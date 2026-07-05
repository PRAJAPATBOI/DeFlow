"""Unit tests for the pure business engines: pricing, risk, proration, split fulfilment."""
from datetime import date
from decimal import Decimal

from app.models import Customer, Inventory, Product, Warehouse
from app.services import billing, fulfillment
from app.services.pricing import assess_risk, price_lines


def line(price, qty=1, disc=0, cost=0, tax=18, sub=False, period=None, category="Servers"):
    return {"product_id": 1, "quantity": qty, "unit_price": price, "unit_cost": cost, "discount_percent": disc,
            "tax_rate": tax, "is_subscription": sub, "billing_period": period, "category": category}


def test_pricing_totals_discount_tax_and_margin():
    p = price_lines([line(1000, qty=3, disc=10, cost=600), line(499.99, qty=1, tax=5, cost=100)])
    assert p["subtotal"] == Decimal("3499.99")
    assert p["discount_total"] == Decimal("300.00")
    assert p["net_total"] == Decimal("3199.99")
    assert p["tax_total"] == Decimal("486.00") + Decimal("25.00")  # 18% of 2700 + 5% of 499.99 (half-up)
    assert p["total"] == p["net_total"] + p["tax_total"]
    assert p["margin_percent"] == Decimal("40.62")                  # (3199.99 - 1900) / 3199.99


def test_pricing_splits_one_time_and_recurring_and_normalises_mrr():
    p = price_lines([line(1000), line(300, sub=True, period="monthly"), line(1200, sub=True, period="annual"),
                     line(900, sub=True, period="quarterly")])
    assert p["one_time_total"] == Decimal("1000.00")
    assert p["recurring_total"] == Decimal("2400.00")
    assert p["mrr"] == Decimal("700.00")  # 300 + 1200/12 + 900/3


def test_empty_quote_prices_to_zero():
    p = price_lines([])
    assert p["total"] == 0 and p["margin_percent"] == 0


def test_risk_low_when_within_policy(db):
    pricing = price_lines([line(100000, qty=2, disc=5, cost=60000)])
    risk = assess_risk(db, pricing, db.get(Customer, 1), 30)
    assert risk["level"] == "low" and risk["required_level"] == 0 and risk["drivers"] == []


def test_risk_scales_with_discount_over_policy_and_thin_margin(db):
    # Servers tier is 12%. 22% off -> 10 points over -> 40 pts (cap). Cost is 80% of list -> margin collapses.
    pricing = price_lines([line(100000, qty=2, disc=22, cost=80000)])
    risk = assess_risk(db, pricing, db.get(Customer, 1), 30)
    factors = {d["factor"]: d["points"] for d in risk["drivers"]}
    assert factors["discount"] == 40.0
    assert factors["margin"] == 30.0
    assert risk["level"] == "high" and risk["required_level"] == 2


def test_risk_medium_band_requires_manager_only(db):
    pricing = price_lines([line(100000, qty=1, disc=19, cost=50000)])  # 7 over policy -> 28 pts
    risk = assess_risk(db, pricing, db.get(Customer, 1), 30)
    assert risk["score"] == Decimal("28.00") and risk["level"] == "medium" and risk["required_level"] == 1


def test_risk_counts_credit_exposure_and_long_payment_terms(db):
    customer = db.get(Customer, 1)
    customer.credit_limit = 100000
    pricing = price_lines([line(100000, qty=2, cost=50000, tax=0)])  # 200% of limit -> 25 pts (cap)
    risk = assess_risk(db, pricing, customer, 90)                    # net-90 -> 15 pts
    assert {d["factor"]: d["points"] for d in risk["drivers"]} == {"credit": 25.0, "terms": 15.0}
    assert risk["level"] == "medium"


def test_exceeding_the_credit_limit_always_needs_a_manager(db):
    customer = db.get(Customer, 1)
    customer.credit_limit = 100000
    at_limit = price_lines([line(100000, qty=1, cost=50000, tax=0)])      # exactly 100% -> 25 pts
    assert assess_risk(db, at_limit, customer, 30)["required_level"] == 1
    half = price_lines([line(50000, qty=1, cost=25000, tax=0)])           # 50% -> no credit risk
    assert assess_risk(db, half, customer, 30)["level"] == "low"


def test_risk_score_is_capped_at_100(db):
    customer = db.get(Customer, 1)
    customer.credit_limit = 1000
    pricing = price_lines([line(100000, qty=5, disc=60, cost=90000)])
    assert assess_risk(db, pricing, customer, 180)["score"] == Decimal("100.00")


def test_proration_mid_month_charges_remaining_days_only():
    first = billing.proration(date(2026, 11, 16), Decimal("3000"), "monthly")
    assert first["prorated"] and first["days"] == 15
    assert first["amount"] == Decimal("1500.00")
    assert first["period_end"] == date(2026, 11, 30)
    assert first["next_billing_date"] == date(2026, 12, 1)


def test_proration_first_of_month_is_a_full_period():
    first = billing.proration(date(2026, 3, 1), Decimal("9000"), "quarterly")
    assert not first["prorated"] and first["amount"] == Decimal("9000.00")
    assert first["period_end"] == date(2026, 5, 31) and first["next_billing_date"] == date(2026, 6, 1)


def test_proration_annual_plan_uses_monthly_equivalent_and_crosses_year_end():
    first = billing.proration(date(2026, 12, 17), Decimal("12000"), "annual")
    assert first["amount"] == Decimal("483.87")  # 1000 per month x 15/31
    assert first["next_billing_date"] == date(2027, 1, 1)


def test_add_months_clamps_to_month_end():
    assert billing.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert billing.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def _stock(db, sku, per_warehouse):
    product = db.query(Product).filter_by(sku=sku).one()
    for code, qty in per_warehouse.items():
        wh = db.query(Warehouse).filter_by(code=code).one()
        db.query(Inventory).filter_by(warehouse_id=wh.id, product_id=product.id).one().quantity = qty
    db.flush()
    return product.id


def test_split_prefers_a_single_warehouse_when_one_can_cover_everything(db):
    a = _stock(db, "SRV-R750", {"BOM": 2, "DEL": 5, "BLR": 9, "CCU": 0})
    b = _stock(db, "NET-SW48", {"BOM": 9, "DEL": 4, "BLR": 6, "CCU": 0})
    plan = fulfillment.plan_split(db, {a: 5, b: 4}, "North")
    assert plan["shipment_count"] == 1 and plan["fully_allocated"]
    assert plan["shipments"][0]["code"] == "DEL"   # same region as the customer, so cheaper than BLR


def test_split_uses_fewest_warehouses_and_reports_backorder(db):
    a = _stock(db, "SRV-R750", {"BOM": 6, "DEL": 3, "BLR": 1, "CCU": 0})
    plan = fulfillment.plan_split(db, {a: 12}, "West")
    assert [s["code"] for s in plan["shipments"]] == ["BOM", "DEL", "BLR"]
    assert [s["units"] for s in plan["shipments"]] == [6, 3, 1]
    assert plan["backorder"] == {a: 2} and not plan["fully_allocated"]


def test_split_ignores_stock_that_is_already_reserved(db):
    a = _stock(db, "SRV-R750", {"BOM": 6, "DEL": 0, "BLR": 0, "CCU": 0})
    bom = db.query(Warehouse).filter_by(code="BOM").one()
    db.query(Inventory).filter_by(warehouse_id=bom.id, product_id=a).one().reserved = 4
    db.flush()
    plan = fulfillment.plan_split(db, {a: 5}, "West")
    assert plan["shipments"][0]["units"] == 2 and plan["backorder"] == {a: 3}


def test_cross_region_shipping_costs_more_and_takes_longer(db):
    a = _stock(db, "SRV-R750", {"BOM": 5, "DEL": 0, "BLR": 0, "CCU": 0})
    local = fulfillment.plan_split(db, {a: 2}, "West")["shipments"][0]
    remote = fulfillment.plan_split(db, {a: 2}, "East")["shipments"][0]
    assert local["shipping_cost"] == Decimal("2860.00")    # 2500 + 2 x 180
    assert remote["shipping_cost"] == Decimal("4004.00")   # x 1.4 cross-region
    assert remote["lead_days"] == local["lead_days"] + 2
