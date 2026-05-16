"""Credential storage with Fernet encryption."""

import json
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.common.dto import DatabaseConnectionConfig
from src.common.logger import get_logger

logger = get_logger(__name__)


class CredentialStorageError(Exception):
    """Base exception for credential storage errors."""


class EncryptionKeyError(CredentialStorageError):
    """Raised when encryption key is invalid or missing."""


class CredentialNotFoundError(CredentialStorageError):
    """Raised when a connection is not found."""


MASKED_PASSWORD = "********"


def _mask(config: DatabaseConnectionConfig) -> DatabaseConnectionConfig:
    """Return a copy of the config with the password masked."""
    return config.model_copy(update={"password": MASKED_PASSWORD})


class CredentialStorage:
    """Encrypted storage for database connection credentials."""

    def __init__(self, storage_path: str, encryption_key: str):
        self.storage_path = Path(storage_path)
        self._validate_and_set_key(encryption_key)
        self._active_connection_id: str | None = None
        self._ensure_storage_exists()

    def _validate_and_set_key(self, encryption_key: str) -> None:
        if not encryption_key:
            raise EncryptionKeyError("Encryption key is required")

        try:
            self._fernet = Fernet(encryption_key.encode())
        except Exception as e:
            raise EncryptionKeyError(f"Invalid encryption key format: {e}")

    def _ensure_storage_exists(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self._write_data({"connections": {}, "active_connection_id": None})

    def _read_data(self) -> dict:
        if not self.storage_path.exists():
            return {"connections": {}, "active_connection_id": None}

        try:
            encrypted_data = self.storage_path.read_bytes()
            if not encrypted_data:
                return {"connections": {}, "active_connection_id": None}

            decrypted_data = self._fernet.decrypt(encrypted_data)
            data = json.loads(decrypted_data.decode())
            self._active_connection_id = data.get("active_connection_id")
            return data
        except InvalidToken:
            logger.error("Failed to decrypt credential storage - invalid key")
            raise EncryptionKeyError("Failed to decrypt storage - encryption key may have changed")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse credential storage: {e}")
            return {"connections": {}, "active_connection_id": None}

    def _write_data(self, data: dict) -> None:
        json_data = json.dumps(data, indent=2)
        encrypted_data = self._fernet.encrypt(json_data.encode())
        self.storage_path.write_bytes(encrypted_data)

    def list_connections(self) -> list[DatabaseConnectionConfig]:
        data = self._read_data()
        connections = []
        for conn_id, conn_data in data.get("connections", {}).items():
            raw = {**conn_data, "id": conn_id, "password": MASKED_PASSWORD}
            connections.append(DatabaseConnectionConfig(**raw))
        return connections

    def get_connection(self, connection_id: str) -> DatabaseConnectionConfig:
        """Get a connection with the password masked (safe for API responses)."""
        return _mask(self.get_connection_with_password(connection_id))

    def get_connection_with_password(self, connection_id: str) -> DatabaseConnectionConfig:
        """Get a connection including the actual password (for connecting to the DB)."""
        data = self._read_data()
        connections = data.get("connections", {})

        if connection_id not in connections:
            raise CredentialNotFoundError(f"Connection '{connection_id}' not found")

        conn_data = connections[connection_id].copy()
        conn_data["id"] = connection_id
        return DatabaseConnectionConfig(**conn_data)

    def save_connection(self, config: DatabaseConnectionConfig) -> DatabaseConnectionConfig:
        data = self._read_data()
        connections = data.get("connections", {})

        connection_id = config.id or str(uuid.uuid4())
        conn_dict = config.model_dump(exclude={"id"})
        connections[connection_id] = conn_dict

        data["connections"] = connections
        self._write_data(data)

        logger.info(f"Saved connection '{config.name}' with ID '{connection_id}'")
        return _mask(config.model_copy(update={"id": connection_id}))

    def update_connection(
        self, connection_id: str, config: DatabaseConnectionConfig
    ) -> DatabaseConnectionConfig:
        data = self._read_data()
        connections = data.get("connections", {})

        if connection_id not in connections:
            raise CredentialNotFoundError(f"Connection '{connection_id}' not found")

        # If the caller passed the masked placeholder, keep the stored password.
        if config.password == MASKED_PASSWORD:
            existing = connections[connection_id]
            config = config.model_copy(update={"password": existing["password"]})

        conn_dict = config.model_dump(exclude={"id"})
        connections[connection_id] = conn_dict

        data["connections"] = connections
        self._write_data(data)

        logger.info(f"Updated connection '{config.name}' (ID: {connection_id})")
        return _mask(config.model_copy(update={"id": connection_id}))

    def delete_connection(self, connection_id: str) -> None:
        data = self._read_data()
        connections = data.get("connections", {})

        if connection_id not in connections:
            raise CredentialNotFoundError(f"Connection '{connection_id}' not found")

        del connections[connection_id]

        # Clear active connection if it was deleted
        if data.get("active_connection_id") == connection_id:
            data["active_connection_id"] = None
            self._active_connection_id = None

        data["connections"] = connections
        self._write_data(data)
        logger.info(f"Deleted connection with ID '{connection_id}'")

    def set_active_connection(self, connection_id: str | None) -> None:
        data = self._read_data()

        if connection_id is not None:
            if connection_id not in data.get("connections", {}):
                raise CredentialNotFoundError(f"Connection '{connection_id}' not found")

        data["active_connection_id"] = connection_id
        self._active_connection_id = connection_id
        self._write_data(data)
        logger.info(f"Set active connection to '{connection_id}'")

    def get_active_connection_id(self) -> str | None:
        if self._active_connection_id is None:
            data = self._read_data()
            self._active_connection_id = data.get("active_connection_id")
        return self._active_connection_id

    def get_active_connection(self) -> DatabaseConnectionConfig | None:
        active_id = self.get_active_connection_id()
        if active_id is None:
            return None
        try:
            return self.get_connection_with_password(active_id)
        except CredentialNotFoundError:
            return None

    @staticmethod
    def generate_encryption_key() -> str:
        """Generate a new Fernet encryption key."""
        return Fernet.generate_key().decode()


def get_credential_storage_from_env() -> CredentialStorage:
    """Create a CredentialStorage instance from environment variables."""
    storage_path = os.getenv("CREDENTIAL_STORAGE_PATH", "./data/connections.enc")
    encryption_key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")

    if not encryption_key:
        raise EncryptionKeyError(
            "CREDENTIAL_ENCRYPTION_KEY environment variable is required. "
            f"Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    return CredentialStorage(storage_path, encryption_key)


__all__ = [
    "CredentialStorage",
    "CredentialStorageError",
    "EncryptionKeyError",
    "CredentialNotFoundError",
    "MASKED_PASSWORD",
    "get_credential_storage_from_env",
]
