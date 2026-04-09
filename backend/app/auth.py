from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
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
PASSWORD_HASH_VERSION = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 200_000


# Local password auth is intentionally simple for this project, while Google
# auth is layered on top using the same signed session cookie model.
def hash_password(password: str) -> str:
    # Convert a plaintext password into a salted PBKDF2 hash string that can be
    # stored safely in the database.
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return ":".join(
        [
            PASSWORD_HASH_VERSION,
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("utf-8"),
            base64.urlsafe_b64encode(derived).decode("utf-8"),
        ]
    )


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    # Compare an incoming password against either the newer salted PBKDF2 format
    # or the legacy unsalted SHA-256 format kept for migration compatibility.
    if not password_hash:
        return False
    if password_hash.startswith(f"{PASSWORD_HASH_VERSION}:"):
        try:
            _version, iterations_str, encoded_salt, encoded_hash = password_hash.split(":", 3)
            salt = base64.urlsafe_b64decode(encoded_salt.encode("utf-8"))
            stored_hash = base64.urlsafe_b64decode(encoded_hash.encode("utf-8"))
            iterations = int(iterations_str)
        except (ValueError, TypeError):
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(derived, stored_hash)

    # Legacy support for older local databases created before salted hashes
    # were introduced.
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, password_hash)


def password_needs_rehash(password_hash: Optional[str]) -> bool:
    # Older SHA-256 hashes and outdated PBKDF2 iteration counts should be
    # refreshed after a successful local login.
    if not password_hash:
        return False
    if not password_hash.startswith(f"{PASSWORD_HASH_VERSION}:"):
        return True
    try:
        _version, iterations_str, _encoded_salt, _encoded_hash = password_hash.split(":", 3)
        return int(iterations_str) < PASSWORD_HASH_ITERATIONS
    except (ValueError, TypeError):
        return True


def _decode_jwt_without_verification(token: str) -> dict:
    # Read the Google JWT payload quickly so basic claim checks can happen
    # before the token is verified against Google's endpoint.
    try:
        _header, payload, _signature = token.split(".", 2)
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:  # pragma: no cover - defensive parsing
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential.") from exc


def verify_google_id_token(token: str) -> dict:
    # Validate the Google credential both locally and through Google's
    # tokeninfo endpoint before trusting it for sign-in.
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


# Session tokens store the user id and role so the backend can restore the
# current user without a server-side session table.
def create_token(user: User) -> str:
    # Build the signed session token that is stored in the session cookie.
    payload = f"{user.id}:{user.role}"
    signature = hmac.new(settings.secret_key_current.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_token(token: str) -> tuple[int, str]:
    # Decode and verify a session token, supporting key rotation through
    # current and previous secret keys.
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
    # Lightweight helper for callers that want "invalid token" to become None
    # instead of an exception.
    try:
        return decode_token(token)
    except HTTPException:
        return None


def create_csrf_token(session_token: str) -> str:
    # Tie the CSRF token to the current session cookie so state-changing
    # requests can be verified without server-side storage.
    signature = hmac.new(
        settings.secret_key_current.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    raw = f"{session_token}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def verify_csrf_token(session_token: str, csrf_token: str) -> bool:
    # Confirm the CSRF cookie was generated from this exact session token.
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
    # Resolve the authenticated user from either a bearer token or the signed
    # session cookie attached by the browser.
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
    # Guard POST/PUT/DELETE routes so only pages that hold the matching CSRF
    # cookie can submit state-changing requests.
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
    # Reuse the current-user dependency, then enforce the elevated author role.
    if user.role != "Author":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Author role required.")
    return user
