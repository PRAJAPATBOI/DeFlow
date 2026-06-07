"""Model -> JSON-ready dict converters. Money is emitted as float rounded to 2 dp."""
from datetime import date

from .models import (Customer, FulfillmentOrder, Inventory, Invoice, NegotiationMessage, Product, Quotation,
                     QuotationEvent, Subscription, User, Warehouse, utcnow)
from .services import billing
from .services.pricing import line_dicts, price_lines


def f(value) -> float:
    return round(float(value or 0), 2)


def iso(value):
    return value.isoformat() if value else None


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_active": u.is_active,
            "customer_id": u.customer_id, "customer_name": u.customer.name if u.customer else None,
            "created_at": iso(u.created_at), "last_login_at": iso(u.last_login_at)}


def customer_out(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "industry": c.industry, "contact_name": c.contact_name, "email": c.email,
            "phone": c.phone, "city": c.city, "region": c.region, "gstin": c.gstin, "tier": c.tier,
            "credit_limit": f(c.credit_limit), "payment_terms_days": c.payment_terms_days,
            "owner_id": c.owner_id, "owner_name": c.owner.name if c.owner else None, "created_at": iso(c.created_at)}


def product_out(p: Product, stock: int | None = None) -> dict:
    price, cost = f(p.price), f(p.cost)
    out = {"id": p.id, "sku": p.sku, "name": p.name, "category": p.category, "description": p.description,
           "price": price, "cost": cost, "margin_percent": round((price - cost) / price * 100, 1) if price else 0,
           "unit": p.unit, "tax_rate": f(p.tax_rate), "is_subscription": p.is_subscription,
           "billing_period": p.billing_period, "is_stocked": p.is_stocked, "is_active": p.is_active}
    if stock is not None:
        out["stock_available"] = stock
    return out


def warehouse_out(w: Warehouse) -> dict:
    return {"id": w.id, "code": w.code, "name": w.name, "city": w.city, "region": w.region,
            "base_shipping_fee": f(w.base_shipping_fee), "per_unit_shipping": f(w.per_unit_shipping),
            "lead_days": w.lead_days}


def inventory_out(i: Inventory) -> dict:
    return {"id": i.id, "warehouse_id": i.warehouse_id, "warehouse": i.warehouse.code, "product_id": i.product_id,
            "sku": i.product.sku, "product": i.product.name, "category": i.product.category,
            "quantity": i.quantity, "reserved": i.reserved, "available": i.available,
            "reorder_level": i.reorder_level, "low": i.available <= i.reorder_level}


def event_out(e: QuotationEvent) -> dict:
    return {"id": e.id, "action": e.action, "actor_name": e.actor_name, "comment": e.comment,
            "created_at": iso(e.created_at)}


def message_out(m: NegotiationMessage) -> dict:
    return {"id": m.id, "author_name": m.author_name, "side": m.side, "message": m.message,
            "proposed_discount": f(m.proposed_discount) if m.proposed_discount is not None else None,
            "offer_status": m.offer_status, "created_at": iso(m.created_at)}


def quotation_summary(q: Quotation) -> dict:
    today = utcnow().date()
    return {"id": q.id, "number": q.number, "title": q.title, "status": q.status, "version": q.version,
            "customer_id": q.customer_id, "customer_name": q.customer.name if q.customer else None,
            "rep_id": q.rep_id, "rep_name": q.rep.name if q.rep else None,
            "subtotal": f(q.subtotal), "discount_total": f(q.discount_total), "tax_total": f(q.tax_total),
            "total": f(q.total), "margin_percent": f(q.margin_percent), "risk_score": f(q.risk_score),
            "risk_level": q.risk_level, "approved_level": q.approved_level, "valid_until": iso(q.valid_until),
            "days_to_expiry": (q.valid_until - today).days if q.valid_until else None,
            "payment_terms_days": q.payment_terms_days, "line_count": len(q.lines),
            "has_open_counter": any(m.offer_status == "open" for m in q.messages),
            "created_at": iso(q.created_at), "updated_at": iso(q.updated_at), "sent_at": iso(q.sent_at),
            "closed_at": iso(q.closed_at), "lost_reason": q.lost_reason}


def pricing_out(pricing: dict) -> dict:
    keys = ("subtotal", "discount_total", "net_total", "tax_total", "total", "cost_total", "margin_percent",
            "one_time_total", "recurring_total", "mrr")
    out = {k: f(pricing[k]) for k in keys}
    out["lines"] = [{
        "id": l.get("id"), "product_id": l["product_id"], "name": l.get("name"), "sku": l.get("sku"),
        "category": l.get("category"), "description": l.get("description"), "quantity": int(l["quantity"]),
        "unit_price": f(l["unit_price"]), "unit_cost": f(l.get("unit_cost")),
        "discount_percent": f(l.get("discount_percent")), "tax_rate": f(l.get("tax_rate")),
        "is_subscription": bool(l.get("is_subscription")), "billing_period": l.get("billing_period"),
        "gross": f(l["gross"]), "discount_amount": f(l["discount_amount"]), "line_total": f(l["line_total"]),
        "tax_amount": f(l["tax_amount"]), "margin_percent": f(l["margin_percent"]),
    } for l in pricing["lines"]]
    return out


def risk_out(risk: dict) -> dict:
    return {"score": f(risk["score"]), "level": risk["level"], "required_level": risk["required_level"],
            "drivers": risk["drivers"]}


def quotation_detail(q: Quotation, risk: dict, include_internal: bool = True) -> dict:
    out = quotation_summary(q)
    pricing = pricing_out(price_lines(line_dicts(q)))
    out.update({"notes": q.notes, "parent_id": q.parent_id, "pricing": pricing, "lines": pricing["lines"],
                "messages": [message_out(m) for m in q.messages],
                "customer": customer_out(q.customer) if q.customer else None})
    if include_internal:
        out.update({"risk": risk_out(risk), "events": [event_out(e) for e in q.events],
                    "portal_token": q.portal_token})
    else:  # customer-facing: never leak cost, margin or risk
        for key in ("margin_percent", "risk_score", "risk_level", "approved_level"):
            out.pop(key, None)
        for key in ("cost_total", "margin_percent"):
            pricing.pop(key, None)
        for line in pricing["lines"]:
            line.pop("unit_cost", None)
            line.pop("margin_percent", None)
        out["customer"] = {k: out["customer"][k] for k in ("name", "contact_name", "city", "gstin")}
    return out


def order_out(o: FulfillmentOrder) -> dict:
    return {"id": o.id, "number": o.number, "status": o.status, "quotation_id": o.quotation_id,
            "quotation_number": o.quotation.number if o.quotation else None,
            "customer_name": o.quotation.customer.name if o.quotation and o.quotation.customer else None,
            "warehouse_id": o.warehouse_id, "warehouse": o.warehouse.name if o.warehouse else None,
            "warehouse_code": o.warehouse.code if o.warehouse else None,
            "shipping_cost": f(o.shipping_cost), "eta": iso(o.eta), "created_at": iso(o.created_at),
            "shipped_at": iso(o.shipped_at), "delivered_at": iso(o.delivered_at),
            "units": sum(l.quantity for l in o.lines),
            "lines": [{"product_id": l.product_id, "sku": l.product.sku, "product": l.product.name,
                       "quantity": l.quantity} for l in o.lines]}


def invoice_out(inv: Invoice, today: date | None = None, detail: bool = False) -> dict:
    today = today or utcnow().date()
    overdue = billing.is_overdue(inv, today)
    out = {"id": inv.id, "number": inv.number, "kind": inv.kind, "status": "overdue" if overdue else inv.status,
           "customer_id": inv.customer_id, "customer_name": inv.customer.name if inv.customer else None,
           "quotation_id": inv.quotation_id, "quotation_number": inv.quotation.number if inv.quotation else None,
           "subscription_id": inv.subscription_id, "issue_date": iso(inv.issue_date), "due_date": iso(inv.due_date),
           "period_start": iso(inv.period_start), "period_end": iso(inv.period_end),
           "subtotal": f(inv.subtotal), "tax_total": f(inv.tax_total), "total": f(inv.total),
           "amount_paid": f(inv.amount_paid), "balance": f(inv.total) - f(inv.amount_paid) if inv.status != "void" else 0.0,
           "days_overdue": (today - inv.due_date).days if overdue else 0}
    out["balance"] = round(out["balance"], 2)
    if detail:
        out["lines"] = [{"description": l.description, "quantity": l.quantity, "unit_price": f(l.unit_price),
                         "tax_rate": f(l.tax_rate), "amount": f(l.amount)} for l in inv.lines]
        out["payments"] = [{"id": p.id, "amount": f(p.amount), "method": p.method, "reference": p.reference,
                            "paid_at": iso(p.paid_at)} for p in inv.payments]
    return out


def subscription_out(s: Subscription) -> dict:
    return {"id": s.id, "status": s.status, "customer_id": s.customer_id, "customer_name": s.customer.name,
            "product_id": s.product_id, "product": s.product.name, "sku": s.product.sku, "quantity": s.quantity,
            "unit_price": f(s.unit_price), "billing_period": s.billing_period,
            "period_amount": f(s.unit_price) * s.quantity, "mrr": f(billing.subscription_mrr(s)),
            "start_date": iso(s.start_date), "next_billing_date": iso(s.next_billing_date),
            "quotation_id": s.quotation_id, "quotation_number": s.quotation.number if s.quotation else None,
            "cancelled_at": iso(s.cancelled_at)}
