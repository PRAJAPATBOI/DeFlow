"""Database models for the DealFlow360 quote-to-cash domain."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (portable across SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


Money = Numeric(14, 2)
Pct = Numeric(6, 2)


class Role:
    ADMIN = "admin"
    MANAGER = "sales_manager"
    REP = "sales_rep"
    FINANCE = "finance"
    CUSTOMER = "customer"
    INTERNAL = (ADMIN, MANAGER, REP, FINANCE)
    ALL = (ADMIN, MANAGER, REP, FINANCE, CUSTOMER)


class QStatus:
    DRAFT = "draft"
    PENDING_MANAGER = "pending_manager"
    PENDING_FINANCE = "pending_finance"
    APPROVED = "approved"
    SENT = "sent"
    NEGOTIATING = "negotiating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"      # rejected internally by an approver
    DECLINED = "declined"      # declined by the customer
    LOST = "lost"
    EXPIRED = "expired"
    OPEN = (DRAFT, PENDING_MANAGER, PENDING_FINANCE, APPROVED, SENT, NEGOTIATING)
    CLOSED_LOST = (REJECTED, DECLINED, LOST, EXPIRED)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default=Role.CUSTOMER)
    is_active = Column(Boolean, nullable=False, default=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", foreign_keys=[customer_id])


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, index=True)
    industry = Column(String(80), nullable=True)
    contact_name = Column(String(120), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(40), nullable=True)
    city = Column(String(80), nullable=True)
    region = Column(String(20), nullable=False, default="West")  # North / South / East / West
    gstin = Column(String(20), nullable=True)
    tier = Column(String(20), nullable=False, default="standard")
    credit_limit = Column(Money, nullable=False, default=500000)
    payment_terms_days = Column(Integer, nullable=False, default=30)
    owner_id = Column(Integer, ForeignKey("users.id", use_alter=True, name="fk_customer_owner"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    owner = relationship("User", foreign_keys=[owner_id])
    quotations = relationship("Quotation", back_populates="customer")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    sku = Column(String(40), unique=True, index=True, nullable=False)
    name = Column(String(160), nullable=False)
    category = Column(String(60), nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Money, nullable=False)
    cost = Column(Money, nullable=False, default=0)
    unit = Column(String(30), nullable=False, default="each")
    tax_rate = Column(Pct, nullable=False, default=18)
    is_subscription = Column(Boolean, nullable=False, default=False)
    billing_period = Column(String(12), nullable=True)  # monthly / quarterly / annual
    is_stocked = Column(Boolean, nullable=False, default=True)  # False for services & subscriptions
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    inventory = relationship("Inventory", back_populates="product")


class DiscountTier(Base):
    """Maximum discount a rep may give without raising the deal's risk score."""
    __tablename__ = "discount_tiers"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    category = Column(String(60), nullable=True, unique=True)  # NULL = default for all categories
    max_discount_percent = Column(Pct, nullable=False)


class Warehouse(Base):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True)
    code = Column(String(12), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    city = Column(String(80), nullable=False)
    region = Column(String(20), nullable=False)
    base_shipping_fee = Column(Money, nullable=False, default=0)
    per_unit_shipping = Column(Money, nullable=False, default=0)
    lead_days = Column(Integer, nullable=False, default=3)

    inventory = relationship("Inventory", back_populates="warehouse")


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id"),)
    id = Column(Integer, primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=0)   # physically on hand
    reserved = Column(Integer, nullable=False, default=0)   # promised to open fulfilment orders
    reorder_level = Column(Integer, nullable=False, default=5)

    warehouse = relationship("Warehouse", back_populates="inventory")
    product = relationship("Product", back_populates="inventory")

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)


class Quotation(Base):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True)
    number = Column(String(24), unique=True, index=True, nullable=True)
    title = Column(String(200), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    rep_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(24), nullable=False, default=QStatus.DRAFT, index=True)
    version = Column(Integer, nullable=False, default=1)
    parent_id = Column(Integer, ForeignKey("quotations.id"), nullable=True)
    valid_until = Column(Date, nullable=True)
    payment_terms_days = Column(Integer, nullable=False, default=30)
    notes = Column(Text, nullable=True)
    # pricing snapshot (recomputed on every change)
    subtotal = Column(Money, nullable=False, default=0)
    discount_total = Column(Money, nullable=False, default=0)
    tax_total = Column(Money, nullable=False, default=0)
    total = Column(Money, nullable=False, default=0)
    margin_percent = Column(Pct, nullable=False, default=0)
    # risk + approval
    risk_score = Column(Pct, nullable=False, default=0)
    risk_level = Column(String(10), nullable=False, default="low")
    approved_level = Column(Integer, nullable=False, default=0)  # 0 none, 1 manager, 2 finance
    portal_token = Column(String(64), unique=True, index=True, nullable=True)
    lost_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="quotations")
    rep = relationship("User", foreign_keys=[rep_id])
    lines = relationship("QuotationLine", back_populates="quotation", cascade="all, delete-orphan",
                         order_by="QuotationLine.id")
    events = relationship("QuotationEvent", back_populates="quotation", cascade="all, delete-orphan",
                          order_by="QuotationEvent.id")
    messages = relationship("NegotiationMessage", back_populates="quotation", cascade="all, delete-orphan",
                            order_by="NegotiationMessage.id")


class QuotationLine(Base):
    __tablename__ = "quotation_lines"
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    description = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Money, nullable=False)
    unit_cost = Column(Money, nullable=False, default=0)
    discount_percent = Column(Pct, nullable=False, default=0)
    tax_rate = Column(Pct, nullable=False, default=18)
    is_subscription = Column(Boolean, nullable=False, default=False)
    billing_period = Column(String(12), nullable=True)
    line_total = Column(Money, nullable=False, default=0)  # net of discount, before tax

    quotation = relationship("Quotation", back_populates="lines")
    product = relationship("Product")


class QuotationEvent(Base):
    """Immutable timeline of everything that happened to a quotation (approval trail)."""
    __tablename__ = "quotation_events"
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = Column(String(120), nullable=False, default="System")
    action = Column(String(40), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    quotation = relationship("Quotation", back_populates="events")


class NegotiationMessage(Base):
    __tablename__ = "negotiation_messages"
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_name = Column(String(120), nullable=False)
    side = Column(String(10), nullable=False)  # customer / internal
    message = Column(Text, nullable=False)
    proposed_discount = Column(Pct, nullable=True)  # counter-offer: uniform discount % requested
    offer_status = Column(String(10), nullable=True)  # open / accepted / rejected (counter-offers only)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    quotation = relationship("Quotation", back_populates="messages")


class FulfillmentOrder(Base):
    __tablename__ = "fulfillment_orders"
    id = Column(Integer, primary_key=True)
    number = Column(String(24), unique=True, nullable=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # NULL = backorder
    status = Column(String(16), nullable=False, default="planned")
    shipping_cost = Column(Money, nullable=False, default=0)
    eta = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)

    quotation = relationship("Quotation")
    warehouse = relationship("Warehouse")
    lines = relationship("FulfillmentLine", back_populates="order", cascade="all, delete-orphan")


class FulfillmentLine(Base):
    __tablename__ = "fulfillment_lines"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("fulfillment_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("FulfillmentOrder", back_populates="lines")
    product = relationship("Product")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Money, nullable=False)  # net price per unit per billing period
    tax_rate = Column(Pct, nullable=False, default=18)
    billing_period = Column(String(12), nullable=False, default="monthly")
    status = Column(String(12), nullable=False, default="active")  # active / paused / cancelled
    start_date = Column(Date, nullable=False)
    next_billing_date = Column(Date, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    quotation = relationship("Quotation")
    customer = relationship("Customer")
    product = relationship("Product")


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    number = Column(String(24), unique=True, nullable=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    kind = Column(String(12), nullable=False, default="one_time")  # one_time / recurring
    status = Column(String(16), nullable=False, default="issued")  # issued / partially_paid / paid / void
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    subtotal = Column(Money, nullable=False, default=0)
    tax_total = Column(Money, nullable=False, default=0)
    total = Column(Money, nullable=False, default=0)
    amount_paid = Column(Money, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    customer = relationship("Customer")
    quotation = relationship("Quotation")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Money, nullable=False)
    tax_rate = Column(Pct, nullable=False, default=18)
    amount = Column(Money, nullable=False)  # before tax

    invoice = relationship("Invoice", back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    amount = Column(Money, nullable=False)
    method = Column(String(30), nullable=False, default="bank_transfer")
    reference = Column(String(80), nullable=True)
    paid_at = Column(DateTime, default=utcnow, nullable=False)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    invoice = relationship("Invoice", back_populates="payments")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(String(120), nullable=False, default="System")
    action = Column(String(60), nullable=False)
    entity = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(60), primary_key=True)
    value = Column(String(255), nullable=False)
