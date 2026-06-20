"""Multi-warehouse split fulfilment.

Goal: ship the physical lines of a won deal in as few shipments as possible, then as cheaply
as possible. A single warehouse that can cover everything always wins; otherwise we greedily
pick the warehouse covering the most outstanding units (ties broken on shipping cost).
"""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import FulfillmentLine, FulfillmentOrder, Inventory, Quotation, Warehouse, utcnow
from .pricing import D, money

CROSS_REGION_COST_FACTOR = Decimal("1.4")
CROSS_REGION_EXTRA_DAYS = 2
NEXT_STATUS = {"planned": "picking", "picking": "shipped", "shipped": "delivered"}


def physical_demand(quotation: Quotation) -> dict[int, int]:
    """Units to ship per product. Subscriptions and services are delivered, not shipped."""
    demand: dict[int, int] = {}
    for line in quotation.lines:
        if line.product.is_stocked and not line.is_subscription:
            demand[line.product_id] = demand.get(line.product_id, 0) + int(line.quantity)
    return demand


def _shipping(wh: Warehouse, units: int, region: str | None) -> tuple[Decimal, int]:
    cost = D(wh.base_shipping_fee) + D(wh.per_unit_shipping) * units
    days = wh.lead_days
    if region and wh.region != region:
        cost *= CROSS_REGION_COST_FACTOR
        days += CROSS_REGION_EXTRA_DAYS
    return money(cost), days


def plan_split(db: Session, demand: dict[int, int], region: str | None = None) -> dict:
    """Pure planning step - does not touch stock."""
    warehouses = db.query(Warehouse).order_by(Warehouse.id).all()
    stock = {wh.id: {} for wh in warehouses}
    if demand:
        for inv in db.query(Inventory).filter(Inventory.product_id.in_(demand.keys())).all():
            stock[inv.warehouse_id][inv.product_id] = inv.available
    remaining = {pid: qty for pid, qty in demand.items() if qty > 0}
    shipments = []
    candidates = list(warehouses)

    while remaining and candidates:
        best = None
        for wh in candidates:
            take = {pid: min(qty, stock[wh.id].get(pid, 0)) for pid, qty in remaining.items()}
            take = {pid: q for pid, q in take.items() if q > 0}
            units = sum(take.values())
            if not units:
                continue
            cost, days = _shipping(wh, units, region)
            key = (-units, cost, wh.id)  # most units first, then cheapest
            if best is None or key < best[0]:
                best = (key, wh, take, cost, days)
        if best is None:
            break
        _, wh, take, cost, days = best
        shipments.append({"warehouse_id": wh.id, "warehouse": wh.name, "code": wh.code, "city": wh.city,
                          "region": wh.region, "items": take, "units": sum(take.values()),
                          "shipping_cost": cost, "lead_days": days})
        for pid, q in take.items():
            remaining[pid] -= q
            if remaining[pid] <= 0:
                del remaining[pid]
        candidates.remove(wh)

    return {
        "shipments": shipments,
        "backorder": remaining,
        "total_units": sum(demand.values()),
        "shipment_count": len(shipments),
        "total_shipping_cost": sum((s["shipping_cost"] for s in shipments), Decimal(0)),
        "fully_allocated": not remaining,
    }


def _number(order: FulfillmentOrder):
    order.number = f"FO-{order.created_at.year}-{order.id:04d}"


def create_orders(db: Session, quotation: Quotation, now=None) -> list[FulfillmentOrder]:
    """Turn the plan into fulfilment orders and reserve the stock."""
    now = now or utcnow()
    demand = physical_demand(quotation)
    if not demand:
        return []
    plan = plan_split(db, demand, quotation.customer.region if quotation.customer else None)
    orders = []
    for shipment in plan["shipments"]:
        order = FulfillmentOrder(quotation_id=quotation.id, warehouse_id=shipment["warehouse_id"],
                                 status="planned", shipping_cost=shipment["shipping_cost"],
                                 eta=(now + timedelta(days=shipment["lead_days"])).date(), created_at=now)
        for pid, qty in shipment["items"].items():
            order.lines.append(FulfillmentLine(product_id=pid, quantity=qty))
            inv = db.query(Inventory).filter_by(warehouse_id=shipment["warehouse_id"], product_id=pid).one()
            inv.reserved += qty
        orders.append(order)
    if plan["backorder"]:
        order = FulfillmentOrder(quotation_id=quotation.id, warehouse_id=None, status="backorder", created_at=now)
        for pid, qty in plan["backorder"].items():
            order.lines.append(FulfillmentLine(product_id=pid, quantity=qty))
        orders.append(order)
    db.add_all(orders)
    db.flush()
    for order in orders:
        _number(order)
    return orders


def advance(db: Session, order: FulfillmentOrder, now=None) -> FulfillmentOrder:
    """planned -> picking -> shipped -> delivered. Shipping removes the stock for good."""
    now = now or utcnow()
    if order.status not in NEXT_STATUS:
        raise ValueError(f"A {order.status} order cannot be advanced")
    new_status = NEXT_STATUS[order.status]
    if new_status == "shipped":
        for line in order.lines:
            inv = db.query(Inventory).filter_by(warehouse_id=order.warehouse_id, product_id=line.product_id).one()
            inv.quantity = max(0, inv.quantity - line.quantity)
            inv.reserved = max(0, inv.reserved - line.quantity)
        order.shipped_at = now
    if new_status == "delivered":
        order.delivered_at = now
    order.status = new_status
    return order


def allocate_backorder(db: Session, order: FulfillmentOrder, now=None) -> list[FulfillmentOrder]:
    """Retry a backorder after stock arrives. Whatever can ship becomes new planned orders."""
    now = now or utcnow()
    if order.status != "backorder":
        raise ValueError("Only backorders can be re-allocated")
    demand = {l.product_id: l.quantity for l in order.lines}
    region = order.quotation.customer.region if order.quotation and order.quotation.customer else None
    plan = plan_split(db, demand, region)
    created = []
    for shipment in plan["shipments"]:
        new = FulfillmentOrder(quotation_id=order.quotation_id, warehouse_id=shipment["warehouse_id"],
                               status="planned", shipping_cost=shipment["shipping_cost"],
                               eta=(now + timedelta(days=shipment["lead_days"])).date(), created_at=now)
        for pid, qty in shipment["items"].items():
            new.lines.append(FulfillmentLine(product_id=pid, quantity=qty))
            db.query(Inventory).filter_by(warehouse_id=shipment["warehouse_id"], product_id=pid).one().reserved += qty
        created.append(new)
    db.add_all(created)
    if plan["backorder"]:
        for line in list(order.lines):
            left = plan["backorder"].get(line.product_id, 0)
            if left:
                line.quantity = left
            else:
                order.lines.remove(line)
    else:
        db.delete(order)
    db.flush()
    for new in created:
        _number(new)
    return created
