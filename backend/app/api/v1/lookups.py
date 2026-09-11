from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import ActivitySector, Agency, Agent, User
from app.models.enums import UserRole
from app.services.data_scope import get_user_data_scope
from app.services.selection import normalize_agency_ids
from app.services.portfolio_identity import matching_agent_ids_query, user_portfolio_identity_key
from app.schemas.common import Page
from app.schemas.domain import ActivitySectorRead, AgencyRead, AgentRead, FeatureFlagsRead

router = APIRouter(
    prefix="/lookups",
    tags=["lookups"],
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.COMMITTEE_MEMBER, UserRole.AGENCY_MANAGER, UserRole.PORTFOLIO_MANAGER]))],
)


@router.get("/features", response_model=FeatureFlagsRead)
def get_feature_flags():
    settings = get_settings()
    return FeatureFlagsRead(bonus_module_active=settings.bonus_module_active)


@router.get("/agencies", response_model=Page[AgencyRead])
def list_agencies(
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    scope = get_user_data_scope(user)
    query = select(Agency).order_by(Agency.name)
    count_query = select(func.count(Agency.id))
    if scope.agency_id is not None:
        query = query.where(Agency.id == scope.agency_id)
        count_query = count_query.where(Agency.id == scope.agency_id)
    return Page(
        items=db.scalars(query.limit(limit).offset(offset)).all(),
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/agents", response_model=Page[AgentRead])
def list_agents(
    agency_id: str | None = None,
    agency_ids: str | None = None,
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    scope = get_user_data_scope(user)
    query = select(Agent).order_by(Agent.name)
    count_query = select(func.count(Agent.id))
    effective_agency_ids = normalize_agency_ids(agency_id=agency_id, agency_ids=agency_ids)
    if scope.agency_id is not None:
        effective_agency_ids = [scope.agency_id]
    if effective_agency_ids:
        if len(effective_agency_ids) == 1:
            query = query.where(Agent.agency_id == effective_agency_ids[0])
            count_query = count_query.where(Agent.agency_id == effective_agency_ids[0])
        else:
            query = query.where(Agent.agency_id.in_(effective_agency_ids))
            count_query = count_query.where(Agent.agency_id.in_(effective_agency_ids))
    if scope.agent_id is not None:
        identity_key = user_portfolio_identity_key(db, user)
        if not identity_key:
            query = query.where(False)
            count_query = count_query.where(False)
        else:
            query = query.where(Agent.id.in_(matching_agent_ids_query(identity_key)))
            count_query = count_query.where(Agent.id.in_(matching_agent_ids_query(identity_key)))
    return Page(
        items=db.scalars(query.limit(limit).offset(offset)).all(),
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/sectors", response_model=list[ActivitySectorRead])
def list_sectors(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(select(ActivitySector).order_by(ActivitySector.name.asc())).all()
