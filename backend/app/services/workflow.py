"""Quotation lifecycle state machine.

draft -> (auto) approved | pending_manager -> pending_finance -> approved -> sent
      -> negotiating <-> sent -> accepted (order-to-cash) | declined | lost | expired
"""
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import (AuditLog, NegotiationMessage, QStatus, Quotation, QuotationEvent, QuotationLine, Role,
                      User, utcnow)
from . import billing, fulfillment
from .pricing import D, load_settings, price_lines, line_dicts, assess_risk, reprice


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def audit(db: Session, actor: User | None, action: str, entity: str, entity_id: int | None, detail: str = "",
          now=None):
    db.add(AuditLog(actor_id=actor.id if actor else None, actor_name=actor.name if actor else "System",
                    action=action, entity=entity, entity_id=entity_id, detail=detail, created_at=now or utcnow()))


def add_event(db, q: Quotation, actor: User | None, action: str, comment: str | None = None, now=None,
              actor_name: str | None = None):
    q.events.append(QuotationEvent(actor_id=actor.id if actor else None,
                                   actor_name=actor_name or (actor.name if actor else "System"),
                                   action=action, comment=comment, created_at=now or utcnow()))


def _require(q: Quotation, *statuses):
    if q.status not in statuses:
        raise WorkflowError(f"Quotation {q.number} is '{q.status}'; this action needs: {', '.join(statuses)}")


def _route_for_approval(q: Quotation, required_level: int) -> str:
    """Pick the next status given what has already been signed off."""
    if required_level <= q.approved_level:
        return QStatus.APPROVED
    return QStatus.PENDING_MANAGER if q.approved_level < 1 else QStatus.PENDING_FINANCE


def submit(db: Session, q: Quotation, actor: User, now=None) -> Quotation:
    now = now or utcnow()
    _require(q, QStatus.DRAFT)
    if not q.lines:
        raise WorkflowError("Add at least one line item before submitting", 422)
    _, risk = reprice(db, q)
    q.submitted_at = now
    q.approved_level = 0
    add_event(db, q, actor, "submitted", f"Risk score {risk['score']} ({risk['level']})", now)
    if risk["required_level"] == 0:
        q.status = QStatus.APPROVED
        add_event(db, q, None, "auto_approved", "Within discount, margin and credit policy", now)
    else:
        q.status = QStatus.PENDING_MANAGER
    audit(db, actor, "quotation.submit", "quotation", q.id, f"{q.number} -> {q.status}", now=now)
    return q


def decide(db: Session, q: Quotation, actor: User, decision: str, comment: str | None = None, now=None):
    now = now or utcnow()
    _require(q, QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE)
    level = 1 if q.status == QStatus.PENDING_MANAGER else 2
    allowed = (Role.MANAGER, Role.ADMIN) if level == 1 else (Role.FINANCE, Role.ADMIN)
    if actor.role not in allowed:
        who = "a Sales Manager" if level == 1 else "Finance"
        raise WorkflowError(f"This quotation is waiting for {who}", 403)
    if actor.id == q.rep_id and actor.role != Role.ADMIN:
        raise WorkflowError("You cannot approve your own quotation", 403)
    if decision in ("reject", "request_changes") and not (comment or "").strip():
        raise WorkflowError("A comment is required when rejecting or requesting changes", 422)

    if decision == "approve":
        _, risk = reprice(db, q)
        q.approved_level = level
        q.status = _route_for_approval(q, risk["required_level"])
        add_event(db, q, actor, "approved", comment or ("Manager approval" if level == 1 else "Finance approval"), now)
    elif decision == "reject":
        q.status, q.closed_at = QStatus.REJECTED, now
        add_event(db, q, actor, "rejected", comment, now)
    elif decision == "request_changes":
        q.status, q.approved_level = QStatus.DRAFT, 0
        add_event(db, q, actor, "changes_requested", comment, now)
    else:
        raise WorkflowError("Unknown decision", 422)
    audit(db, actor, f"quotation.{decision}", "quotation", q.id, f"{q.number} -> {q.status}", now=now)
    return q


def send(db: Session, q: Quotation, actor: User, now=None):
    now = now or utcnow()
    _require(q, QStatus.APPROVED)
    if not q.portal_token:
        q.portal_token = secrets.token_urlsafe(24)
    if not q.valid_until or q.valid_until < now.date():
        q.valid_until = now.date() + timedelta(days=int(load_settings(db)["quote_validity_days"]))
    q.status, q.sent_at = QStatus.SENT, now
    add_event(db, q, actor, "sent", f"Shared with {q.customer.name} via secure portal link", now)
    audit(db, actor, "quotation.send", "quotation", q.id, q.number, now=now)
    return q


def accept(db: Session, q: Quotation, actor_name: str, actor: User | None = None, now=None) -> dict:
    """Customer signs off -> reserve stock, raise invoices, start subscriptions."""
    now = now or utcnow()
    _require(q, QStatus.SENT, QStatus.NEGOTIATING)
    if q.valid_until and q.valid_until < now.date():
        raise WorkflowError("This quotation has expired")
    for m in q.messages:
        if m.offer_status == "open":
            m.offer_status = "rejected"
    q.status, q.closed_at = QStatus.ACCEPTED, now
    add_event(db, q, actor, "accepted", "Customer accepted the quotation", now, actor_name=actor_name)
    orders = fulfillment.create_orders(db, q, now)
    billed = billing.bill_accepted_quotation(db, q, now.date())
    add_event(db, q, None, "order_created",
              f"{len(orders)} fulfilment order(s), {len(billed['invoices'])} invoice(s), "
              f"{len(billed['subscriptions'])} subscription(s)", now)
    audit(db, actor, "quotation.accept", "quotation", q.id, f"{q.number} accepted by {actor_name}", now=now)
    return {"orders": orders, **billed}


def decline(db: Session, q: Quotation, actor_name: str, reason: str | None, actor: User | None = None, now=None):
    now = now or utcnow()
    _require(q, QStatus.SENT, QStatus.NEGOTIATING)
    q.status, q.closed_at, q.lost_reason = QStatus.DECLINED, now, (reason or "Declined by customer")[:255]
    add_event(db, q, actor, "declined", reason, now, actor_name=actor_name)
    audit(db, actor, "quotation.decline", "quotation", q.id, q.number, now=now)
    return q


def mark_lost(db: Session, q: Quotation, actor: User, reason: str, now=None):
    now = now or utcnow()
    _require(q, *QStatus.OPEN)
    q.status, q.closed_at, q.lost_reason = QStatus.LOST, now, reason[:255]
    add_event(db, q, actor, "lost", reason, now)
    audit(db, actor, "quotation.lost", "quotation", q.id, q.number, now=now)
    return q


def post_message(db: Session, q: Quotation, author: User | None, author_name: str, side: str, message: str,
                 proposed_discount=None, now=None) -> NegotiationMessage:
    now = now or utcnow()
    _require(q, QStatus.SENT, QStatus.NEGOTIATING)
    if proposed_discount is not None:
        if side != "customer":
            raise WorkflowError("Only the customer can raise a counter-offer", 422)
        if not (0 < D(proposed_discount) <= 90):
            raise WorkflowError("Counter-offer discount must be between 0 and 90%", 422)
        if any(m.offer_status == "open" for m in q.messages):
            raise WorkflowError("There is already an open counter-offer on this quotation")
    msg = NegotiationMessage(author_id=author.id if author else None, author_name=author_name, side=side,
                             message=message, proposed_discount=proposed_discount,
                             offer_status="open" if proposed_discount is not None else None, created_at=now)
    q.messages.append(msg)
    if proposed_discount is not None:
        q.status = QStatus.NEGOTIATING
        add_event(db, q, author, "counter_offer", f"Customer asked for {proposed_discount}% off", now,
                  actor_name=author_name)
    return msg


def counter_impact(db: Session, q: Quotation, discount) -> dict:
    """What-if: pricing and risk if every line were discounted to at least `discount` %."""
    lines = line_dicts(q)
    for l in lines:
        l["discount_percent"] = max(D(l["discount_percent"]), D(discount))
    pricing = price_lines(lines)
    risk = assess_risk(db, pricing, q.customer, q.payment_terms_days)
    return {"total": pricing["total"], "margin_percent": pricing["margin_percent"], "risk": risk,
            "needs_reapproval": risk["required_level"] > q.approved_level}


def respond_counter(db: Session, q: Quotation, msg: NegotiationMessage, actor: User, accept_offer: bool,
                    comment: str | None = None, now=None):
    now = now or utcnow()
    _require(q, QStatus.NEGOTIATING)
    if msg.offer_status != "open":
        raise WorkflowError("This counter-offer has already been answered")
    if accept_offer:
        for line in q.lines:
            line.discount_percent = max(D(line.discount_percent), D(msg.proposed_discount))
        _, risk = reprice(db, q)
        msg.offer_status = "accepted"
        nxt = _route_for_approval(q, risk["required_level"])
        q.status = QStatus.SENT if nxt == QStatus.APPROVED else nxt
        note = f"Accepted {msg.proposed_discount}% counter-offer; new total {q.total}"
        if q.status != QStatus.SENT:
            note += " - re-approval required before it goes back to the customer"
        add_event(db, q, actor, "counter_accepted", note, now)
        reply = comment or f"We can do {msg.proposed_discount}%. The quotation has been updated."
    else:
        msg.offer_status = "rejected"
        q.status = QStatus.SENT
        add_event(db, q, actor, "counter_rejected", comment, now)
        reply = comment or "We are unable to meet that price, but the current offer stands."
    q.messages.append(NegotiationMessage(author_id=actor.id, author_name=actor.name, side="internal",
                                         message=reply, created_at=now))
    audit(db, actor, "quotation.counter_response", "quotation", q.id,
          f"{q.number}: {'accepted' if accept_offer else 'rejected'} {msg.proposed_discount}%", now=now)
    return q


def duplicate(db: Session, q: Quotation, actor: User, now=None) -> Quotation:
    now = now or utcnow()
    validity = int(load_settings(db)["quote_validity_days"])
    new = Quotation(title=q.title, customer_id=q.customer_id, rep_id=actor.id if actor.role == Role.REP else q.rep_id,
                    status=QStatus.DRAFT, version=q.version + 1, parent_id=q.id,
                    valid_until=now.date() + timedelta(days=validity), payment_terms_days=q.payment_terms_days,
                    notes=q.notes, created_at=now, updated_at=now)
    for l in q.lines:
        new.lines.append(QuotationLine(product_id=l.product_id, description=l.description, quantity=l.quantity,
                                       unit_price=l.unit_price, unit_cost=l.unit_cost,
                                       discount_percent=l.discount_percent, tax_rate=l.tax_rate,
                                       is_subscription=l.is_subscription, billing_period=l.billing_period))
    db.add(new)
    db.flush()
    new.number = f"Q-{now.year}-{new.id:04d}"
    db.flush()
    db.refresh(new)
    reprice(db, new)
    add_event(db, new, actor, "created", f"Revision of {q.number}", now)
    return new


def expire_stale(db: Session, today=None) -> int:
    today = today or utcnow().date()
    stale = (db.query(Quotation).filter(Quotation.status.in_((QStatus.APPROVED, QStatus.SENT, QStatus.NEGOTIATING)),
                                        Quotation.valid_until.isnot(None), Quotation.valid_until < today).all())
    for q in stale:
        q.status, q.closed_at = QStatus.EXPIRED, utcnow()
        add_event(db, q, None, "expired", f"Validity ended on {q.valid_until}")
    if stale:
        db.commit()
    return len(stale)
