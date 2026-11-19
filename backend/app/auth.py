import hashlib
import hmac
import os
import secrets
import time


SESSION_SECONDS = 7 * 24 * 60 * 60
COOKIE_NAME = "homestead_session"


def _secret() -> bytes:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET environment variable is required.")
    return secret.encode()


def check_credentials(username: str, password: str) -> bool:
    expected_user = os.environ.get("APP_USERNAME")
    expected_password = os.environ.get("APP_PASSWORD")
    if not expected_user or not expected_password:
        raise RuntimeError("APP_USERNAME and APP_PASSWORD environment variables are required.")
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode())
    password_ok = hmac.compare_digest(password.encode(), expected_password.encode())
    return user_ok and password_ok


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def create_token() -> str:
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(16)}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        expires, nonce, signature = token.split(".")
    except ValueError:
        return False
    payload = f"{expires}.{nonce}"
    return hmac.compare_digest(signature, _sign(payload)) and int(expires) > time.time()
