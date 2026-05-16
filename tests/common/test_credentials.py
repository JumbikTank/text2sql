"""Tests for credential storage module."""

import pytest
from cryptography.fernet import Fernet

from src.common.credentials import (
    CredentialNotFoundError,
    CredentialStorage,
    EncryptionKeyError,
)
from src.common.dto import DatabaseConnectionConfig


def test_credential_storage_init(temp_storage_path: str, encryption_key: str):
    """Test CredentialStorage initialization creates storage file."""
    storage = CredentialStorage(temp_storage_path, encryption_key)
    assert storage.storage_path.exists()


def test_credential_storage_invalid_key(temp_storage_path: str):
    """Test CredentialStorage raises error with invalid encryption key."""
    with pytest.raises(EncryptionKeyError):
        CredentialStorage(temp_storage_path, "invalid-key")


def test_credential_storage_empty_key(temp_storage_path: str):
    """Test CredentialStorage raises error with empty encryption key."""
    with pytest.raises(EncryptionKeyError):
        CredentialStorage(temp_storage_path, "")


def test_save_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test saving a new connection."""
    saved = credential_storage.save_connection(sample_connection)

    assert saved.id is not None
    assert saved.name == sample_connection.name
    assert saved.host == sample_connection.host
    assert saved.port == sample_connection.port
    assert saved.database == sample_connection.database
    assert saved.username == sample_connection.username


def test_list_connections(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test listing saved connections."""
    # Save a connection first
    credential_storage.save_connection(sample_connection)

    connections = credential_storage.list_connections()

    assert len(connections) == 1
    assert connections[0].name == sample_connection.name
    # Password should be masked
    assert connections[0].password == "********"


def test_get_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test retrieving a connection by ID."""
    saved = credential_storage.save_connection(sample_connection)

    retrieved = credential_storage.get_connection(saved.id)

    assert retrieved.id == saved.id
    assert retrieved.name == sample_connection.name
    assert retrieved.host == sample_connection.host


def test_get_connection_with_password(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test retrieving a connection with actual password."""
    saved = credential_storage.save_connection(sample_connection)

    retrieved = credential_storage.get_connection_with_password(saved.id)

    assert retrieved.password == sample_connection.password


def test_get_connection_not_found(credential_storage: CredentialStorage):
    """Test getting a non-existent connection raises error."""
    with pytest.raises(CredentialNotFoundError):
        credential_storage.get_connection("non-existent-id")


def test_update_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test updating an existing connection."""
    saved = credential_storage.save_connection(sample_connection)

    updated_config = DatabaseConnectionConfig(
        name="Updated Connection",
        host="newhost",
        port=5433,
        database="newdb",
        username="newuser",
        password="newpassword",
        ssl_mode="require",
    )

    updated = credential_storage.update_connection(saved.id, updated_config)

    assert updated.id == saved.id
    assert updated.name == "Updated Connection"
    assert updated.host == "newhost"
    assert updated.port == 5433


def test_update_connection_not_found(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test updating a non-existent connection raises error."""
    with pytest.raises(CredentialNotFoundError):
        credential_storage.update_connection("non-existent-id", sample_connection)


def test_delete_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test deleting a connection."""
    saved = credential_storage.save_connection(sample_connection)

    credential_storage.delete_connection(saved.id)

    connections = credential_storage.list_connections()
    assert len(connections) == 0


def test_delete_connection_not_found(credential_storage: CredentialStorage):
    """Test deleting a non-existent connection raises error."""
    with pytest.raises(CredentialNotFoundError):
        credential_storage.delete_connection("non-existent-id")


def test_set_active_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test setting the active connection."""
    saved = credential_storage.save_connection(sample_connection)

    credential_storage.set_active_connection(saved.id)

    assert credential_storage.get_active_connection_id() == saved.id


def test_set_active_connection_not_found(credential_storage: CredentialStorage):
    """Test setting a non-existent connection as active raises error."""
    with pytest.raises(CredentialNotFoundError):
        credential_storage.set_active_connection("non-existent-id")


def test_set_active_connection_none(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test clearing the active connection."""
    saved = credential_storage.save_connection(sample_connection)
    credential_storage.set_active_connection(saved.id)

    credential_storage.set_active_connection(None)

    assert credential_storage.get_active_connection_id() is None


def test_get_active_connection(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test getting the active connection."""
    saved = credential_storage.save_connection(sample_connection)
    credential_storage.set_active_connection(saved.id)

    active = credential_storage.get_active_connection()

    assert active is not None
    assert active.id == saved.id
    assert active.name == sample_connection.name


def test_get_active_connection_none(credential_storage: CredentialStorage):
    """Test getting active connection when none is set."""
    active = credential_storage.get_active_connection()
    assert active is None


def test_delete_active_connection_clears_active(
    credential_storage: CredentialStorage, sample_connection: DatabaseConnectionConfig
):
    """Test that deleting the active connection clears the active ID."""
    saved = credential_storage.save_connection(sample_connection)
    credential_storage.set_active_connection(saved.id)

    credential_storage.delete_connection(saved.id)

    assert credential_storage.get_active_connection_id() is None


def test_generate_encryption_key():
    """Test generating a valid encryption key."""
    key = CredentialStorage.generate_encryption_key()

    # Verify it's a valid Fernet key
    Fernet(key.encode())


def test_encryption_roundtrip(
    temp_storage_path: str, encryption_key: str, sample_connection: DatabaseConnectionConfig
):
    """Test that credentials survive encryption/decryption roundtrip."""
    # Create first storage instance and save
    storage1 = CredentialStorage(temp_storage_path, encryption_key)
    saved = storage1.save_connection(sample_connection)

    # Create a new storage instance with the same path and key
    storage2 = CredentialStorage(temp_storage_path, encryption_key)

    # Verify the connection can be read with the password
    retrieved = storage2.get_connection_with_password(saved.id)

    assert retrieved.password == sample_connection.password
    assert retrieved.name == sample_connection.name
    assert retrieved.host == sample_connection.host


def test_multiple_connections(credential_storage: CredentialStorage):
    """Test managing multiple connections."""
    configs = [
        DatabaseConnectionConfig(
            name=f"Connection {i}",
            host=f"host{i}",
            port=5432 + i,
            database=f"db{i}",
            username=f"user{i}",
            password=f"pass{i}",
            ssl_mode="disable",
        )
        for i in range(5)
    ]

    saved_ids = []
    for config in configs:
        saved = credential_storage.save_connection(config)
        saved_ids.append(saved.id)

    connections = credential_storage.list_connections()
    assert len(connections) == 5

    # Delete middle connection
    credential_storage.delete_connection(saved_ids[2])

    connections = credential_storage.list_connections()
    assert len(connections) == 4
