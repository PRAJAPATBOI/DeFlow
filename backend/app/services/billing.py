"""Invoicing, subscription billing with first-period proration, and payments.

Recurring billing is anchored to the 1st of the month. A subscription that starts mid-month
is charged a daily pro-rata amount for the rest of that month; full periods start on the next 1st.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Invoice, InvoiceLine, Payment, Quotation, Subscription, utcnow
from .pricing import D, PERIOD_MONTHS, money


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def first_of_next_month(d: date) -> date:
    return add_months(d.replace(day=1), 1)


def proration(start: date, period_price: Decimal, billing_period: str) -> dict:
    """First charge for a subscription starting on `start`."""
    months = PERIOD_MONTHS.get(billing_period, 1)
    if start.day == 1:
        end = add_months(start, months) - timedelta(days=1)
        return {"amount": money(period_price), "period_start": start, "period_end": end,
                "next_billing_date": add_months(start, months), "prorated": False, "days": None}
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    days = days_in_month - start.day + 1
    monthly = D(period_price) / months
    return {"amount": money(monthly * days / days_in_month), "period_start": start,
            "period_end": start.replace(day=days_in_month), "next_billing_date": first_of_next_month(start),
            "prorated": True, "days": days}


def _finalise(db: Session, invoice: Invoice) -> Invoice:
    invoice.subtotal = sum((D(l.amount) for l in invoice.lines), Decimal(0))
    invoice.tax_total = sum((money(D(l.amount) * D(l.tax_rate) / 100) for l in invoice.lines), Decimal(0))
    invoice.total = invoice.subtotal + invoice.tax_total
    db.add(invoice)
    db.flush()
    invoice.number = f"INV-{invoice.issue_date.year}-{invoice.id:04d}"
    return invoice


def _net_unit(line) -> Decimal:
    return money(D(line.unit_price) * (100 - D(line.discount_percent)) / 100)


def bill_accepted_quotation(db: Session, quotation: Quotation, today: date) -> dict:
    """Order-to-cash on acceptance: one invoice for one-time items, a subscription (plus a
    pro-rated first invoice) for every recurring line."""
    terms = quotation.payment_terms_days
    invoices, subscriptions = [], []

    one_time = [l for l in quotation.lines if not l.is_subscription]
    if one_time:
        inv = Invoice(quotation_id=quotation.id, customer_id=quotation.customer_id, kind="one_time",
                      issue_date=today, due_date=today + timedelta(days=terms))
        for l in one_time:
            inv.lines.append(InvoiceLine(description=l.product.name, quantity=l.quantity, unit_price=_net_unit(l),
                                         tax_rate=l.tax_rate, amount=l.line_total))
        invoices.append(_finalise(db, inv))

    for l in quotation.lines:
        if not l.is_subscription:
            continue
        period = l.billing_period or "monthly"
        unit = _net_unit(l)
        first = proration(today, unit * l.quantity, period)
        sub = Subscription(quotation_id=quotation.id, customer_id=quotation.customer_id, product_id=l.product_id,
                           quantity=l.quantity, unit_price=unit, tax_rate=l.tax_rate, billing_period=period,
                           status="active", start_date=today, next_billing_date=first["next_billing_date"])
        db.add(sub)
        db.flush()
        inv = Invoice(quotation_id=quotation.id, customer_id=quotation.customer_id, subscription_id=sub.id,
                      kind="recurring", issue_date=today, due_date=today + timedelta(days=terms),
                      period_start=first["period_start"], period_end=first["period_end"])
        label = f"{l.product.name} ({period})"
        if first["prorated"]:
            label += f" - pro-rated {first['days']} days"
        inv.lines.append(InvoiceLine(description=label, quantity=l.quantity, unit_price=unit,
                                     tax_rate=l.tax_rate, amount=first["amount"]))
        invoices.append(_finalise(db, inv))
        subscriptions.append(sub)
    return {"invoices": invoices, "subscriptions": subscriptions}


def run_billing(db: Session, as_of: date, payment_terms_days: int = 30) -> list[Invoice]:
    """Generate invoices for every active subscription that is due on or before `as_of`."""
    created = []
    due = (db.query(Subscription).filter(Subscription.status == "active",
                                         Subscription.next_billing_date <= as_of).all())
    for sub in due:
        months = PERIOD_MONTHS.get(sub.billing_period, 1)
        guard = 0
        while sub.next_billing_date and sub.next_billing_date <= as_of and guard < 36:
            guard += 1
            start = sub.next_billing_date
            end = add_months(start, months) - timedelta(days=1)
            terms = sub.quotation.payment_terms_days if sub.quotation else payment_terms_days
            inv = Invoice(quotation_id=sub.quotation_id, customer_id=sub.customer_id, subscription_id=sub.id,
                          kind="recurring", issue_date=start, due_date=start + timedelta(days=terms),
                          period_start=start, period_end=end)
            inv.lines.append(InvoiceLine(description=f"{sub.product.name} ({sub.billing_period})",
                                         quantity=sub.quantity, unit_price=sub.unit_price, tax_rate=sub.tax_rate,
                                         amount=money(D(sub.unit_price) * sub.quantity)))
            created.append(_finalise(db, inv))
            sub.next_billing_date = add_months(start, months)
    return created


def record_payment(db: Session, invoice: Invoice, amount, method: str, reference: str | None,
                   user_id: int | None, paid_at=None) -> Payment:
    amount = money(amount)
    balance = D(invoice.total) - D(invoice.amount_paid)
    if invoice.status == "void":
        raise ValueError("Cannot pay a void invoice")
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    if amount > balance:
        raise ValueError(f"Payment exceeds the outstanding balance of {balance}")
    payment = Payment(amount=amount, method=method, reference=reference, recorded_by=user_id,
                      paid_at=paid_at or utcnow())
    invoice.payments.append(payment)
    invoice.amount_paid = D(invoice.amount_paid) + amount
    invoice.status = "paid" if invoice.amount_paid >= D(invoice.total) else "partially_paid"
    return payment


def subscription_mrr(sub: Subscription) -> Decimal:
    if sub.status != "active":
        return Decimal(0)
    return money(D(sub.unit_price) * sub.quantity / PERIOD_MONTHS.get(sub.billing_period, 1))


def is_overdue(invoice: Invoice, today: date) -> bool:
    return invoice.status in ("issued", "partially_paid") and invoice.due_date < today
