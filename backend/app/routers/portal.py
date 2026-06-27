"""Customer portal.

Two ways in:
  * a secure, unguessable link (`/portal?token=...`) e-mailed with the quotation - no login needed
  * a customer account, which sees every quotation and invoice of its own company
Customer responses never expose cost, margin or risk data.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, QStatus, Quotation, Role, User
from ..schemas import PortalActionIn, PortalMessageIn
from ..security import require_roles
from ..serializers import invoice_out, quotation_detail, quotation_summary
from ..services import workflow
from ..services.pricing import load_settings
from ..services.workflow import WorkflowError

router = APIRouter(prefix="/portal", tags=["portal"])
customer_user = require_roles(Role.CUSTOMER)

VISIBLE = (QStatus.SENT, QStatus.NEGOTIATING, QStatus.ACCEPTED, QStatus.DECLINED, QStatus.EXPIRED,
           QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE, QStatus.APPROVED)


def _by_token(db: Session, token: str) -> Quotation:
    workflow.expire_stale(db)
    q = db.query(Quotation).filter(Quotation.portal_token == token).first() if token else None
    if not q or q.status not in VISIBLE:
        raise HTTPException(404, "This quotation link is invalid or no longer available")
    return q


def _public(db: Session, q: Quotation) -> dict:
    out = quotation_detail(q, risk={}, include_internal=False)
    # While the seller is re-approving revised pricing the customer just sees "being revised".
    out["under_revision"] = q.status in (QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE, QStatus.APPROVED)
    if out["under_revision"]:
        out["status"] = "under_revision"
    out["can_respond"] = q.status in (QStatus.SENT, QStatus.NEGOTIATING)
    out["seller"] = load_settings(db)["company_name"]
    out["rep_email"] = q.rep.email if q.rep else None
    return out


def _run(db: Session, q: Quotation, fn, *args, **kwargs):
    try:
        fn(db, q, *args, **kwargs)
    except WorkflowError as err:
        db.rollback()
        raise HTTPException(err.status_code, err.message)
    db.commit()
    db.refresh(q)
    return _public(db, q)


@router.get("/quotes/{token}")
def view_quote(token: str, db: Session = Depends(get_db)):
    return _public(db, _by_token(db, token))


@router.post("/quotes/{token}/accept")
def accept_quote(token: str, body: PortalActionIn, db: Session = Depends(get_db)):
    return _run(db, _by_token(db, token), workflow.accept, body.name)


@router.post("/quotes/{token}/decline")
def decline_quote(token: str, body: PortalActionIn, db: Session = Depends(get_db)):
    return _run(db, _by_token(db, token), workflow.decline, body.name, body.reason)


@router.post("/quotes/{token}/messages")
def portal_message(token: str, body: PortalMessageIn, db: Session = Depends(get_db)):
    return _run(db, _by_token(db, token), workflow.post_message, None, body.name, "customer", body.message,
                body.proposed_discount)


@router.get("/my/overview")
def my_overview(user: User = Depends(customer_user), db: Session = Depends(get_db)):
    workflow.expire_stale(db)
    quotes = (db.query(Quotation).filter(Quotation.customer_id == user.customer_id,
                                         Quotation.status.in_(VISIBLE), Quotation.portal_token.isnot(None))
              .order_by(Quotation.id.desc()).all())
    invoices = db.query(Invoice).filter(Invoice.customer_id == user.customer_id).order_by(Invoice.id.desc()).all()
    hidden = ("margin_percent", "risk_score", "risk_level", "approved_level", "rep_id")
    return {
        "company": user.customer.name if user.customer else None,
        "quotations": [{**{k: v for k, v in quotation_summary(q).items() if k not in hidden},
                        "status": "under_revision" if q.status in VISIBLE[5:] else q.status,
                        "portal_token": q.portal_token} for q in quotes],
        "invoices": [invoice_out(i, detail=True) for i in invoices if i.status != "void"],
    }
