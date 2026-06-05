"""Password hashing, JWT issuing and role-based access dependencies."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Role, User

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": expires}, settings.secret_key,
                      algorithm=settings.algorithm)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, settings.secret_key, algorithms=[settings.algorithm])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")
        return user
    return dependency


internal_user = require_roles(*Role.INTERNAL)
admin_user = require_roles(Role.ADMIN)
manager_user = require_roles(Role.ADMIN, Role.MANAGER)
finance_user = require_roles(Role.ADMIN, Role.FINANCE)
sales_user = require_roles(Role.ADMIN, Role.MANAGER, Role.REP)
