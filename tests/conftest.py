"""Shared test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from src.common.credentials import CredentialStorage
from src.common.dto import DatabaseConnectionConfig
from src.common.settings import Settings


@pytest.fixture
def encryption_key() -> str:
    """Generate a test encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def temp_storage_path() -> str:
    """Create a temporary file path for credential storage."""
    with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
        yield f.name
    # Cleanup
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture
def credential_storage(temp_storage_path: str, encryption_key: str) -> CredentialStorage:
    """Create a CredentialStorage instance for testing."""
    return CredentialStorage(temp_storage_path, encryption_key)


@pytest.fixture
def sample_connection() -> DatabaseConnectionConfig:
    """Create a sample database connection config."""
    return DatabaseConnectionConfig(
        name="Test Connection",
        host="localhost",
        port=5432,
        database="testdb",
        username="testuser",
        password="testpassword",
        ssl_mode="disable",
    )


@pytest.fixture
def test_settings(temp_storage_path: str, encryption_key: str) -> Settings:
    """Create test settings with credential storage configured."""
    os.environ["USERNAME"] = "testuser"
    os.environ["PASSWORD"] = "testpass"
    os.environ["DB_HOST"] = "localhost"
    os.environ["DATABASE"] = "testdb"
    os.environ["CREDENTIAL_STORAGE_PATH"] = temp_storage_path
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = encryption_key

    return Settings(
        username="testuser",
        password="testpass",
        db_host="localhost",
        database="testdb",
        credential_storage_path=temp_storage_path,
        credential_encryption_key=encryption_key,
    )
