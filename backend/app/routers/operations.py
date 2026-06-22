"""Post-sale operations: fulfilment orders, invoices & payments, subscriptions."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FulfillmentOrder, Invoice, Quotation, Role, Subscription, User, utcnow
from ..schemas import PaymentIn, RunBillingIn
from ..security import finance_user, internal_user, manager_user
from ..serializers import f, invoice_out, order_out, subscription_out
from ..services import billing, fulfillment
from ..services.workflow import audit

router = APIRouter()


def _rep_scope(query, user: User):
    return query.filter(Quotation.rep_id == user.id) if user.role == Role.REP else query


# ----------------------------------------------------------------------------- fulfilment
@router.get("/fulfillment/orders", tags=["fulfillment"])
def list_orders(status: str = "", user: User = Depends(internal_user), db: Session = Depends(get_db)):
    query = _rep_scope(db.query(FulfillmentOrder).join(Quotation), user)
    if status:
        query = query.filter(FulfillmentOrder.status.in_(status.split(",")))
    return [order_out(o) for o in query.order_by(FulfillmentOrder.id.desc()).all()]


@router.post("/fulfillment/orders/{order_id}/advance", tags=["fulfillment"])
def advance_order(order_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    order = db.get(FulfillmentOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        fulfillment.advance(db, order)
    except ValueError as err:
        raise HTTPException(409, str(err))
    audit(db, user, "fulfillment.advance", "fulfillment_order", order.id, f"{order.number} -> {order.status}")
    db.commit()
    return order_out(order)


@router.post("/fulfillment/orders/{order_id}/allocate", tags=["fulfillment"])
def allocate_backorder(order_id: int, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    order = db.get(FulfillmentOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        created = fulfillment.allocate_backorder(db, order)
    except ValueError as err:
        raise HTTPException(409, str(err))
    audit(db, user, "fulfillment.allocate", "fulfillment_order", order_id, f"{len(created)} shipment(s) released")
    db.commit()
    return {"created": [order_out(o) for o in created],
            "remaining_backorder": db.get(FulfillmentOrder, order_id) is not None}


# ----------------------------------------------------------------------------- invoices
@router.get("/invoices", tags=["invoices"])
def list_invoices(status: str = "", user: User = Depends(internal_user), db: Session = Depends(get_db)):
    query = db.query(Invoice)
    if user.role == Role.REP:
        query = query.join(Quotation).filter(Quotation.rep_id == user.id)
    rows = [invoice_out(i) for i in query.order_by(Invoice.issue_date.desc(), Invoice.id.desc()).all()]
    if status:
        rows = [r for r in rows if r["status"] in status.split(",")]
    live = [r for r in rows if r["status"] != "void"]
    summary = {"billed": round(sum(r["total"] for r in live), 2),
               "collected": round(sum(r["amount_paid"] for r in live), 2),
               "outstanding": round(sum(r["balance"] for r in live), 2),
               "overdue": round(sum(r["balance"] for r in live if r["status"] == "overdue"), 2)}
    return {"summary": summary, "invoices": rows}


def _invoice(db: Session, invoice_id: int, user: User) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv or (user.role == Role.REP and (not inv.quotation or inv.quotation.rep_id != user.id)):
        raise HTTPException(404, "Invoice not found")
    return inv


@router.get("/invoices/{invoice_id}", tags=["invoices"])
def get_invoice(invoice_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return invoice_out(_invoice(db, invoice_id, user), detail=True)


@router.post("/invoices/{invoice_id}/payments", status_code=201, tags=["invoices"])
def pay_invoice(invoice_id: int, body: PaymentIn, user: User = Depends(finance_user), db: Session = Depends(get_db)):
    inv = _invoice(db, invoice_id, user)
    try:
        billing.record_payment(db, inv, body.amount, body.method, body.reference, user.id)
    except ValueError as err:
        raise HTTPException(409, str(err))
    audit(db, user, "invoice.payment", "invoice", inv.id, f"{inv.number}: {body.amount} via {body.method}")
    db.commit()
    return invoice_out(inv, detail=True)


@router.post("/invoices/{invoice_id}/void", tags=["invoices"])
def void_invoice(invoice_id: int, user: User = Depends(finance_user), db: Session = Depends(get_db)):
    inv = _invoice(db, invoice_id, user)
    if f(inv.amount_paid) > 0:
        raise HTTPException(409, "An invoice with payments cannot be voided")
    inv.status = "void"
    audit(db, user, "invoice.void", "invoice", inv.id, inv.number)
    db.commit()
    return invoice_out(inv, detail=True)


# ----------------------------------------------------------------------------- subscriptions
@router.get("/subscriptions", tags=["subscriptions"])
def list_subscriptions(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    query = _rep_scope(db.query(Subscription).join(Quotation), user)
    rows = [subscription_out(s) for s in query.order_by(Subscription.id.desc()).all()]
    active = [r for r in rows if r["status"] == "active"]
    mrr = round(sum(r["mrr"] for r in active), 2)
    today = utcnow().date()
    return {"summary": {"mrr": mrr, "arr": round(mrr * 12, 2), "active": len(active),
                        "paused": sum(1 for r in rows if r["status"] == "paused"),
                        "cancelled": sum(1 for r in rows if r["status"] == "cancelled"),
                        "due_now": sum(1 for r in active if r["next_billing_date"] and
                                       r["next_billing_date"] <= today.isoformat())},
            "subscriptions": rows}


@router.post("/subscriptions/run-billing", tags=["subscriptions"])
def run_billing(body: RunBillingIn, user: User = Depends(finance_user), db: Session = Depends(get_db)):
    as_of = body.as_of or utcnow().date()
    created = billing.run_billing(db, as_of)
    audit(db, user, "billing.run", "subscription", None, f"{len(created)} invoice(s) as of {as_of}")
    db.commit()
    return {"as_of": as_of.isoformat(), "invoices_created": len(created),
            "total_billed": round(sum(f(i.total) for i in created), 2),
            "invoices": [invoice_out(i) for i in created]}


@router.post("/subscriptions/{subscription_id}/{action}", tags=["subscriptions"])
def change_subscription(subscription_id: int, action: str, user: User = Depends(finance_user),
                        db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    transitions = {"pause": ("active", "paused"), "resume": ("paused", "active"), "cancel": (None, "cancelled")}
    if action not in transitions:
        raise HTTPException(404, "Unknown action")
    required, target = transitions[action]
    if sub.status == "cancelled" or (required and sub.status != required):
        raise HTTPException(409, f"A {sub.status} subscription cannot be {action}d")
    sub.status = target
    today = utcnow().date()
    if action == "cancel":
        sub.cancelled_at, sub.next_billing_date = utcnow(), None
    elif action == "resume" and sub.next_billing_date and sub.next_billing_date < today:
        sub.next_billing_date = billing.first_of_next_month(today)  # no back-billing for the paused time
    audit(db, user, f"subscription.{action}", "subscription", sub.id, sub.product.name)
    db.commit()
    return subscription_out(sub)
