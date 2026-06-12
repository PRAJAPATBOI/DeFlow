"""Pricing engine + blended deal-risk scoring.

All arithmetic is done in Decimal and rounded half-up to 2 dp, the way an invoice would be.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from ..models import AppSetting, Customer, DiscountTier, Quotation

CENT = Decimal("0.01")
PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}

DEFAULT_SETTINGS = {
    "company_name": "DealFlow360 Technologies Pvt. Ltd.",
    "currency": "INR",
    "min_margin_percent": "25",
    "manager_threshold": "25",
    "finance_threshold": "55",
    "quote_validity_days": "30",
}
NUMERIC_SETTINGS = ("min_margin_percent", "manager_threshold", "finance_threshold", "quote_validity_days")


def D(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value if value is not None else 0))


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def load_settings(db: Session) -> dict:
    values = dict(DEFAULT_SETTINGS)
    for row in db.query(AppSetting).all():
        values[row.key] = row.value
    return values


def price_lines(lines: list[dict]) -> dict:
    """Price a list of line dicts. Each line needs quantity, unit_price, unit_cost,
    discount_percent, tax_rate, is_subscription and billing_period."""
    priced = []
    subtotal = discount_total = tax_total = cost_total = net_total = Decimal(0)
    one_time_net = recurring_net = mrr = Decimal(0)
    for line in lines:
        qty = D(line["quantity"])
        gross = money(qty * D(line["unit_price"]))
        discount = money(gross * D(line.get("discount_percent", 0)) / 100)
        net = gross - discount
        tax = money(net * D(line.get("tax_rate", 0)) / 100)
        cost = money(qty * D(line.get("unit_cost", 0)))
        subtotal += gross
        discount_total += discount
        tax_total += tax
        cost_total += cost
        net_total += net
        if line.get("is_subscription"):
            recurring_net += net
            mrr += net / PERIOD_MONTHS.get(line.get("billing_period") or "monthly", 1)
        else:
            one_time_net += net
        priced.append({**line, "gross": gross, "discount_amount": discount, "line_total": net, "tax_amount": tax,
                       "line_cost": cost,
                       "margin_percent": money((net - cost) / net * 100) if net > 0 else Decimal(0)})
    margin = money((net_total - cost_total) / net_total * 100) if net_total > 0 else Decimal(0)
    return {
        "lines": priced,
        "subtotal": subtotal, "discount_total": discount_total, "net_total": net_total,
        "tax_total": tax_total, "total": net_total + tax_total, "cost_total": cost_total,
        "margin_percent": margin, "one_time_total": one_time_net, "recurring_total": recurring_net,
        "mrr": money(mrr),
    }


def tier_limits(db: Session) -> tuple[dict, Decimal | None]:
    by_category, default = {}, None
    for tier in db.query(DiscountTier).all():
        if tier.category:
            by_category[tier.category] = D(tier.max_discount_percent)
        else:
            default = D(tier.max_discount_percent)
    return by_category, default


def assess_risk(db: Session, pricing: dict, customer: Customer | None, payment_terms_days: int) -> dict:
    """Blend four signals into a 0-100 risk score and decide who must approve.

    * discount over policy  (max 40) - value-weighted % above the category's discount tier
    * margin erosion        (max 30) - points below the minimum blended margin
    * credit exposure       (max 25) - deal total vs the customer's credit limit; a deal that
                                       exceeds the limit reaches the manager threshold on its own
    * payment terms         (max 15) - credit days beyond net-30
    The total is capped at 100.
    """
    cfg = load_settings(db)
    by_category, default = tier_limits(db)
    drivers = []

    weighted_excess = Decimal(0)
    gross_total = pricing["subtotal"]
    for line in pricing["lines"]:
        limit = by_category.get(line.get("category"), default)
        if limit is None:
            continue
        excess = D(line.get("discount_percent", 0)) - limit
        if excess > 0 and gross_total > 0:
            weighted_excess += excess * line["gross"] / gross_total
    discount_pts = min(Decimal(40), weighted_excess * 4)
    if discount_pts > 0:
        drivers.append({"factor": "discount", "points": float(money(discount_pts)),
                        "detail": f"Discounts exceed policy by {money(weighted_excess)}% (value-weighted)"})

    margin_pts = Decimal(0)
    if pricing["net_total"] > 0:
        gap = D(cfg["min_margin_percent"]) - pricing["margin_percent"]
        margin_pts = min(Decimal(30), max(Decimal(0), gap * 2))
        if margin_pts > 0:
            drivers.append({"factor": "margin", "points": float(money(margin_pts)),
                            "detail": f"Blended margin {pricing['margin_percent']}% is below the "
                                      f"{cfg['min_margin_percent']}% floor"})

    credit_pts = Decimal(0)
    if customer is not None and D(customer.credit_limit) > 0:
        ratio = pricing["total"] / D(customer.credit_limit)
        credit_pts = min(Decimal(25), max(Decimal(0), (ratio - Decimal("0.5")) * 50))
        if credit_pts > 0:
            drivers.append({"factor": "credit", "points": float(money(credit_pts)),
                            "detail": f"Deal value is {money(ratio * 100)}% of the customer's credit limit"})

    terms_pts = min(Decimal(15), max(Decimal(0), D(payment_terms_days - 30) / 60 * 15))
    if terms_pts > 0:
        drivers.append({"factor": "terms", "points": float(money(terms_pts)),
                        "detail": f"Net-{payment_terms_days} payment terms extend credit beyond net-30"})

    score = money(min(Decimal(100), discount_pts + margin_pts + credit_pts + terms_pts))
    if score >= D(cfg["finance_threshold"]):
        level, required = "high", 2
    elif score >= D(cfg["manager_threshold"]):
        level, required = "medium", 1
    else:
        level, required = "low", 0
    return {"score": score, "level": level, "required_level": required, "drivers": drivers}


def line_dicts(quotation: Quotation) -> list[dict]:
    return [{
        "id": l.id, "product_id": l.product_id, "name": l.product.name if l.product else "",
        "sku": l.product.sku if l.product else "", "category": l.product.category if l.product else None,
        "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price,
        "unit_cost": l.unit_cost, "discount_percent": l.discount_percent, "tax_rate": l.tax_rate,
        "is_subscription": l.is_subscription, "billing_period": l.billing_period,
    } for l in quotation.lines]


def reprice(db: Session, quotation: Quotation) -> tuple[dict, dict]:
    """Recompute and persist the pricing + risk snapshot on a quotation."""
    pricing = price_lines(line_dicts(quotation))
    for line, priced in zip(quotation.lines, pricing["lines"]):
        line.line_total = priced["line_total"]
    quotation.subtotal = pricing["subtotal"]
    quotation.discount_total = pricing["discount_total"]
    quotation.tax_total = pricing["tax_total"]
    quotation.total = pricing["total"]
    quotation.margin_percent = pricing["margin_percent"]
    risk = assess_risk(db, pricing, quotation.customer, quotation.payment_terms_days)
    quotation.risk_score = risk["score"]
    quotation.risk_level = risk["level"]
    return pricing, risk
