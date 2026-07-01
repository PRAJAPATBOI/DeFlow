"""Demo data.

Rather than inserting rows directly, the seeder drives ~40 deals through the *real* workflow
(submit -> approve -> send -> negotiate -> accept -> ship -> invoice -> pay) with back-dated
timestamps, so every dashboard number is internally consistent.

Run standalone to reset the database:  python -m app.seed --reset
"""
import random
import sys
from datetime import timedelta

from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, reset_database
from .models import (Customer, DiscountTier, FulfillmentOrder, Inventory, Invoice, Product, QStatus, Quotation,
                     QuotationLine, Role, User, Warehouse, utcnow)
from .security import hash_password
from .services import billing, fulfillment, workflow
from .services.pricing import D, reprice

DEMO_PASSWORD = "Demo@1234"

USERS = [
    ("Ramesh Prajapat", "admin@dealflow360.in", Role.ADMIN),
    ("Priya Sharma", "manager@dealflow360.in", Role.MANAGER),
    ("Arjun Mehta", "arjun@dealflow360.in", Role.REP),
    ("Sneha Iyer", "sneha@dealflow360.in", Role.REP),
    ("Vikram Nair", "finance@dealflow360.in", Role.FINANCE),
]

# name, industry, contact, city, region, tier, credit limit, terms
CUSTOMERS = [
    ("Aravalli Steel Works", "Manufacturing", "Rohit Bansal", "Jaipur", "North", "gold", 4000000, 45),
    ("Konkan Logistics", "Logistics", "Meera Desai", "Mumbai", "West", "silver", 2500000, 30),
    ("Nilgiri Health Systems", "Healthcare", "Dr. Anand Rao", "Coimbatore", "South", "platinum", 6000000, 30),
    ("Sundarban Foods", "FMCG", "Ishita Ghosh", "Kolkata", "East", "standard", 1200000, 30),
    ("Deccan Fintech Labs", "Financial Services", "Karthik Reddy", "Hyderabad", "South", "gold", 5000000, 30),
    ("Sabarmati Textiles", "Textiles", "Hetal Shah", "Ahmedabad", "West", "silver", 2000000, 60),
    ("Himadri EduTech", "Education", "Nitin Rawat", "Dehradun", "North", "standard", 900000, 30),
    ("Malabar Retail Group", "Retail", "Fathima Koya", "Kochi", "South", "gold", 3500000, 45),
    ("Vindhya Power Infra", "Energy", "Sanjay Tiwari", "Bhopal", "North", "silver", 3000000, 60),
    ("Brahmaputra Media", "Media", "Rupam Baruah", "Guwahati", "East", "standard", 800000, 30),
]

# sku, name, category, price, cost, unit, subscription period
PRODUCTS = [
    ("SRV-R750", "Rack Server R750 (2x Xeon, 256GB)", "Servers", 685000, 520000, "each", None),
    ("SRV-T350", "Tower Server T350", "Servers", 245000, 186000, "each", None),
    ("SRV-GPU4", "GPU Compute Node (4x A-series)", "Servers", 1850000, 1480000, "each", None),
    ("NET-SW48", "48-Port PoE+ Managed Switch", "Networking", 142000, 96000, "each", None),
    ("NET-FW90", "Next-Gen Firewall FW-90", "Networking", 218000, 145000, "each", None),
    ("NET-AP6", "Wi-Fi 6 Access Point", "Networking", 28500, 17800, "each", None),
    ("STO-NAS8", "8-Bay NAS Appliance (96TB)", "Storage", 395000, 290000, "each", None),
    ("STO-SAN2", "All-Flash SAN Array (40TB)", "Storage", 1240000, 955000, "each", None),
    ("EUC-LT14", "Business Laptop 14\" (i7, 16GB)", "End-User Computing", 92000, 76500, "each", None),
    ("EUC-MON27", "27\" QHD Monitor", "End-User Computing", 24500, 18900, "each", None),
    ("EUC-DOCK", "USB-C Docking Station", "End-User Computing", 11800, 7900, "each", None),
    ("PWR-UPS10", "10kVA Online UPS", "Power", 168000, 124000, "each", None),
    ("SW-VIRT", "Virtualisation Suite (per socket)", "Software", 135000, 81000, "licence", None),
    ("SW-BKP", "Backup & Recovery Licence (perpetual)", "Software", 78000, 39000, "licence", None),
    ("SVC-INST", "On-site Installation & Commissioning", "Services", 45000, 27000, "job", None),
    ("SVC-MIG", "Data Migration Service", "Services", 120000, 68000, "job", None),
    ("SUB-SOC", "Managed SOC Monitoring", "Subscriptions", 85000, 46000, "month", "monthly"),
    ("SUB-CLD", "Cloud Backup 10TB", "Subscriptions", 18500, 8200, "month", "monthly"),
    ("SUB-AMC", "Hardware AMC - Next Business Day", "Subscriptions", 96000, 52000, "quarter", "quarterly"),
    ("SUB-M365", "Productivity Suite (per user)", "Subscriptions", 9800, 8100, "year", "annual"),
    ("SUB-NOC", "24x7 Network Operations Centre", "Subscriptions", 62000, 35000, "month", "monthly"),
    ("SUB-EDR", "Endpoint Detection & Response (per 50 seats)", "Subscriptions", 27500, 14500, "month", "monthly"),
]

WAREHOUSES = [  # code, name, city, region, base fee, per unit, lead days
    ("BOM", "Bhiwandi Distribution Centre", "Mumbai", "West", 2500, 180, 2),
    ("DEL", "Gurugram Fulfilment Hub", "Delhi NCR", "North", 2800, 200, 3),
    ("BLR", "Hoskote Logistics Park", "Bengaluru", "South", 2400, 170, 2),
    ("CCU", "Dankuni Warehouse", "Kolkata", "East", 3200, 240, 4),
]

TIERS = [("Standard policy", None, 10), ("Servers", "Servers", 12), ("Networking", "Networking", 15),
         ("Storage", "Storage", 12), ("End-User Computing", "End-User Computing", 8), ("Software", "Software", 20),
         ("Subscriptions", "Subscriptions", 15), ("Services", "Services", 10), ("Power", "Power", 10)]

BUNDLES = [  # title, [(sku, qty)]
    ("Data centre refresh", [("SRV-R750", 4), ("STO-SAN2", 1), ("SW-VIRT", 8), ("SVC-INST", 1), ("SUB-AMC", 1)]),
    ("Branch network rollout", [("NET-SW48", 6), ("NET-AP6", 24), ("NET-FW90", 2), ("SUB-NOC", 1)]),
    ("Security operations package", [("NET-FW90", 2), ("SUB-SOC", 1), ("SUB-EDR", 4)]),
    ("Workforce laptop refresh", [("EUC-LT14", 40), ("EUC-MON27", 40), ("EUC-DOCK", 40), ("SUB-M365", 40)]),
    ("Backup modernisation", [("STO-NAS8", 2), ("SW-BKP", 2), ("SUB-CLD", 3), ("SVC-MIG", 1)]),
    ("AI compute pilot", [("SRV-GPU4", 1), ("PWR-UPS10", 1), ("SVC-INST", 1)]),
    ("Remote office kit", [("SRV-T350", 1), ("NET-SW48", 1), ("NET-AP6", 4), ("PWR-UPS10", 1)]),
    ("Storage expansion", [("STO-NAS8", 3), ("SVC-MIG", 1), ("SUB-AMC", 1)]),
    ("Campus Wi-Fi upgrade", [("NET-AP6", 60), ("NET-SW48", 4), ("SVC-INST", 2)]),
    ("Managed security renewal", [("SUB-SOC", 1), ("SUB-EDR", 6), ("SUB-CLD", 2)]),
]


def _seed_master(db: Session) -> dict:
    users = {}
    hashed = hash_password(DEMO_PASSWORD)
    start = utcnow() - timedelta(days=200)
    for name, email, role in USERS:
        users[email.split("@")[0]] = User(name=name, email=email, role=role, hashed_password=hashed, created_at=start)
    db.add_all(users.values())
    db.flush()

    reps = [users["arjun"], users["sneha"]]
    customers = []
    for i, (name, industry, contact, city, region, tier, limit, terms) in enumerate(CUSTOMERS):
        slug = name.split()[0].lower()
        customers.append(Customer(name=name, industry=industry, contact_name=contact, city=city, region=region,
                                  tier=tier, credit_limit=limit, payment_terms_days=terms,
                                  email=f"procurement@{slug}.example", phone=f"+91 98{i:02d}0 1{i:02d}45",
                                  gstin=f"{8 + i:02d}AAECD{1000 + i * 37}K1Z{i}", owner_id=reps[i % 2].id,
                                  created_at=start + timedelta(days=i * 3)))
    db.add_all(customers)
    db.flush()
    db.add(User(name="Rohit Bansal", email="customer@aravalli.example", role=Role.CUSTOMER, hashed_password=hashed,
                customer_id=customers[0].id, created_at=start))

    products = {}
    for sku, name, category, price, cost, unit, period in PRODUCTS:
        products[sku] = Product(sku=sku, name=name, category=category, price=price, cost=cost, unit=unit,
                                is_subscription=period is not None, billing_period=period, tax_rate=18,
                                is_stocked=period is None and category != "Services",
                                description=f"{name} - enterprise grade, GST invoice, pan-India support.",
                                created_at=start)
    db.add_all(products.values())
    warehouses = [Warehouse(code=c, name=n, city=city, region=r, base_shipping_fee=b, per_unit_shipping=p,
                            lead_days=d) for c, n, city, r, b, p, d in WAREHOUSES]
    db.add_all(warehouses)
    db.add_all(DiscountTier(name=n, category=c, max_discount_percent=m) for n, c, m in TIERS)
    db.flush()

    rng = random.Random(7)
    for product in products.values():
        if not product.is_stocked:
            continue
        bulk = D(product.price) < 100000
        for wh in warehouses:
            qty = rng.randint(80, 180) if bulk else rng.randint(8, 20)
            if rng.random() < 0.08:
                qty = rng.randint(0, 3)  # a few genuinely low-stock positions
            db.add(Inventory(warehouse_id=wh.id, product_id=product.id, quantity=qty,
                             reorder_level=20 if bulk else 3))
    db.flush()
    return {"users": users, "customers": customers, "products": products}


def _make_quote(db, rep, customer, title, items, created, products, terms=None, notes=None) -> Quotation:
    q = Quotation(title=title, customer_id=customer.id, rep_id=rep.id, status=QStatus.DRAFT,
                  valid_until=(created + timedelta(days=30)).date(),
                  payment_terms_days=terms or customer.payment_terms_days, notes=notes,
                  created_at=created, updated_at=created)
    for sku, qty, disc in items:
        p = products[sku]
        q.lines.append(QuotationLine(product_id=p.id, quantity=qty, unit_price=p.price, unit_cost=p.cost,
                                     discount_percent=disc, tax_rate=p.tax_rate, is_subscription=p.is_subscription,
                                     billing_period=p.billing_period))
    db.add(q)
    db.flush()
    q.number = f"Q-{created.year}-{q.id:04d}"
    db.flush()
    db.refresh(q)
    reprice(db, q)
    workflow.add_event(db, q, rep, "created", None, created)
    return q


def _approve_all(db, q, users, t):
    while q.status in (QStatus.PENDING_MANAGER, QStatus.PENDING_FINANCE):
        t += timedelta(hours=6)
        approver = users["manager"] if q.status == QStatus.PENDING_MANAGER else users["finance"]
        workflow.decide(db, q, approver, "approve", "Strategic account - approved", t)
    return t


def _progress(db, q, target, users, rng, t):
    """Drive a draft quotation to the requested end state, advancing the clock as we go."""
    rep = q.rep
    if target == "draft":
        return t
    t += timedelta(hours=rng.randint(2, 30))
    workflow.submit(db, q, rep, t)
    if target == "pending":
        return t
    if target == "pending_finance":
        if q.status == QStatus.PENDING_MANAGER:
            t += timedelta(hours=5)
            workflow.decide(db, q, users["manager"], "approve", "OK from sales; needs Finance sign-off", t)
        return t
    if target == "rejected" and q.status != QStatus.APPROVED:
        t += timedelta(hours=8)
        workflow.decide(db, q, users["manager"], "reject", "Margin too thin for this account. Rework pricing.", t)
        return t
    t = _approve_all(db, q, users, t)
    if target == "approved":
        return t
    t += timedelta(hours=rng.randint(1, 20))
    workflow.send(db, q, rep, t)
    if target == "sent":
        return t
    contact = q.customer.contact_name
    if target in ("negotiating", "won_negotiated"):
        t += timedelta(days=rng.randint(1, 3))
        ask = float(max(D(l.discount_percent) for l in q.lines)) + rng.choice([3, 4, 5])
        msg = workflow.post_message(db, q, None, contact, "customer",
                                    f"Thanks for the proposal. We can sign this week at {ask:g}% off.", ask, t)
        db.flush()
        if target == "negotiating":
            return t
        t += timedelta(hours=10)
        workflow.respond_counter(db, q, msg, rep, True, None, t)
        t = _approve_all(db, q, users, t)
        if q.status == QStatus.APPROVED:
            t += timedelta(hours=2)
            workflow.send(db, q, rep, t)
    t += timedelta(days=rng.randint(3, 16))
    if target == "declined":
        workflow.decline(db, q, contact, rng.choice(["Budget frozen this quarter", "Went with an incumbent vendor",
                                                     "Pricing higher than competing bid"]), None, t)
    elif target == "lost":
        workflow.mark_lost(db, q, rep, rng.choice(["Customer went silent", "Project cancelled"]), t)
    else:
        workflow.accept(db, q, contact, None, t)
    return t


def _settle(db, q, users, rng, t, today):
    """Ship orders and collect payments for a won deal, depending on how old it is."""
    age = (today - t).days
    for order in db.query(FulfillmentOrder).filter_by(quotation_id=q.id).all():
        steps = 3 if age > 10 else 2 if age > 5 else 1 if age > 2 else 0
        when = t
        for _ in range(steps):
            if order.status in fulfillment.NEXT_STATUS:
                when += timedelta(days=1, hours=rng.randint(1, 8))
                fulfillment.advance(db, order, when)


def _collect(db, users, rng, today):
    for inv in db.query(Invoice).order_by(Invoice.id).all():
        age = (today.date() - inv.issue_date).days
        roll = rng.random()
        if age < 6 or roll < 0.05:
            continue  # recent, or a late payer -> may show up as overdue
        paid_on = min(today, utcnow().replace(year=inv.issue_date.year, month=inv.issue_date.month,
                                              day=inv.issue_date.day) + timedelta(days=rng.randint(4, 28)))
        amount = D(inv.total) if roll > 0.13 else (D(inv.total) / 2)
        billing.record_payment(db, inv, amount, rng.choice(["bank_transfer", "bank_transfer", "upi", "cheque"]),
                               f"UTR{rng.randint(10**9, 10**10 - 1)}", users["finance"].id, paid_on)


def seed(db: Session) -> None:
    master = _seed_master(db)
    users, customers, products = master["users"], master["customers"], master["products"]
    reps = [users["arjun"], users["sneha"]]
    rng = random.Random(360)
    today = utcnow()

    # Historic deals: (days ago, outcome).
    history = [(150, "won"), (144, "won"), (138, "declined"), (131, "won_negotiated"), (126, "won"), (119, "lost"),
               (113, "won"), (108, "rejected"), (101, "won"), (96, "won_negotiated"), (90, "won"), (84, "declined"),
               (79, "won"), (72, "won"), (66, "lost"), (60, "won_negotiated"), (55, "won"), (49, "won"),
               (44, "declined"), (40, "won"), (36, "rejected"), (31, "won"), (27, "won_negotiated"), (22, "won"),
               (18, "won"), (14, "won"), (11, "lost"), (9, "won")]
    for i, (days_ago, outcome) in enumerate(history):
        title, bundle = BUNDLES[i % len(BUNDLES)]
        customer = customers[(i * 3 + 1) % len(customers)]
        scale = rng.choice([0.5, 1, 1, 1, 2])
        heavy = outcome == "rejected" or rng.random() < 0.3
        items = [(sku, max(1, round(qty * scale)), rng.choice([14, 18, 22]) if heavy else rng.choice([0, 3, 5, 8]))
                 for sku, qty in bundle]
        created = today - timedelta(days=days_ago, hours=rng.randint(0, 9))
        q = _make_quote(db, reps[i % 2], customer, f"{title} - {customer.name.split()[0]}", items, created, products)
        t = _progress(db, q, outcome, users, rng, created)
        if q.status == QStatus.ACCEPTED:
            _settle(db, q, users, rng, t, today)
        q.updated_at = t
        db.flush()

    # Live pipeline: one of everything so each screen has something to act on.
    aravalli = customers[0]
    live = [
        (aravalli, reps[0], "Plant-floor network & SOC", [("NET-SW48", 8, 10), ("NET-FW90", 2, 12), ("SUB-SOC", 1, 10)],
         6, "negotiating"),
        (aravalli, reps[0], "Design office laptop refresh", [("EUC-LT14", 25, 5), ("EUC-MON27", 25, 5),
                                                             ("SUB-M365", 25, 0)], 3, "sent"),
        (customers[2], reps[1], "Hospital PACS storage", [("STO-SAN2", 2, 20), ("SRV-R750", 2, 18), ("SUB-AMC", 2, 10)],
         2, "pending"),
        (customers[4], reps[0], "Trading floor GPU cluster", [("SRV-GPU4", 3, 24), ("PWR-UPS10", 2, 20),
                                                              ("SVC-INST", 1, 15)], 4, "pending_finance"),
        (customers[1], reps[1], "Warehouse Wi-Fi coverage", [("NET-AP6", 36, 8), ("NET-SW48", 3, 8)], 2, "approved"),
        (customers[7], reps[1], "Store backup roll-out", [("STO-NAS8", 2, 6), ("SUB-CLD", 6, 5)], 12, "sent"),
        (customers[5], reps[0], "ERP server upgrade", [("SRV-R750", 2, 8), ("SW-VIRT", 4, 10)], 1, "draft"),
        (customers[8], reps[1], "Substation edge compute", [("SRV-T350", 6, 13), ("PWR-UPS10", 6, 9)], 9, "pending"),
        (customers[3], reps[0], "Head-office security stack", [("NET-FW90", 1, 5), ("SUB-EDR", 2, 5)], 0, "draft"),
        (customers[6], reps[1], "Campus lab refresh", [("EUC-LT14", 30, 16), ("NET-AP6", 12, 10)], 5, "negotiating"),
    ]
    for customer, rep, title, items, days_ago, target in live:
        created = today - timedelta(days=days_ago, hours=5)
        q = _make_quote(db, rep, customer, title, items, created, products)
        t = _progress(db, q, target, users, rng, created)
        q.valid_until = (today + timedelta(days=rng.randint(4, 24))).date()
        q.updated_at = min(t, today)
        db.flush()

    billing.run_billing(db, today.date())   # catch recurring invoices up to today
    _collect(db, users, rng, today)
    db.commit()


def seed_if_empty() -> bool:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).count():
            return False
        seed(db)
        return True


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_database()
    created = seed_if_empty()
    print("Seeded demo data." if created else "Database already has data (use --reset to rebuild).")
    print(f"Demo password for every account: {DEMO_PASSWORD}")
