"""Secrets-at-rest encryption unit tests (no DB)."""

from __future__ import annotations

import sitebot.crypto as crypto


def _with_key(monkeypatch, key: str):  # type: ignore[no-untyped-def]
    class S:
        secret_encryption_key = key
    monkeypatch.setattr(crypto, "get_settings", lambda: S())
    monkeypatch.setattr(crypto, "_fernet", None)
    monkeypatch.setattr(crypto, "_warned", False)


def test_roundtrip_and_idempotence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _with_key(monkeypatch, "test-master-key")
    token = crypto.encrypt_secret("sk-live-abc123")
    assert token is not None and token.startswith("enc:v1:")
    assert "sk-live-abc123" not in token
    # Encrypting an already-encrypted value must not double-wrap.
    assert crypto.encrypt_secret(token) == token
    assert crypto.decrypt_secret(token) == "sk-live-abc123"
    # Plaintext (pre-migration rows) passes through decrypt untouched.
    assert crypto.decrypt_secret("legacy-plaintext") == "legacy-plaintext"
    # Empties pass through both ways.
    assert crypto.encrypt_secret("") == ""
    assert crypto.decrypt_secret(None) is None


def test_without_key_is_passthrough(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _with_key(monkeypatch, "")
    assert crypto.encrypt_secret("plain") == "plain"


def test_wrong_key_fails_loud(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    _with_key(monkeypatch, "key-one")
    token = crypto.encrypt_secret("secret-value")
    _with_key(monkeypatch, "key-two")
    with pytest.raises(RuntimeError, match="SECRET_ENCRYPTION_KEY"):
        crypto.decrypt_secret(token)
