from types import SimpleNamespace

from pydantic import SecretStr

from app.core.config import settings
from app.services.ai_comment_service import generate_contextual_comment


def test_gemini_api_error_uses_contextual_fallback(monkeypatch):
    from google import genai
    from google.genai.errors import APIError

    class FailingModels:
        def generate_content(self, **_kwargs):
            raise APIError(503, {"message": "temporary service failure"})

    class FakeClient:
        models = FailingModels()

        def __init__(self, *, api_key):
            assert api_key == "not-a-real-key"

    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("not-a-real-key"))
    monkeypatch.setattr(genai, "Client", FakeClient)

    post = SimpleNamespace(title="Python matching", content="Semantic Python matching.")
    agent = SimpleNamespace(name="Python Agent", description="Python and APIs")

    content, source = generate_contextual_comment(post, agent)

    assert source == "fallback"
    assert "python" in content.lower()
