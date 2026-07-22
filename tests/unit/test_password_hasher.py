"""Unit tests for the bcrypt password hashing strategy."""

from src.modules.auth.password_hasher import BcryptPasswordHasher


def test_hash_is_not_plaintext(password_hasher: BcryptPasswordHasher) -> None:
    hashed = password_hasher.hash("s3cret-password")
    assert hashed != "s3cret-password"
    assert hashed.startswith("$2b$")


def test_verify_accepts_correct_password(password_hasher: BcryptPasswordHasher) -> None:
    hashed = password_hasher.hash("correct horse battery staple")
    assert password_hasher.verify("correct horse battery staple", hashed) is True


def test_verify_rejects_wrong_password(password_hasher: BcryptPasswordHasher) -> None:
    hashed = password_hasher.hash("correct horse battery staple")
    assert password_hasher.verify("wrong password", hashed) is False


def test_verify_handles_malformed_hash(password_hasher: BcryptPasswordHasher) -> None:
    # A corrupt stored hash must not raise — it should simply fail to match.
    assert password_hasher.verify("anything", "not-a-real-hash") is False


def test_hashes_are_salted(password_hasher: BcryptPasswordHasher) -> None:
    # Two hashes of the same password differ because each uses a fresh salt.
    assert password_hasher.hash("same") != password_hasher.hash("same")
