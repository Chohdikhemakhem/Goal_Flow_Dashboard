from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination
from app.db.session import get_db
from app.models.entities import Complaint, User
from app.models.enums import UserRole
from app.schemas.common import Page
from app.schemas.domain import ComplaintCreate, ComplaintRead, ComplaintStatusUpdate

router = APIRouter(prefix="/complaints", tags=["complaints"])


@router.get("", response_model=Page[ComplaintRead])
def list_complaints(
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit, offset = page
    query = select(Complaint)
    count_query = select(func.count(Complaint.id))
    if user.role != UserRole.ADMIN:
        query = query.where(Complaint.user_id == user.id)
        count_query = count_query.where(Complaint.user_id == user.id)
    return Page(
        items=db.scalars(query.order_by(Complaint.created_at.desc()).limit(limit).offset(offset)).all(),
        total=db.scalar(count_query) or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ComplaintRead)
def create_complaint(
    payload: ComplaintCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_complaint_forbidden", "message": "Admin receives complaints and cannot submit them"},
        )
    complaint = Complaint(user_id=user.id, **payload.model_dump())
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return complaint


@router.patch("/{complaint_id}/status", response_model=ComplaintRead)
def update_complaint_status(
    complaint_id: int,
    payload: ComplaintStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Admin only"})
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Complaint not found"})
    complaint.status = payload.status
    db.commit()
    db.refresh(complaint)
    return complaint
