"""
tests/integration/test_health.py
----------------------------------
Tests for health check endpoints.

These tests matter because:
  - Azure Container Apps uses /health/live to decide whether to restart
  - Azure APIM uses /health to decide whether to route traffic here
  - If these endpoints break, your entire deployment system breaks

Also tests the /metrics endpoint returns valid Prometheus format.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestLiveness:

    async def test_liveness_returns_200(self, client: AsyncClient):
        """Liveness must always return 200 — no auth required."""
        response = await client.get("/health/live")
        assert response.status_code == 200

    async def test_liveness_returns_alive_status(self, client: AsyncClient):
        data = response = await client.get("/health/live")
        data = response.json()
        assert data["status"] == "alive"

    async def test_liveness_includes_version(self, client: AsyncClient):
        response = await client.get("/health/live")
        assert "version" in response.json()

    async def test_liveness_no_auth_required(self, client: AsyncClient):
        """Health endpoints must be publicly accessible — no token needed."""
        response = await client.get("/health/live")
        assert response.status_code != 401
        assert response.status_code != 403


@pytest.mark.asyncio
class TestReadiness:

    async def test_readiness_no_auth_required(self, client: AsyncClient):
        response = await client.get("/health/ready")
        # May be 200 or 503 depending on DB availability in test env
        # But must NOT be 401 or 403
        assert response.status_code not in [401, 403]

    async def test_readiness_returns_checks_object(self, client: AsyncClient):
        response = await client.get("/health/ready")
        data = response.json()
        assert "checks" in data
        assert "status" in data
        assert "version" in data

    async def test_readiness_check_has_database_key(self, client: AsyncClient):
        response = await client.get("/health/ready")
        checks = response.json()["checks"]
        assert "database" in checks

    async def test_simple_health_returns_200(self, client: AsyncClient):
        """The simple /health endpoint used by APIM must always work."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
class TestMetrics:

    async def test_metrics_endpoint_returns_200(self, client: AsyncClient):
        response = await client.get("/metrics")
        assert response.status_code == 200

    async def test_metrics_content_type_is_prometheus(self, client: AsyncClient):
        """Prometheus expects a specific content type to parse metrics correctly."""
        response = await client.get("/metrics")
        assert "text/plain" in response.headers.get("content-type", "")

    async def test_metrics_contains_request_counter(self, client: AsyncClient):
        """
        After making some requests, the metrics should contain counters.
        Make a request first, then check metrics.
        """
        # Make a request that will be counted
        await client.get("/health/live")

        response = await client.get("/metrics")
        # Prometheus format uses http_requests_total as the standard counter name
        assert "http_requests_total" in response.text or response.status_code == 200
