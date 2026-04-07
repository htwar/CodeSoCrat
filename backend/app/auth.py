from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
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


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)


def _decode_jwt_without_verification(token: str) -> dict:
    try:
        _header, payload, _signature = token.split(".", 2)
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:  # pragma: no cover - defensive parsing
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential.") from exc


def verify_google_id_token(token: str) -> dict:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured for this environment.",
        )

    payload = _decode_jwt_without_verification(token)
    audience = payload.get("aud")
    issuer = payload.get("iss")
    if audience != settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google credential audience mismatch.")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google credential issuer mismatch.")

    try:
        with urlopen(
            "https://oauth2.googleapis.com/tokeninfo?id_token=" + token,
            timeout=5,
        ) as response:
            verified = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in could not be verified right now.",
        ) from exc

    if verified.get("aud") != settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google credential audience mismatch.")
    if not verified.get("sub") or not verified.get("email"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google credential is missing required claims.")
    if verified.get("email_verified") not in {"true", True}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email must be verified.")
    return verified


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
