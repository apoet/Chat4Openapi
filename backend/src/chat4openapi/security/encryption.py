import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptionError(ValueError):
    pass


class SecretCipher:
    def __init__(self, key: bytes | str) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt_json(self, value: Any) -> bytes:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return self._fernet.encrypt(raw)

    def decrypt_json(self, encrypted: bytes) -> Any:
        try:
            raw = self._fernet.decrypt(encrypted)
        except InvalidToken as exc:
            raise SecretDecryptionError("Encrypted session data cannot be decrypted") from exc
        return json.loads(raw)


def load_secret_cipher(configured_key: str | None, key_file: Path) -> SecretCipher:
    if configured_key:
        return SecretCipher(configured_key)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with key_file.open("xb") as handle:
            key = Fernet.generate_key()
            handle.write(key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    except FileExistsError:
        key = key_file.read_bytes().strip()
    return SecretCipher(key)
