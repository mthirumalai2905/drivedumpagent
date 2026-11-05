import httpx
import pytest

from app.core.errors import GoogleAuthError, IntegrationError
from app.integrations.deepseek import DeepSeekClient
from app.integrations.google_auth import GoogleAuth


@pytest.mark.asyncio
async def test_refresh_token_success_and_invalid_grant_are_safe():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        body = request.content.decode()
        assert "refresh-token-sentinel" in body
        if calls["count"] == 1:
            return httpx.Response(
                200,
                json={"access_token": "ya29.access-token-sentinel", "expires_in": 3600},
            )
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        auth = GoogleAuth(
            client_id="client",
            client_secret="client-secret-sentinel",
            refresh_token="refresh-token-sentinel",
            http=http,
        )
        token = await auth.get_access_token()
        assert token == "ya29.access-token-sentinel"
        auth.invalidate()
        with pytest.raises(GoogleAuthError) as caught:
            await auth.get_access_token(force=True)
    message = str(caught.value)
    assert "7 days" in message
    assert "refresh-token-sentinel" not in message
    assert "client-secret-sentinel" not in message
    assert "ya29.access-token-sentinel" not in message


@pytest.mark.asyncio
async def test_deepseek_verifies_model_and_parses_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer deepseek-sentinel"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"Invoice","attachments":[{"filename":"a.pdf",'
                                '"description":"invoice","category":"invoice","attachment_type":"pdf"}]}'
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DeepSeekClient(
            api_key="deepseek-sentinel",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            http=http,
        )
        assert await client.verify_model() is True
        insight = await client.inspect_email(
            subject="Back Office",
            sender="a@example.com",
            body_excerpt="invoice",
            attachments=[("a.pdf", "application/pdf", 10)],
        )
    assert insight.summary == "Invoice"
    assert insight.attachments[0].category == "invoice"


@pytest.mark.asyncio
async def test_deepseek_error_does_not_include_the_api_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key deepseek-sentinel"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DeepSeekClient(
            api_key="deepseek-sentinel",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            http=http,
        )
        with pytest.raises(IntegrationError) as caught:
            await client.list_models()
    assert "deepseek-sentinel" not in str(caught.value)
    assert "rejected the API key" in str(caught.value)
