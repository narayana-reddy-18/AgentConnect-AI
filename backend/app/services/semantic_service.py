import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from requests.exceptions import RequestException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent import Agent
from app.models.post import Post

logger = logging.getLogger(__name__)

_WORD_PATTERN = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "but",
    "for",
    "from",
    "have",
    "into",
    "its",
    "more",
    "not",
    "our",
    "that",
    "the",
    "their",
    "them",
    "this",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class AgentMatch:
    agent: Agent
    score: float
    method: str


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def _terms(text: str) -> set[str]:
    return {
        word.lower()
        for word in _WORD_PATTERN.findall(text)
        if word.lower() not in _STOP_WORDS
    }


def _keyword_matches(query: str, agents: list[Agent]) -> list[AgentMatch]:
    query_terms = _terms(query)
    if not query_terms:
        return []

    matches = []
    for agent in agents:
        profile = f"{agent.name} {agent.description or ''}"
        profile_terms = _terms(profile)
        score = len(query_terms & profile_terms) / len(query_terms)
        if score >= settings.semantic_match_threshold:
            matches.append(AgentMatch(agent, score, "keyword_fallback"))
    return sorted(matches, key=lambda match: (-match.score, match.agent.id))[
        : settings.semantic_match_limit
    ]


def find_relevant_agents(db: Session, post: Post) -> list[AgentMatch]:
    agents = list(
        db.scalars(
            select(Agent)
            .where(Agent.id != post.agent_id)
            .order_by(Agent.id)
        ).all()
    )
    if not agents:
        return []

    query = " ".join(part for part in (post.title, post.content) if part)
    profiles = [f"{agent.name}. {agent.description or ''}" for agent in agents]

    try:
        model = _load_model()
        embeddings = model.encode(
            [query, *profiles],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except (
        ImportError,
        OSError,
        RequestException,
        RuntimeError,
        ValueError,
    ) as exc:
        logger.warning(
            "Sentence Transformer matching unavailable; using keyword matching: %s",
            exc,
        )
        return _keyword_matches(query, agents)

    query_embedding = embeddings[0]
    matches = []
    for agent, embedding in zip(agents, embeddings[1:], strict=True):
        score = float(sum(float(left) * float(right) for left, right in zip(
            query_embedding, embedding, strict=True
        )))
        if score >= settings.semantic_match_threshold:
            matches.append(AgentMatch(agent, score, "sentence_transformers"))

    return sorted(matches, key=lambda match: (-match.score, match.agent.id))[
        : settings.semantic_match_limit
    ]
