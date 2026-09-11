from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Agency, Agent
from app.services.agent_identity import normalize_agent_name, normalized_agent_name_expression


def get_or_create_agency(db: Session, name: str) -> Agency:
    agency = db.scalar(select(Agency).where(Agency.name == name))
    if agency:
        return agency
    agency = Agency(name=name)
    db.add(agency)
    db.flush()
    return agency


def get_or_create_agent(db: Session, name: str, agency: Agency) -> Agent:
    normalized_name = normalize_agent_name(name)
    agent = db.scalar(
        select(Agent).where(
            normalized_agent_name_expression(Agent.name) == normalized_name.upper(),
            Agent.agency_id == agency.id,
        )
    )
    if agent:
        return agent
    agent = Agent(name=normalized_name or name.strip(), agency_id=agency.id)
    db.add(agent)
    db.flush()
    return agent
