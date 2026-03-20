from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)


def create_token(user: User) -> str:
    payload = f"{user.id}:{user.role}"
    signature = hmac.new(settings.secret_key_current.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_token(token: str) -> tuple[int, str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user_id_str, role, signature = decoded.split(":", 2)
    except Exception as exc:  # pragma: no cover - defensive parse guard
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc

    payload = f"{user_id_str}:{role}"
    if not any(
        hmac.compare_digest(
            signature,
            hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest(),
        )
        for secret in [settings.secret_key_current, *settings.secret_key_previous]
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    return int(user_id_str), role


def try_decode_token(token: str) -> Optional[tuple[int, str]]:
    try:
        return decode_token(token)
    except HTTPException:
        return None


def create_csrf_token(session_token: str) -> str:
    signature = hmac.new(
        settings.secret_key_current.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    raw = f"{session_token}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def verify_csrf_token(session_token: str, csrf_token: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(csrf_token.encode("utf-8")).decode("utf-8")
        token_value, signature = decoded.rsplit(":", 1)
    except Exception:  # pragma: no cover - defensive parse guard
        return False

    if not hmac.compare_digest(token_value, session_token):
        return False

    return any(
        hmac.compare_digest(
            signature,
            hmac.new(secret.encode("utf-8"), session_token.encode("utf-8"), hashlib.sha256).hexdigest(),
        )
        for secret in [settings.secret_key_current, *settings.secret_key_previous]
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token: Optional[str] = None
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get(settings.session_cookie_name)

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    user_id, _role = decode_token(token)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


def require_csrf(
    request: Request,
    csrf_header: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    session_token = request.cookies.get(settings.session_cookie_name)
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    if not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    if not verify_csrf_token(session_token, csrf_cookie):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")


def require_author(user: User = Depends(get_current_user)) -> User:
    if user.role != "Author":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Author role required.")
    return user
