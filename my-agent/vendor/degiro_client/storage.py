"""Persistence for credentials (encrypted) and session state (plain JSON).

Data directory resolution order: $DEGIRO_DATA_DIR, then /data (HA add-on
convention) if writable, else ~/.degiro.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .models import Credentials, SessionState

KDF_SALT = b"degiro-client-v1"
KDF_ITERATIONS = 200_000


def data_dir() -> Path:
    explicit = os.environ.get("DEGIRO_DATA_DIR")
    if explicit:
        p = Path(explicit)
    elif Path("/data").is_dir() and os.access("/data", os.W_OK):
        p = Path("/data")
    else:
        p = Path.home() / ".degiro"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _credentials_path() -> Path:
    return data_dir() / "credentials.enc"


def _session_path() -> Path:
    return data_dir() / "session.json"


def _fernet() -> Fernet:
    passphrase = os.environ.get("DEGIRO_KEY")
    if not passphrase:
        raise RuntimeError(
            "DEGIRO_KEY env var is required to read/write credentials"
        )
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=KDF_SALT,
        iterations=KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def save_credentials(creds: Credentials) -> None:
    payload = json.dumps(
        {
            "username": creds.username,
            "password": creds.password,
            "totp_seed": creds.totp_seed,
        }
    ).encode("utf-8")
    token = _fernet().encrypt(payload)
    path = _credentials_path()
    path.write_bytes(token)
    os.chmod(path, 0o600)


def load_credentials() -> Credentials | None:
    path = _credentials_path()
    if not path.exists():
        return None
    try:
        raw = _fernet().decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError(
            "Failed to decrypt credentials — DEGIRO_KEY does not match"
        ) from exc
    data = json.loads(raw.decode("utf-8"))
    return Credentials(
        username=data["username"],
        password=data["password"],
        totp_seed=data.get("totp_seed"),
    )


def delete_credentials() -> None:
    p = _credentials_path()
    if p.exists():
        p.unlink()


def save_session(session: SessionState) -> None:
    path = _session_path()
    path.write_text(json.dumps(session.to_dict(), indent=2))
    os.chmod(path, 0o600)


def load_session() -> SessionState | None:
    path = _session_path()
    if not path.exists():
        return None
    try:
        return SessionState.from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError):
        return None


def delete_session() -> None:
    p = _session_path()
    if p.exists():
        p.unlink()
