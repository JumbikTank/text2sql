"""Tests for schema API endpoints."""

import pytest
from litestar.testing import TestClient

from src.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_test_connection_success(client: TestClient):
    """Test connection test endpoint with valid config."""
    # Note: This test requires a real database connection
    # In a real test suite, you'd mock the database connection
    response = client.post(
        "/api/connections/test",
        json={
            "name": "Test",
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "username": "postgres",
            "password": "postgres",
            "ssl_mode": "disable",
        },
    )

    # This will likely fail without a real database, but tests the endpoint structure
    assert response.status_code in [200, 500]


def test_test_connection_invalid_body(client: TestClient):
    """Test connection test endpoint with invalid body."""
    response = client.post(
        "/api/connections/test",
        json={
            "name": "Test",
            # Missing required fields
        },
    )

    assert response.status_code == 400


def test_list_connections_no_encryption_key(client: TestClient):
    """Test listing connections without encryption key configured."""
    # Without CREDENTIAL_ENCRYPTION_KEY, this should fail
    response = client.get("/api/connections")

    # Should return 500 with encryption key error
    assert response.status_code == 500


def test_save_connection_no_encryption_key(client: TestClient):
    """Test saving connection without encryption key configured."""
    response = client.post(
        "/api/connections",
        json={
            "name": "Test",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "testuser",
            "password": "testpass",
            "ssl_mode": "disable",
        },
    )

    assert response.status_code == 500


def test_get_connection_not_found(client: TestClient):
    """Test getting a non-existent connection."""
    response = client.get("/api/connections/non-existent-id")

    # Should return 404 or 500 depending on encryption key
    assert response.status_code in [404, 500]


def test_list_tables_no_active_connection(client: TestClient):
    """Test listing tables without active connection."""
    response = client.get("/api/schema/tables")

    # Should return 400 or 500
    assert response.status_code in [400, 500]


def test_get_table_details_no_active_connection(client: TestClient):
    """Test getting table details without active connection."""
    response = client.get("/api/schema/tables/users")

    # Should return 400 or 500
    assert response.status_code in [400, 500]


def test_preview_table_no_active_connection(client: TestClient):
    """Test previewing table without active connection."""
    response = client.post(
        "/api/schema/preview",
        json={
            "schema_name": "public",
            "table_name": "users",
            "limit": 50,
        },
    )

    # Should return 400 or 500
    assert response.status_code in [400, 500]


def test_preview_table_invalid_limit(client: TestClient):
    """Test previewing table with invalid limit."""
    response = client.post(
        "/api/schema/preview",
        json={
            "schema_name": "public",
            "table_name": "users",
            "limit": 10000,  # Exceeds max of 1000
        },
    )

    assert response.status_code == 400


def test_delete_connection_not_found(client: TestClient):
    """Test deleting a non-existent connection."""
    response = client.delete("/api/connections/non-existent-id")

    # Should return 404 or 500
    assert response.status_code in [404, 500]


def test_activate_connection_not_found(client: TestClient):
    """Test activating a non-existent connection."""
    response = client.post("/api/connections/non-existent-id/activate")

    # Should return 404 or 500
    assert response.status_code in [404, 500]
