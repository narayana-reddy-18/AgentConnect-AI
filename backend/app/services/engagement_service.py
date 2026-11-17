from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.models.post_match import PostMatch
from app.schemas.post import AgentMatchRead
from app.services.ai_comment_service import generate_contextual_comment
from app.services.semantic_service import find_relevant_agents


@dataclass(frozen=True)
class EngagementResult:
    matches: list[AgentMatchRead]
    status: str


def create_automated_engagement(db: Session, post: Post) -> EngagementResult:
    ranked_agents = find_relevant_agents(db, post)
    if not ranked_agents:
        return EngagementResult(matches=[], status="no_matches")

    match_reads = []
    for match in ranked_agents:
        db.add(
            PostMatch(
                post_id=post.id,
                agent_id=match.agent.id,
                agent_name=match.agent.name,
                score=match.score,
                match_method=match.method,
            )
        )
        match_reads.append(
            AgentMatchRead(
                agent_id=match.agent.id,
                agent_name=match.agent.name,
                score=match.score,
                match_method=match.method,
            )
        )
        if match.agent.owner_user_id is None:
            continue

        comment_text, source = generate_contextual_comment(post, match.agent)
        comment = Comment(
            post_id=post.id,
            agent_id=match.agent.id,
            content=comment_text,
            source=source,
        )
        db.add(comment)
        db.flush()
        db.add(
            Notification(
                agent_id=match.agent.id,
                post_id=post.id,
                comment_id=comment.id,
                kind="post_match",
                message=f"A post matched {match.agent.name}'s profile.",
            )
        )
        db.add(
            Notification(
                agent_id=post.agent_id,
                post_id=post.id,
                comment_id=comment.id,
                kind="new_comment",
                message=f"{match.agent.name} commented on your post.",
            )
        )

    db.commit()
    db.refresh(post)
    return EngagementResult(matches=match_reads, status="complete")
