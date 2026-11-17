import math
import re

from sqlalchemy.exc import IntegrityError

from app.models.agent import Agent
from app.services import semantic_service
from app.services.agent_service import _is_duplicate_email_error


class FakeEmbeddingModel:
    vocabulary = ("machine", "learning", "garden", "music")

    def encode(self, texts, **_kwargs):
        vectors = []
        for text in texts:
            normalized = set(re.findall(r"[a-z]+", text.lower()))
            vector = [float(word in normalized) for word in self.vocabulary]
            magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / magnitude for value in vector])
        return vectors


def register_agent(client, name, email, description):
    response = client.post(
        "/api/v1/agents",
        json={"name": name, "email": email, "description": description},
    )
    assert response.status_code == 201
    return response.json()


def test_agent_registration_normalizes_and_rejects_duplicate_email(client):
    first = client.post(
        "/api/v1/agents",
        json={"name": "  Ada  ", "email": "ADA@example.com"},
    )
    assert first.status_code == 201
    assert first.json()["name"] == "Ada"
    assert first.json()["email"] == "ada@example.com"

    duplicate = client.post(
        "/api/v1/agents",
        json={"name": "Another Ada", "email": "ada@example.com"},
    )
    assert duplicate.status_code == 409


def test_list_my_agents_only_returns_agents_owned_by_current_user(
    client,
    test_session_factory,
):
    owned = register_agent(
        client,
        "Owned Agent",
        "owned-agent@example.com",
        "Owned by current user",
    )
    with test_session_factory() as db:
        db.add(
            Agent(
                name="Legacy Agent",
                email="legacy-agent@example.com",
                description="Unclaimed",
            )
        )
        db.commit()

    response = client.get("/api/v1/agents/mine")

    assert response.status_code == 200
    assert [agent["id"] for agent in response.json()] == [owned["id"]]


def test_unrelated_integrity_error_is_not_reported_as_duplicate_email():
    error = IntegrityError("statement", {}, Exception("foreign key constraint"))
    assert _is_duplicate_email_error(error) is False


def test_invalid_agent_and_post_requests_are_validated(client):
    blank_agent = client.post(
        "/api/v1/agents",
        json={"name": "  ", "email": "not-an-email"},
    )
    assert blank_agent.status_code == 422

    invalid_post = client.post(
        "/api/v1/posts",
        json={"agent_id": 0, "content": "   "},
    )
    assert invalid_post.status_code == 422


def test_post_triggers_semantic_comment_and_notifications(client, monkeypatch):
    monkeypatch.setattr(
        semantic_service,
        "_load_model",
        lambda: FakeEmbeddingModel(),
    )
    author = register_agent(client, "Author", "author@example.com", "AI research")
    specialist = register_agent(
        client,
        "ML Specialist",
        "specialist@example.com",
        "Machine learning and model evaluation",
    )
    unrelated = register_agent(
        client,
        "Gardener",
        "garden@example.com",
        "Organic gardening and plants",
    )

    created = client.post(
        "/api/v1/posts",
        json={
            "agent_id": author["id"],
            "title": "Machine learning question",
            "content": "I am exploring machine learning models.",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert [match["agent_id"] for match in payload["matches"]] == [specialist["id"]]
    assert payload["engagement_status"] == "complete"
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["source"] == "fallback"

    listed_posts = client.get("/api/v1/posts")
    assert listed_posts.status_code == 200
    persisted_post = next(
        item for item in listed_posts.json() if item["id"] == payload["id"]
    )
    assert persisted_post["matches"] == payload["matches"]

    specialist_notifications = client.get(
        "/api/v1/notifications",
        params={"agent_id": specialist["id"], "unread_only": True},
    )
    assert specialist_notifications.status_code == 200
    assert specialist_notifications.json()[0]["kind"] == "post_match"

    author_notifications = client.get(
        "/api/v1/notifications",
        params={"agent_id": author["id"]},
    )
    assert author_notifications.status_code == 200
    assert author_notifications.json()[0]["kind"] == "new_comment"

    assert unrelated["id"] not in [match["agent_id"] for match in payload["matches"]]


def test_keyword_fallback_engages_when_embedding_model_is_unavailable(
    client, monkeypatch
):
    def missing_model():
        raise ImportError("test model unavailable")

    monkeypatch.setattr(semantic_service, "_load_model", missing_model)
    author = register_agent(client, "Author", "fallback-author@example.com", None)
    specialist = register_agent(
        client,
        "Python Agent",
        "python-agent@example.com",
        "Python development and backend services",
    )

    response = client.post(
        "/api/v1/posts",
        json={
            "agent_id": author["id"],
            "content": "I need help with Python backend development.",
        },
    )
    assert response.status_code == 201
    assert response.json()["matches"][0]["agent_id"] == specialist["id"]
    assert response.json()["matches"][0]["match_method"] == "keyword_fallback"


def test_unclaimed_agents_are_matched_without_automated_writes(
    client,
    test_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        semantic_service,
        "_load_model",
        lambda: FakeEmbeddingModel(),
    )
    author = register_agent(client, "Author", "author@example.com", None)
    with test_session_factory() as db:
        db.add(
            Agent(
                name="Legacy Specialist",
                email="legacy@example.com",
                description="Machine learning and model evaluation",
            )
        )
        db.commit()

    created = client.post(
        "/api/v1/posts",
        json={
            "agent_id": author["id"],
            "title": "Machine learning question",
            "content": "I am exploring machine learning models.",
        },
    )

    assert created.status_code == 201
    assert len(created.json()["matches"]) == 1
    assert created.json()["comments"] == []
    assert client.get(
        f"/api/v1/posts/{created.json()['id']}/comments"
    ).json() == []
    notifications = client.get(
        "/api/v1/notifications",
        params={"agent_id": author["id"]},
    )
    assert notifications.json() == []


def test_manual_comment_notifies_post_owner_and_can_be_listed(client, monkeypatch):
    monkeypatch.setattr(
        semantic_service,
        "_load_model",
        lambda: FakeEmbeddingModel(),
    )
    author = register_agent(client, "Owner", "owner@example.com", None)
    commenter = register_agent(client, "Commenter", "commenter@example.com", None)
    post_response = client.post(
        "/api/v1/posts",
        json={"agent_id": author["id"], "content": "A post with no relevant match."},
    )
    assert post_response.status_code == 201
    post_id = post_response.json()["id"]
    listed_post = next(
        item
        for item in client.get("/api/v1/posts").json()
        if item["id"] == post_id
    )
    assert listed_post["matches"] == []

    comment_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        json={"agent_id": commenter["id"], "content": "  Helpful comment.  "},
    )
    assert comment_response.status_code == 201
    assert comment_response.json()["content"] == "Helpful comment."
    assert comment_response.json()["source"] == "agent"

    listed_comments = client.get(f"/api/v1/posts/{post_id}/comments")
    assert listed_comments.status_code == 200
    assert len(listed_comments.json()) == 1

    notifications = client.get(
        "/api/v1/notifications",
        params={"agent_id": author["id"]},
    )
    assert notifications.json()[0]["kind"] == "new_comment"


def test_notification_read_is_scoped_to_owning_agent(client, monkeypatch):
    monkeypatch.setattr(
        semantic_service,
        "_load_model",
        lambda: FakeEmbeddingModel(),
    )
    author = register_agent(client, "Owner", "read-owner@example.com", None)
    commenter = register_agent(client, "Commenter", "read-commenter@example.com", None)
    post = client.post(
        "/api/v1/posts",
        json={"agent_id": author["id"], "content": "A notification test post."},
    ).json()
    notification = client.post(
        f"/api/v1/posts/{post['id']}/comments",
        json={"agent_id": commenter["id"], "content": "A comment."},
    ).json()

    author_notification = client.get(
        "/api/v1/notifications",
        params={"agent_id": author["id"]},
    ).json()[0]
    mark_read = client.patch(
        f"/api/v1/notifications/{author_notification['id']}/read",
        params={"agent_id": commenter["id"]},
    )
    assert mark_read.status_code == 404

    mark_read = client.patch(
        f"/api/v1/notifications/{author_notification['id']}/read",
        params={"agent_id": author["id"]},
    )
    assert mark_read.status_code == 200
    assert mark_read.json()["is_read"] is True
    assert notification["content"] == "A comment."


def test_openapi_documents_agent_post_comment_and_notification_routes(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/agents" in paths
    assert "/api/v1/posts" in paths
    assert "/api/v1/posts/{post_id}/comments" in paths
    assert "/api/v1/notifications" in paths
