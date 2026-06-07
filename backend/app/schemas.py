"""Request payload schemas (validation lives here; responses are built in serializers.py)."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

RoleName = Literal["admin", "sales_manager", "sales_rep", "finance", "customer"]
Period = Literal["monthly", "quarterly", "annual"]
Region = Literal["North", "South", "East", "West"]
Tier = Literal["standard", "silver", "gold", "platinum"]


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: RoleName
    customer_id: Optional[int] = None


class UserUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    role: Optional[RoleName] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    industry: Optional[str] = Field(default=None, max_length=80)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=40)
    city: Optional[str] = Field(default=None, max_length=80)
    region: Region = "West"
    gstin: Optional[str] = Field(default=None, max_length=20)
    tier: Tier = "standard"
    credit_limit: float = Field(default=500000, ge=0)
    payment_terms_days: int = Field(default=30, ge=0, le=180)


class ProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=60)
    description: Optional[str] = None
    price: float = Field(gt=0)
    cost: float = Field(default=0, ge=0)
    unit: str = Field(default="each", max_length=30)
    tax_rate: float = Field(default=18, ge=0, le=50)
    is_subscription: bool = False
    billing_period: Optional[Period] = None
    is_stocked: bool = True
    is_active: bool = True


class LineIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=100000)
    discount_percent: float = Field(default=0, ge=0, le=90)
    unit_price: Optional[float] = Field(default=None, gt=0)  # defaults to list price
    description: Optional[str] = Field(default=None, max_length=255)


class QuotationIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    customer_id: int
    valid_until: Optional[date] = None
    payment_terms_days: int = Field(default=30, ge=0, le=180)
    notes: Optional[str] = None
    lines: list[LineIn] = Field(default_factory=list)


class PreviewIn(BaseModel):
    customer_id: Optional[int] = None
    payment_terms_days: int = Field(default=30, ge=0, le=180)
    lines: list[LineIn] = Field(default_factory=list)


class DecisionIn(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=1000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    proposed_discount: Optional[float] = Field(default=None, gt=0, le=90)


class CounterResponseIn(BaseModel):
    accept: bool
    comment: Optional[str] = Field(default=None, max_length=1000)


class PortalActionIn(BaseModel):
    name: str = Field(default="Customer", min_length=1, max_length=120)
    reason: Optional[str] = Field(default=None, max_length=255)


class PortalMessageIn(MessageIn):
    name: str = Field(default="Customer", min_length=1, max_length=120)


class StockAdjustIn(BaseModel):
    warehouse_id: int
    product_id: int
    delta: int = Field(ge=-100000, le=100000)
    reason: str = Field(default="Manual adjustment", max_length=120)


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    method: Literal["bank_transfer", "upi", "card", "cheque", "cash"] = "bank_transfer"
    reference: Optional[str] = Field(default=None, max_length=80)


class RunBillingIn(BaseModel):
    as_of: Optional[date] = None


class DiscountTierIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    category: Optional[str] = Field(default=None, max_length=60)
    max_discount_percent: float = Field(ge=0, le=90)


class SettingsIn(BaseModel):
    company_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    min_margin_percent: Optional[float] = Field(default=None, ge=0, le=90)
    manager_threshold: Optional[float] = Field(default=None, ge=1, le=100)
    finance_threshold: Optional[float] = Field(default=None, ge=1, le=100)
    quote_validity_days: Optional[int] = Field(default=None, ge=1, le=365)
