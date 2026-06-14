"""Master data: customers, products, warehouses & stock, discount policy, settings, audit trail."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (AppSetting, AuditLog, Customer, DiscountTier, Inventory, Invoice, Product, QStatus, Quotation,
                      Role, User, Warehouse)
from ..schemas import CustomerIn, DiscountTierIn, ProductIn, SettingsIn, StockAdjustIn
from ..security import admin_user, internal_user, manager_user, sales_user
from ..serializers import (customer_out, f, inventory_out, invoice_out, iso, product_out, quotation_summary,
                           warehouse_out)
from ..services.pricing import NUMERIC_SETTINGS, load_settings
from ..services.workflow import audit

router = APIRouter()


# ----------------------------------------------------------------------------- customers
@router.get("/customers", tags=["customers"])
def list_customers(q: str = "", user: User = Depends(internal_user), db: Session = Depends(get_db)):
    query = db.query(Customer)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Customer.name).like(like), func.lower(Customer.city).like(like),
                                 func.lower(Customer.industry).like(like)))
    customers = query.order_by(Customer.name).all()
    won = dict(db.query(Quotation.customer_id, func.sum(Quotation.total))
               .filter(Quotation.status == QStatus.ACCEPTED).group_by(Quotation.customer_id).all())
    open_ = dict(db.query(Quotation.customer_id, func.count(Quotation.id))
                 .filter(Quotation.status.in_(QStatus.OPEN)).group_by(Quotation.customer_id).all())
    return [{**customer_out(c), "won_value": f(won.get(c.id)), "open_quotes": open_.get(c.id, 0)} for c in customers]


@router.post("/customers", status_code=201, tags=["customers"])
def create_customer(body: CustomerIn, user: User = Depends(sales_user), db: Session = Depends(get_db)):
    customer = Customer(**body.model_dump(), owner_id=user.id)
    db.add(customer)
    db.flush()
    audit(db, user, "customer.create", "customer", customer.id, customer.name)
    db.commit()
    return customer_out(customer)


@router.get("/customers/{customer_id}", tags=["customers"])
def get_customer(customer_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    quotes = db.query(Quotation).filter_by(customer_id=customer_id).order_by(Quotation.id.desc()).all()
    if user.role == Role.REP:
        quotes = [q for q in quotes if q.rep_id == user.id]
    invoices = db.query(Invoice).filter_by(customer_id=customer_id).order_by(Invoice.id.desc()).all()
    outstanding = sum(invoice_out(i)["balance"] for i in invoices)
    return {**customer_out(customer), "quotations": [quotation_summary(q) for q in quotes],
            "invoices": [invoice_out(i) for i in invoices], "outstanding": round(outstanding, 2),
            "credit_used_percent": round(outstanding / f(customer.credit_limit) * 100, 1)
            if f(customer.credit_limit) else 0}


@router.patch("/customers/{customer_id}", tags=["customers"])
def update_customer(customer_id: int, body: CustomerIn, user: User = Depends(sales_user),
                    db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    data = body.model_dump()
    if user.role == Role.REP:  # reps cannot change commercial terms
        for key in ("credit_limit", "tier", "payment_terms_days"):
            data.pop(key)
    for key, value in data.items():
        setattr(customer, key, value)
    audit(db, user, "customer.update", "customer", customer.id, customer.name)
    db.commit()
    return customer_out(customer)


# ----------------------------------------------------------------------------- products
def _stock_map(db: Session) -> dict:
    rows = db.query(Inventory.product_id, func.sum(Inventory.quantity - Inventory.reserved)).group_by(
        Inventory.product_id).all()
    return {pid: int(qty or 0) for pid, qty in rows}


@router.get("/products", tags=["products"])
def list_products(q: str = "", category: str = "", include_inactive: bool = False,
                  user: User = Depends(internal_user), db: Session = Depends(get_db)):
    query = db.query(Product)
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    if category:
        query = query.filter(Product.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Product.name).like(like), func.lower(Product.sku).like(like)))
    stock = _stock_map(db)
    return [product_out(p, stock.get(p.id, 0) if p.is_stocked else None)
            for p in query.order_by(Product.category, Product.name).all()]


def _product_data(body: ProductIn) -> dict:
    data = body.model_dump()
    data["billing_period"] = (data["billing_period"] or "monthly") if data["is_subscription"] else None
    data["is_stocked"] = data["is_stocked"] and not data["is_subscription"]
    return data


@router.post("/products", status_code=201, tags=["products"])
def create_product(body: ProductIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    if db.query(Product).filter(Product.sku == body.sku).first():
        raise HTTPException(409, f"SKU {body.sku} already exists")
    data = _product_data(body)
    product = Product(**data)
    db.add(product)
    db.flush()
    audit(db, user, "product.create", "product", product.id, product.sku)
    db.commit()
    return product_out(product)


@router.patch("/products/{product_id}", tags=["products"])
def update_product(product_id: int, body: ProductIn, user: User = Depends(manager_user),
                   db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    clash = db.query(Product).filter(Product.sku == body.sku, Product.id != product_id).first()
    if clash:
        raise HTTPException(409, f"SKU {body.sku} already exists")
    for key, value in _product_data(body).items():
        setattr(product, key, value)
    audit(db, user, "product.update", "product", product.id, product.sku)
    db.commit()
    return product_out(product)


@router.get("/products/{product_id}/upsells", tags=["products"])
def upsells(product_id: int, user: User = Depends(internal_user), db: Session = Depends(get_db)):
    """Cross-sell ideas: recurring services to attach to hardware (and vice versa), plus
    higher-margin alternatives in the same category - ranked by margin contribution."""
    ref = db.get(Product, product_id)
    if not ref:
        raise HTTPException(404, "Product not found")
    others = db.query(Product).filter(Product.is_active.is_(True), Product.id != ref.id).all()
    scored = []
    for p in others:
        margin = f(p.price) - f(p.cost)
        if p.is_subscription != ref.is_subscription:
            reason = "Attach recurring revenue" if p.is_subscription else "Bundle the hardware"
            score = margin * 1.5
        elif p.category == ref.category and f(p.price) > f(ref.price):
            reason, score = "Premium upgrade", margin
        else:
            continue
        scored.append((score, {**product_out(p), "margin_delta": round(margin, 2), "reason": reason}))
    return [item for _, item in sorted(scored, key=lambda s: -s[0])[:4]]


# ----------------------------------------------------------------------------- inventory
@router.get("/warehouses", tags=["inventory"])
def list_warehouses(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    out = []
    for w in db.query(Warehouse).order_by(Warehouse.id).all():
        out.append({**warehouse_out(w), "sku_count": len(w.inventory),
                    "units_on_hand": sum(i.quantity for i in w.inventory),
                    "units_reserved": sum(i.reserved for i in w.inventory),
                    "low_stock": sum(1 for i in w.inventory if i.available <= i.reorder_level)})
    return out


@router.get("/inventory", tags=["inventory"])
def list_inventory(warehouse_id: int | None = None, low_only: bool = False, user: User = Depends(internal_user),
                   db: Session = Depends(get_db)):
    query = db.query(Inventory).join(Product).filter(Product.is_active.is_(True), Product.is_stocked.is_(True))
    if warehouse_id:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    rows = [inventory_out(i) for i in query.order_by(Product.name, Inventory.warehouse_id).all()]
    return [r for r in rows if r["low"]] if low_only else rows


@router.post("/inventory/adjust", tags=["inventory"])
def adjust_stock(body: StockAdjustIn, user: User = Depends(manager_user), db: Session = Depends(get_db)):
    warehouse, product = db.get(Warehouse, body.warehouse_id), db.get(Product, body.product_id)
    if not warehouse or not product:
        raise HTTPException(404, "Warehouse or product not found")
    if not product.is_stocked:
        raise HTTPException(422, "Services and subscriptions are not stocked")
    inv = db.query(Inventory).filter_by(warehouse_id=warehouse.id, product_id=product.id).first()
    if not inv:
        inv = Inventory(warehouse_id=warehouse.id, product_id=product.id, quantity=0, reserved=0)
        db.add(inv)
    if inv.quantity + body.delta < inv.reserved:
        raise HTTPException(409, f"Cannot go below the {inv.reserved} units already reserved for orders")
    inv.quantity += body.delta
    db.flush()
    audit(db, user, "inventory.adjust", "inventory", inv.id,
          f"{product.sku} @ {warehouse.code}: {body.delta:+d} ({body.reason})")
    db.commit()
    db.refresh(inv)
    return inventory_out(inv)


# ----------------------------------------------------------------------------- governance
@router.get("/discount-tiers", tags=["governance"])
def list_tiers(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name, "category": t.category, "max_discount_percent": f(t.max_discount_percent)}
            for t in db.query(DiscountTier).order_by(DiscountTier.category.is_(None), DiscountTier.category).all()]


@router.post("/discount-tiers", status_code=201, tags=["governance"])
def upsert_tier(body: DiscountTierIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    category = (body.category or "").strip() or None
    tier = db.query(DiscountTier).filter(DiscountTier.category == category if category
                                         else DiscountTier.category.is_(None)).first()
    if not tier:
        tier = DiscountTier(category=category)
        db.add(tier)
    tier.name, tier.max_discount_percent = body.name, body.max_discount_percent
    db.flush()
    audit(db, user, "policy.discount_tier", "discount_tier", tier.id,
          f"{category or 'default'} max {body.max_discount_percent}%")
    db.commit()
    return {"id": tier.id, "name": tier.name, "category": tier.category,
            "max_discount_percent": f(tier.max_discount_percent)}


@router.delete("/discount-tiers/{tier_id}", status_code=204, tags=["governance"])
def delete_tier(tier_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    tier = db.get(DiscountTier, tier_id)
    if not tier:
        raise HTTPException(404, "Tier not found")
    if tier.category is None:
        raise HTTPException(400, "The default tier cannot be deleted")
    audit(db, user, "policy.discount_tier_delete", "discount_tier", tier.id, tier.category)
    db.delete(tier)
    db.commit()


def _settings_out(db: Session) -> dict:
    cfg = load_settings(db)
    return {k: (float(v) if k in NUMERIC_SETTINGS else v) for k, v in cfg.items()}


@router.get("/settings", tags=["governance"])
def get_settings(user: User = Depends(internal_user), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings", tags=["governance"])
def update_settings(body: SettingsIn, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    merged = {**_settings_out(db), **changes}
    if merged["manager_threshold"] >= merged["finance_threshold"]:
        raise HTTPException(422, "The Finance threshold must be higher than the Manager threshold")
    for key, value in changes.items():
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = str(value)
        db.add(row)
    audit(db, user, "policy.settings", "settings", None, ", ".join(f"{k}={v}" for k, v in changes.items()))
    db.commit()
    return _settings_out(db)


@router.get("/audit-logs", tags=["governance"])
def audit_logs(limit: int = Query(100, ge=1, le=500), user: User = Depends(manager_user),
               db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "actor_name": r.actor_name, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "detail": r.detail, "created_at": iso(r.created_at)} for r in rows]
