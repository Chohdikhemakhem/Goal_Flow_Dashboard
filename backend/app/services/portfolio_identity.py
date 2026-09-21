from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Agent, User
from app.services.agent_identity import normalized_agent_name_expression, normalized_agent_name_key


def user_portfolio_identity_key(db: Session, user: User) -> str:
    if user.agent_id:
        agent = db.get(Agent, user.agent_id)
        if agent and agent.name:
            return normalized_agent_name_key(agent.name)
    return normalized_agent_name_key(user.full_name)


def agent_identity_filter(identity_key: str):
    if not identity_key:
        return None
    return normalized_agent_name_expression(Agent.name) == identity_key


def matching_agent_ids_query(identity_key: str):
    condition = agent_identity_filter(identity_key)
    if condition is None:
        return select(Agent.id).where(False)
    return select(Agent.id).where(condition)
