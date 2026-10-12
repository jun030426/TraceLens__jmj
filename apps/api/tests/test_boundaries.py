import asyncio

import httpx
from lerny.main import create_app


async def check_readiness_boundary():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/health/live")).status_code == 200
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["sandbox"] == "disabled"


async def check_execution_boundary():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        capabilities = (await client.get("/api/v1/capabilities")).json()
        assert capabilities["code_execution"] is False
        response = await client.post(
            "/api/v1/episodes/test/runs",
            json={"language": "python", "source": "raise RuntimeError('must not run')"},
        )
        assert response.status_code == 404


def test_live_does_not_claim_learning_readiness():
    asyncio.run(check_readiness_boundary())


def test_no_student_code_execution_endpoint():
    asyncio.run(check_execution_boundary())
