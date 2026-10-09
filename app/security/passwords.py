from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
MIN_PASSWORD_LENGTH = 12


def hash_password(raw_password: str) -> str:
    if len(raw_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, encoded_hash: str) -> bool:
    if not encoded_hash.startswith("$argon2id$"):
        return False
    try:
        return _hasher.verify(encoded_hash, raw_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def is_argon2id_hash(encoded_hash: str) -> bool:
    return encoded_hash.startswith("$argon2id$")
