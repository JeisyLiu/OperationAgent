from pathlib import Path

from cryptography.fernet import Fernet

from app.config import settings

FERNET_KEY_FILE = ".fernet.key"


def _key_path() -> Path:
    return settings.data_dir / FERNET_KEY_FILE


def _load_or_create_fernet() -> Fernet:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_path = _key_path()
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
    return Fernet(key)


def encrypt_text(plain: str) -> str:
    return _load_or_create_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(cipher: str) -> str:
    return _load_or_create_fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:3]}***{api_key[-4:]}"
