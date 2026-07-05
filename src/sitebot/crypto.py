"""Encryption at rest for client secrets.

Per-site LLM keys, channel tokens, and Secrets-Guardian values are written
through encrypt_secret() and read back through decrypt_secret(). Values are
stored as "enc:v1:<fernet token>", so encryption is detectable, idempotent,
and old plaintext rows keep working until scripts/encrypt_existing_secrets.py
migrates them.

Key management: SECRET_ENCRYPTION_KEY is any string; it is stretched to a
Fernet key via SHA-256. Without it the module passes values through unchanged
(single-machine dev mode) and logs one warning at startup - production
deployments must set it (see docs/DEPLOYMENT_GUIDE.md).
"""

from __future__ import annotations

import base64
import hashlib
import logging

from sitebot.config import get_settings

log = logging.getLogger(__name__)

_PREFIX = "enc:v1:"
_fernet = None
_warned = False


def _get_fernet():  # type: ignore[no-untyped-def]
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    key = get_settings().secret_encryption_key
    if not key:
        if not _warned:
            _warned = True
            log.warning(
                "SECRET_ENCRYPTION_KEY is not set: client secrets are stored "
                "in plaintext. Set it before taking production traffic."
            )
        return None
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt a secret for storage. Idempotent; empty values pass through."""
    if not value or value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        return value
    return _PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored secret. Plaintext (pre-migration) values pass through."""
    if not value or not value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        raise RuntimeError(
            "Encrypted secret found but SECRET_ENCRYPTION_KEY is not set."
        )
    from cryptography.fernet import InvalidToken

    try:
        return f.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Could not decrypt a stored secret - SECRET_ENCRYPTION_KEY changed?"
        ) from exc
