"""Authentication and user administration."""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Role, User, utcnow
from ..schemas import LoginIn, PasswordChangeIn, RegisterIn, UserCreateIn, UserUpdateIn
from ..security import admin_user, create_access_token, get_current_user, hash_password, verify_password
from ..serializers import user_out
from ..services.workflow import audit

router = APIRouter(tags=["auth"])

MAX_FAILED, WINDOW_SECONDS = 8, 300
_failed: dict[str, list[float]] = defaultdict(list)


def _throttle(email: str):
    now = time.time()
    _failed[email] = [t for t in _failed[email] if now - t < WINDOW_SECONDS]
    if len(_failed[email]) >= MAX_FAILED:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in a few minutes.")


def _token_response(user: User) -> dict:
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user_out(user)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    _throttle(email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        _failed[email].append(time.time())
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated")
    _failed.pop(email, None)
    user.last_login_at = utcnow()
    db.commit()
    return _token_response(user)


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Public sign-up always creates a customer-portal account - never an internal role."""
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    customer = Customer(name=body.company.strip(), contact_name=body.name.strip(), email=email)
    db.add(customer)
    db.flush()
    user = User(name=body.name.strip(), email=email, hashed_password=hash_password(body.password),
                role=Role.CUSTOMER, customer_id=customer.id)
    db.add(user)
    db.flush()
    audit(db, user, "user.register", "user", user.id, email)
    db.commit()
    return _token_response(user)


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/auth/change-password")
def change_password(body: PasswordChangeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    audit(db, user, "user.password_change", "user", user.id)
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    if body.role == Role.CUSTOMER and not (body.customer_id and db.get(Customer, body.customer_id)):
        raise HTTPException(422, "Customer users must be linked to an existing customer")
    user = User(name=body.name.strip(), email=email, hashed_password=hash_password(body.password), role=body.role,
                customer_id=body.customer_id if body.role == Role.CUSTOMER else None)
    db.add(user)
    db.flush()
    audit(db, actor, "user.create", "user", user.id, f"{email} as {body.role}")
    db.commit()
    return user_out(user)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == actor.id and (changes.get("is_active") is False or changes.get("role", Role.ADMIN) != Role.ADMIN):
        raise HTTPException(400, "You cannot deactivate or demote your own admin account")
    if changes.get("role") == Role.CUSTOMER and not user.customer_id:
        raise HTTPException(422, "This user is not linked to a customer company")
    if "password" in changes:
        user.hashed_password = hash_password(changes.pop("password"))
    for key, value in changes.items():
        setattr(user, key, value)
    audit(db, actor, "user.update", "user", user.id, ", ".join(f"{k}={v}" for k, v in changes.items()) or "password")
    db.commit()
    return user_out(user)
