"""Unit tests for JWT and password utilities."""

import time

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self) -> None:
        hashed = hash_password("mysecret")
        assert hashed != "mysecret"

    def test_verify_correct_password(self) -> None:
        hashed = hash_password("correct-horse")
        assert verify_password("correct-horse", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("correct-horse")
        assert verify_password("wrong-password", hashed) is False

    def test_same_password_different_hashes(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts differ


class TestJWT:
    def test_create_and_decode_token(self) -> None:
        token = create_access_token("user-123")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"

    def test_token_has_expiry(self) -> None:
        token = create_access_token("user-123")
        payload = decode_access_token(token)
        assert "exp" in payload
        assert payload["exp"] > time.time()

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(JWTError):
            decode_access_token("not.a.valid.token")

    def test_tampered_token_raises(self) -> None:
        token = create_access_token("user-123")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_extra_claims(self) -> None:
        token = create_access_token("user-456", extra={"role": "admin"})
        payload = decode_access_token(token)
        assert payload["role"] == "admin"
