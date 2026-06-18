"""Quotations: CRUD, live pricing preview, approval workflow, negotiation and what-if tools."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, NegotiationMessage, Product, QStatus, Quotation, QuotationLine, Role, User, utcnow
from ..schemas import CounterResponseIn, DecisionIn, LineIn, MessageIn, PreviewIn, QuotationIn, ReasonIn
from ..security import internal_user, sales_user
from ..serializers import (f, iso, message_out, pricing_out, quotation_detail, quotation_summary, risk_out)
from ..services import billing, fulfillment, workflow
from ..services.pricing import (D, PERIOD_MONTHS, assess_risk, line_dicts, load_settings, money, price_lines,
                                reprice, tier_limits)
from ..services.workflow import WorkflowError

router = APIRouter(tags=["quotations"])


def _fail(err: WorkflowError):
    raise HTTPException(err.status_code, err.message)


def get_quote(db: Session, quotation_id: int, user: User) -> Quotation:
    q = db.get(Quotation, quotation_id)
    if not q or (user.role == Role.REP and q.rep_id != user.id):
        raise HTTPException(404, "Quotation not found")
    return q


def _detail(db: Session, q: Quotation) -> dict:
    pricing = price_lines(line_dicts(q))
    risk = assess_risk(db, pricing, q.customer, q.payment_terms_days)
    return quotation_detail(q, risk)


def _build_lines(db: Session, lines: list[LineIn]) -> list[QuotationLine]:
    built = []
    for item in lines:
        product = db.get(Product, item.product_id)
        if not product or not product.is_active:
            raise HTTPException(422, f"Product #{item.product_id} is not available")
        built.append(QuotationLine(
            product=product, product_id=product.id, description=item.description, quantity=item.quantity,
            unit_price=item.unit_price if item.unit_price is not None else product.price, unit_cost=product.cost,
            discount_percent=item.discount_percent, tax_rate=product.tax_rate,
            is_subscription=product.is_subscription, billing_period=product.billing_period))
    return built


@router.get("/quotations")
def list_quotations(status: str = "", q: str = "", customer_id: int | None = None,
                    user: User = Depends(internal_user), db: Session = Depends(get_db)):
    workflow.expire_stale(db)
    query = db.query(Quotation).join(Customer)
    if user.role == Role.REP:
        query = query.filter(Quotation.rep_id == user.id)
    if status:
        query = query.filter(Quotation.status.in_(status.split(",")))
    if customer_id:
        query = query.filter(Quotation.customer_id == customer_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Quotation.title).like(like), func.lower(Quotation.number).like(like),
                                 func.lower(Customer.name).like(like)))
    return [quotation_summary(x) for x in query.order_by(Quotation.updated_at.desc(), Quotation.id.desc()).all()]


@router.post("/quotations/preview")
def preview(body: PreviewIn, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    """Live pricing + risk for the quote builder; nothing is saved."""
    lines = _build_lines(db, body.lines)
    by_category, default = tier_limits(db)
    dicts = [{"product_id": l.product_id, "name": l.product.name, "sku": l.product.sku,
              "category": l.product.category, "quantity": l.quantity, "unit_price": l.unit_price,
              "unit_cost": l.unit_cost, "discount_percent": l.discount_percent, "tax_rate": l.tax_rate,
              "is_subscription": l.is_subscription, "billing_period": l.billing_period} for l in lines]
    pricing = price_lines(dicts)
    customer = db.get(Customer, body.customer_id) if body.customer_id else None
    risk = assess_risk(db, pricing, customer, body.payment_terms_days)
    out = pricing_out(pricing)
    for line in out["lines"]:
        limit = by_category.get(line["category"], default)
        line["max_discount"] = f(limit) if limit is not None else None
    return {"pricing": out, "risk": risk_out(risk)}


@router.post("/quotations", status_code=201)
def create_quotation(body: QuotationIn, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    customer = db.get(Customer, body.customer_id)
    if not customer:
        raise HTTPException(422, "Customer not found")
    now = utcnow()
    validity = int(load_settings(db)["quote_validity_days"])
    q = Quotation(title=body.title.strip(), customer_id=customer.id, rep_id=user.id, status=QStatus.DRAFT,
                  valid_until=body.valid_until or (now.date() + timedelta(days=validity)),
                  payment_terms_days=body.payment_terms_days, notes=body.notes, lines=_build_lines(db, body.lines))
    db.add(q)
    db.flush()
    q.number = f"Q-{now.year}-{q.id:04d}"
    db.flush()
    db.refresh(q)
    reprice(db, q)
    workflow.add_event(db, q, user, "created", None, now)
    workflow.audit(db, user, "quotation.create", "quotation", q.id, q.number)
    db.commit()
    return _detail(db, q)


@router.get("/quotations/{quotation_id}")
def get_quotation(quotation_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return _detail(db, get_quote(db, quotation_id, user))


@router.put("/quotations/{quotation_id}")
def update_quotation(quotation_id: int, body: QuotationIn, user: User = Depends(sales_user),
                     db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    if q.status != QStatus.DRAFT:
        raise HTTPException(409, "Only draft quotations can be edited. Create a revision instead.")
    if not db.get(Customer, body.customer_id):
        raise HTTPException(422, "Customer not found")
    q.title, q.customer_id, q.notes = body.title.strip(), body.customer_id, body.notes
    q.payment_terms_days = body.payment_terms_days
    if body.valid_until:
        q.valid_until = body.valid_until
    q.lines = _build_lines(db, body.lines)
    db.flush()
    db.refresh(q)
    reprice(db, q)
    workflow.audit(db, user, "quotation.update", "quotation", q.id, q.number)
    db.commit()
    return _detail(db, q)


@router.delete("/quotations/{quotation_id}", status_code=204)
def delete_quotation(quotation_id: int, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    if q.status != QStatus.DRAFT:
        raise HTTPException(409, "Only draft quotations can be deleted")
    workflow.audit(db, user, "quotation.delete", "quotation", q.id, q.number)
    db.delete(q)
    db.commit()


def _transition(db: Session, q: Quotation, fn, *args):
    try:
        fn(db, q, *args)
    except WorkflowError as err:
        db.rollback()
        _fail(err)
    db.commit()
    db.refresh(q)
    return _detail(db, q)


@router.post("/quotations/{quotation_id}/submit")
def submit(quotation_id: int, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.submit, user)


@router.post("/quotations/{quotation_id}/approve")
def approve(quotation_id: int, body: DecisionIn, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.decide, user, "approve", body.comment)


@router.post("/quotations/{quotation_id}/reject")
def reject(quotation_id: int, body: DecisionIn, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.decide, user, "reject", body.comment)


@router.post("/quotations/{quotation_id}/request-changes")
def request_changes(quotation_id: int, body: DecisionIn, user: User = Depends(internal_user),
                    db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.decide, user, "request_changes", body.comment)


@router.post("/quotations/{quotation_id}/send")
def send(quotation_id: int, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.send, user)


@router.post("/quotations/{quotation_id}/mark-lost")
def mark_lost(quotation_id: int, body: ReasonIn, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    return _transition(db, get_quote(db, quotation_id, user), workflow.mark_lost, user, body.reason)


@router.post("/quotations/{quotation_id}/mark-won")
def mark_won(quotation_id: int, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    """Record an acceptance received offline (signed PO, email) on the customer's behalf."""
    q = get_quote(db, quotation_id, user)
    return _transition(db, q, workflow.accept, f"{q.customer.name} (recorded by {user.name})", user)


@router.post("/quotations/{quotation_id}/duplicate", status_code=201)
def duplicate(quotation_id: int, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    new = workflow.duplicate(db, get_quote(db, quotation_id, user), user)
    db.commit()
    return _detail(db, new)


# ----------------------------------------------------------------------------- negotiation
@router.post("/quotations/{quotation_id}/messages", status_code=201)
def post_message(quotation_id: int, body: MessageIn, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    try:
        msg = workflow.post_message(db, q, user, user.name, "internal", body.message)
    except WorkflowError as err:
        _fail(err)
    db.commit()
    return message_out(msg)


@router.get("/quotations/{quotation_id}/messages/{message_id}/impact")
def counter_impact(quotation_id: int, message_id: int, user: User = Depends(internal_user),
                   db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    msg = db.get(NegotiationMessage, message_id)
    if not msg or msg.quotation_id != q.id or msg.proposed_discount is None:
        raise HTTPException(404, "Counter-offer not found")
    impact = workflow.counter_impact(db, q, msg.proposed_discount)
    return {"current_total": f(q.total), "current_margin_percent": f(q.margin_percent),
            "new_total": f(impact["total"]), "new_margin_percent": f(impact["margin_percent"]),
            "revenue_delta": round(f(impact["total"]) - f(q.total), 2), "risk": risk_out(impact["risk"]),
            "needs_reapproval": impact["needs_reapproval"]}


@router.post("/quotations/{quotation_id}/messages/{message_id}/respond")
def respond_counter(quotation_id: int, message_id: int, body: CounterResponseIn,
                    user: User = Depends(sales_user), db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    msg = db.get(NegotiationMessage, message_id)
    if not msg or msg.quotation_id != q.id or msg.proposed_discount is None:
        raise HTTPException(404, "Counter-offer not found")
    return _transition(db, q, workflow.respond_counter, msg, user, body.accept, body.comment)


# ----------------------------------------------------------------------------- what-if tools
@router.get("/quotations/{quotation_id}/fulfillment-plan")
def fulfillment_plan(quotation_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    q = get_quote(db, quotation_id, user)
    plan = fulfillment.plan_split(db, fulfillment.physical_demand(q), q.customer.region)
    names = {l.product_id: l.product.name for l in q.lines}
    return {
        "fully_allocated": plan["fully_allocated"], "shipment_count": plan["shipment_count"],
        "total_units": plan["total_units"], "total_shipping_cost": f(plan["total_shipping_cost"]),
        "shipments": [{**{k: s[k] for k in ("warehouse_id", "warehouse", "code", "city", "region", "units",
                                             "lead_days")},
                       "shipping_cost": f(s["shipping_cost"]),
                       "items": [{"product_id": pid, "product": names.get(pid), "quantity": qty}
                                 for pid, qty in s["items"].items()]} for s in plan["shipments"]],
        "backorder": [{"product_id": pid, "product": names.get(pid), "quantity": qty}
                      for pid, qty in plan["backorder"].items()],
    }


@router.get("/quotations/{quotation_id}/billing-schedule")
def billing_schedule(quotation_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    """Projected cash-flow if the customer accepted today: upfront invoice + 12 months of recurring."""
    q = get_quote(db, quotation_id, user)
    today = utcnow().date()
    pricing = price_lines(line_dicts(q))
    one_time = [l for l in pricing["lines"] if not l["is_subscription"]]
    upfront = sum((l["line_total"] + l["tax_amount"] for l in one_time), D(0))
    schedule, subs = [], []
    horizon = billing.add_months(today, 12)
    for l in pricing["lines"]:
        if not l["is_subscription"]:
            continue
        period = l["billing_period"] or "monthly"
        tax = 1 + D(l["tax_rate"]) / 100
        first = billing.proration(today, l["line_total"], period)
        subs.append({"product": l["name"], "billing_period": period, "period_amount": f(l["line_total"]),
                     "first_charge": f(first["amount"] * tax), "prorated": first["prorated"],
                     "prorated_days": first["days"], "next_billing_date": iso(first["next_billing_date"])})
        schedule.append((today, first["amount"] * tax, f"{l['name']} - first charge"))
        when = first["next_billing_date"]
        while when < horizon:
            schedule.append((when, l["line_total"] * tax, f"{l['name']} - {period}"))
            when = billing.add_months(when, PERIOD_MONTHS[period])
    if upfront > 0:
        schedule.append((today, upfront, "One-time items"))
    by_date: dict = {}
    for when, amount, label in schedule:
        entry = by_date.setdefault(when, {"date": iso(when), "amount": D(0), "items": []})
        entry["amount"] += amount
        entry["items"].append(label)
    timeline = [{**v, "amount": f(money(v["amount"]))} for _, v in sorted(by_date.items())]
    return {"one_time_total": f(upfront), "mrr": f(pricing["mrr"]), "subscriptions": subs, "timeline": timeline,
            "first_year_value": round(sum(t["amount"] for t in timeline), 2)}


# ----------------------------------------------------------------------------- approvals
@router.get("/approvals/queue", tags=["approvals"])
def approval_queue(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    """Quotations waiting for a decision. `can_act` tells the UI whether it is this user's turn."""
    pending = (db.query(Quotation).filter(Quotation.status.in_((QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE)))
               .order_by(Quotation.submitted_at).all())
    if user.role == Role.REP:
        pending = [q for q in pending if q.rep_id == user.id]
    out = []
    now = utcnow()
    for q in pending:
        level_roles = (Role.MANAGER, Role.ADMIN) if q.status == QStatus.PENDING_MANAGER else (Role.FINANCE, Role.ADMIN)
        pricing = price_lines(line_dicts(q))
        risk = assess_risk(db, pricing, q.customer, q.payment_terms_days)
        out.append({**quotation_summary(q), "risk": risk_out(risk),
                    "waiting_hours": round((now - (q.submitted_at or q.created_at)).total_seconds() / 3600, 1),
                    "can_act": user.role in level_roles and (q.rep_id != user.id or user.role == Role.ADMIN)})
    return out


@router.get("/approvals/history", tags=["approvals"])
def approval_history(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    from ..models import QuotationEvent
    query = (db.query(QuotationEvent).join(Quotation)
             .filter(QuotationEvent.action.in_(("approved", "rejected", "changes_requested", "auto_approved"))))
    if user.role == Role.REP:
        query = query.filter(Quotation.rep_id == user.id)
    rows = query.order_by(QuotationEvent.id.desc()).limit(50).all()
    return [{"id": e.id, "action": e.action, "actor_name": e.actor_name, "comment": e.comment,
             "created_at": iso(e.created_at), "quotation_id": e.quotation_id, "number": e.quotation.number,
             "title": e.quotation.title, "customer_name": e.quotation.customer.name,
             "total": f(e.quotation.total)} for e in rows]
