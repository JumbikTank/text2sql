"""Tests for connection service."""

import pytest

from src.common.credentials import CredentialStorage
from src.common.dto import DatabaseConnectionConfig
from src.common.settings import Settings
from src.services.connection_service import (
    ConnectionService,
    ConnectionServiceError,
    InvalidIdentifierError,
    _validate_identifier,
)


def test_validate_identifier_valid():
    """Test valid identifier names pass validation."""
    valid_names = ["users", "user_table", "_private", "Table1", "a", "ABC"]
    for name in valid_names:
        _validate_identifier(name)  # Should not raise


def test_validate_identifier_invalid():
    """Test invalid identifier names fail validation."""
    invalid_names = [
        "1table",  # starts with number
        "table-name",  # contains hyphen
        "table.name",  # contains dot
        "table name",  # contains space
        "table;drop",  # SQL injection attempt
        "",  # empty string
    ]
    for name in invalid_names:
        with pytest.raises(InvalidIdentifierError):
            _validate_identifier(name)


def test_connection_service_init(test_settings: Settings, credential_storage: CredentialStorage):
    """Test ConnectionService initialization."""
    service = ConnectionService(test_settings, credential_storage)
    assert service.settings == test_settings


def test_list_connections_empty(test_settings: Settings, credential_storage: CredentialStorage):
    """Test listing connections when none exist."""
    service = ConnectionService(test_settings, credential_storage)

    result = service.list_connections()

    assert len(result.connections) == 0
    assert result.active_connection_id is None


def test_save_and_list_connections(
    test_settings: Settings,
    credential_storage: CredentialStorage,
    sample_connection: DatabaseConnectionConfig,
):
    """Test saving and listing connections."""
    service = ConnectionService(test_settings, credential_storage)

    saved = service.save_connection(sample_connection)
    result = service.list_connections()

    assert len(result.connections) == 1
    assert result.connections[0].name == sample_connection.name


def test_get_connection(
    test_settings: Settings,
    credential_storage: CredentialStorage,
    sample_connection: DatabaseConnectionConfig,
):
    """Test getting a specific connection."""
    service = ConnectionService(test_settings, credential_storage)
    saved = service.save_connection(sample_connection)

    retrieved = service.get_connection(saved.id)

    assert retrieved.id == saved.id
    assert retrieved.name == sample_connection.name


def test_get_connection_not_found(test_settings: Settings, credential_storage: CredentialStorage):
    """Test getting a non-existent connection."""
    service = ConnectionService(test_settings, credential_storage)

    with pytest.raises(ConnectionServiceError) as exc_info:
        service.get_connection("non-existent")

    assert "not found" in str(exc_info.value).lower()


def test_update_connection(
    test_settings: Settings,
    credential_storage: CredentialStorage,
    sample_connection: DatabaseConnectionConfig,
):
    """Test updating a connection."""
    service = ConnectionService(test_settings, credential_storage)
    saved = service.save_connection(sample_connection)

    updated_config = DatabaseConnectionConfig(
        name="Updated Name",
        host="newhost",
        port=5433,
        database="newdb",
        username="newuser",
        password="newpass",
        ssl_mode="require",
    )

    updated = service.update_connection(saved.id, updated_config)

    assert updated.name == "Updated Name"
    assert updated.host == "newhost"


def test_delete_connection(
    test_settings: Settings,
    credential_storage: CredentialStorage,
    sample_connection: DatabaseConnectionConfig,
):
    """Test deleting a connection."""
    service = ConnectionService(test_settings, credential_storage)
    saved = service.save_connection(sample_connection)

    service.delete_connection(saved.id)

    result = service.list_connections()
    assert len(result.connections) == 0


def test_set_active_connection(
    test_settings: Settings,
    credential_storage: CredentialStorage,
    sample_connection: DatabaseConnectionConfig,
):
    """Test setting the active connection."""
    service = ConnectionService(test_settings, credential_storage)
    saved = service.save_connection(sample_connection)

    service.set_active_connection(saved.id)

    result = service.list_connections()
    assert result.active_connection_id == saved.id


def test_set_active_connection_not_found(
    test_settings: Settings, credential_storage: CredentialStorage
):
    """Test setting a non-existent connection as active."""
    service = ConnectionService(test_settings, credential_storage)

    with pytest.raises(ConnectionServiceError) as exc_info:
        service.set_active_connection("non-existent")

    assert "not found" in str(exc_info.value).lower()


def test_no_active_connection_error(
    test_settings: Settings, credential_storage: CredentialStorage
):
    """Test error when no active connection is set."""
    service = ConnectionService(test_settings, credential_storage)

    with pytest.raises(ConnectionServiceError) as exc_info:
        service._get_active_connection()

    assert "no active connection" in str(exc_info.value).lower()


def test_connection_service_without_credential_storage(test_settings: Settings):
    """Test ConnectionService creates its own credential storage when not provided."""
    service = ConnectionService(test_settings)

    # This should work because test_settings has credential_encryption_key set
    result = service.list_connections()
    assert len(result.connections) == 0


def test_connection_service_missing_encryption_key():
    """Test ConnectionService raises error when encryption key is missing."""
    settings = Settings(
        username="test",
        password="test",
        db_host="localhost",
        database="testdb",
        credential_storage_path="/tmp/test.enc",
        credential_encryption_key=None,
    )
    service = ConnectionService(settings)

    with pytest.raises(ConnectionServiceError) as exc_info:
        service.list_connections()

    assert "CREDENTIAL_ENCRYPTION_KEY" in str(exc_info.value)
