import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, pagination, require_roles
from app.db.session import get_db
from app.models.entities import User
from app.models.enums import ImportBatchType, UserRole
from app.schemas.common import Message, Page
from app.schemas.imports import (
    ImportBatchRead,
    ImportResult,
    SnapshotDeleteRequest,
    SnapshotDeleteResult,
)
from app.schemas.restructured import (
    PendingRestructuredContractRead,
    PendingRestructuredContractSaveResult,
    PendingRestructuredContractUpdate,
    RestructuredImportLogRead,
    RestructuredImportResult,
    RestructuredSyncPreviewRead,
)
from app.services.support_audit import record_support_action
from app.services.imports import (
    HistoricalPeriodExistsError,
    delete_import_batch,
    delete_snapshot_batches,
    import_current_state,
    import_historical_month,
    import_loan_snapshot,
    list_import_batches,
)
from app.services.restructured import (
    get_restructured_import_log,
    import_restructured_contracts,
    list_pending_restructured_contracts,
    list_restructured_import_logs,
    preview_restructured_contract_sync,
    recalculate_restructured_results,
    resync_pending_restructured_contracts_from_all_mcr,
    get_pending_restructured_contracts_diagnostics,
    start_restructured_schedule_import_job,
    sync_pending_restructured_contracts_from_mcr_batch,
    update_pending_restructured_contract,
    validate_all_ready_pending_contracts,
    validate_pending_restructured_contract,
)
router = APIRouter(prefix="/imports", tags=["imports"])
IMPORT_OPERATOR_ROLES = [UserRole.SUPER_ADMIN, UserRole.SUPPORT]
logger = logging.getLogger(__name__)


def _import_result_audit_details(result: ImportResult) -> dict[str, str | int]:
    return {
        "rows_seen": result.rows_seen,
        "inserted": result.inserted,
        "updated": result.updated,
        "duplicates": result.duplicates,
        "metrics_recalculated": result.metrics_recalculated,
        "snapshot_date": str(result.snapshot_date),
        "import_batch_id": result.import_batch.id,
    }


def _record_import_audit_safe(
    db: Session,
    *,
    actor: User,
    action: str,
    outcome: str,
    request: Request | None,
    target_label: str,
    details: dict | None,
) -> None:
    try:
        record_support_action(
            db,
            actor=actor,
            action=action,
            result=outcome,
            request=request,
            target_type="import",
            target_label=target_label,
            details=details,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Import audit logging failed action=%s actor_id=%s target_label=%s outcome=%s",
            action,
            getattr(actor, "id", None),
            target_label,
            outcome,
        )


def _refresh_restructured_calculations_safe(db: Session, result: ImportResult) -> None:
    """Resynchronise les credits restructures/consolides en attente avec le
    nouveau batch importe, puis recalcule leurs resultats.

    Declenche automatiquement apres CHAQUE import de fichier de credits
    (etat courant, historique, legacy), quel que soit le fichier importe,
    pour que les credits restructures/consolides restent a jour sans action
    manuelle. Un echec ici ne doit jamais faire echouer l'import principal :
    l'erreur est loguee et avalee.
    """
    import_batch = getattr(result, "import_batch", None)
    if import_batch is None:
        return
    try:
        sync_pending_restructured_contracts_from_mcr_batch(db, import_batch)
        recalculate_restructured_results(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Echec du recalcul automatique des credits restructures/consolides "
            "apres import batch_id=%s",
            import_batch.id,
        )


def _validate_excel_file(file: UploadFile) -> None:
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_file", "message": "Upload an Excel .xlsx or .xls file"},
        )


def _validate_schedule_file(file: UploadFile) -> None:
    if not file.filename or not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_file",
                "message": "Upload a .xlsx, .xls or .csv schedule file",
            },
        )


@router.get(
    "/batches",
    response_model=list[ImportBatchRead],
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def get_import_batches(db: Session = Depends(get_db)):
    return list_import_batches(db)


@router.post(
    "/snapshots/delete",
    response_model=SnapshotDeleteResult,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def delete_snapshots_endpoint(
    payload: SnapshotDeleteRequest,
    db: Session = Depends(get_db),
):
    try:
        deleted_batch_ids, deleted_rows = delete_snapshot_batches(db, payload.batch_ids)
        return SnapshotDeleteResult(
            deleted_batch_ids=deleted_batch_ids,
            deleted_rows=deleted_rows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "snapshot_delete_error", "message": str(exc)},
        ) from exc


@router.post(
    "/current-state",
    response_model=ImportResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def import_current_state_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _validate_excel_file(file)
    try:
        result = import_current_state(db, await file.read(), file.filename or "current-state.xlsx")
        _refresh_restructured_calculations_safe(db, result)
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_current_state",
            outcome="success",
            request=request,
            target_label=file.filename or "current-state.xlsx",
            details=_import_result_audit_details(result),
        )
        return result
    except ValueError as exc:
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_current_state",
            outcome="error",
            request=request,
            target_label=file.filename or "current-state.xlsx",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_validation_error", "message": str(exc)},
        ) from exc


@router.post(
    "/historical",
    response_model=ImportResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def import_historical_endpoint(
    period: str = Form(...),
    replace_existing: bool = Form(default=False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _validate_excel_file(file)
    try:
        result = import_historical_month(
            db=db,
            content=await file.read(),
            file_name=file.filename or "historical-month.xlsx",
            period=period,
            replace_existing=replace_existing,
        )
        _refresh_restructured_calculations_safe(db, result)
        success_details = _import_result_audit_details(result)
        success_details.update({"period": period, "replace_existing": bool(replace_existing)})
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_historical_month",
            outcome="success",
            request=request,
            target_label=file.filename or "historical-month.xlsx",
            details=success_details,
        )
        return result
    except HistoricalPeriodExistsError as exc:
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_historical_month",
            outcome="error",
            request=request,
            target_label=file.filename or "historical-month.xlsx",
            details={"period": period, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "historical_period_exists",
                "message": f"Un fichier existe deja pour la periode {exc.period}",
                "period": exc.period,
                "existing_batch": ImportBatchRead.model_validate(exc.existing_batch).model_dump(
                    mode="json"
                ),
            },
        ) from exc
    except ValueError as exc:
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_historical_month",
            outcome="error",
            request=request,
            target_label=file.filename or "historical-month.xlsx",
            details={"period": period, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_validation_error", "message": str(exc)},
        ) from exc


@router.post(
    "/loans",
    response_model=ImportResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def import_loans_legacy(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    # Legacy endpoint preserved for backward compatibility with older frontend versions.
    _validate_excel_file(file)
    try:
        result = import_loan_snapshot(db, await file.read(), file.filename or "legacy-upload.xlsx")
        _refresh_restructured_calculations_safe(db, result)
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_legacy_loans",
            outcome="success",
            request=request,
            target_label=file.filename or "legacy-upload.xlsx",
            details=_import_result_audit_details(result),
        )
        return result
    except ValueError as exc:
        _record_import_audit_safe(
            db,
            actor=actor,
            action="import_legacy_loans",
            outcome="error",
            request=request,
            target_label=file.filename or "legacy-upload.xlsx",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "import_validation_error", "message": str(exc)},
        ) from exc


@router.delete(
    "/batches/{batch_id}",
    response_model=Message,
    dependencies=[Depends(require_roles([UserRole.SUPER_ADMIN]))],
)
def delete_import_batch_endpoint(batch_id: int, db: Session = Depends(get_db)):
    try:
        batch_type, snapshot_date, deleted_rows = delete_import_batch(
            db=db,
            batch_id=batch_id,
            allowed_types={ImportBatchType.SNAPSHOT, ImportBatchType.HISTORICAL_MONTH},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "delete_import_batch_error", "message": str(exc)},
        ) from exc
    return Message(
        message=(
            f"Import {batch_type} du {snapshot_date} supprime. "
            f"{deleted_rows} ligne(s) MCR supprimee(s)."
        )
    )


@router.get(
    "/restructured-logs",
    response_model=list[RestructuredImportLogRead],
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def get_restructured_import_logs(
    import_type: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    return list_restructured_import_logs(db, import_type=import_type, limit=limit)


@router.get(
    "/restructured-logs/{log_id}",
    response_model=RestructuredImportLogRead,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def get_restructured_import_log_endpoint(log_id: int, db: Session = Depends(get_db)):
    log = get_restructured_import_log(db, log_id)
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "restructured_import_log_not_found", "message": "Import introuvable"},
        )
    return log


@router.post(
    "/restructured-contracts/preview",
    response_model=RestructuredSyncPreviewRead,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def preview_restructured_contracts_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _validate_excel_file(file)
    try:
        logger.info(
            "Preview restructured contracts import started actor_id=%s role=%s file_name=%s",
            getattr(actor, "id", None),
            getattr(actor.role, "value", actor.role),
            file.filename,
        )
        result = preview_restructured_contract_sync(
            db,
            await file.read(),
            file.filename or "liste_restructures.xlsx",
        )
        record_support_action(
            db,
            actor=actor,
            action="preview_restructured_contract_sync",
            result="success",
            request=request,
            target_type="import",
            target_label=file.filename or "liste_restructures.xlsx",
            details={
                "rows": result.rows_seen,
                "existing_contracts": result.existing_contracts_count,
                "mcr_detected": result.detected_in_mcr_count,
                "delete_count": result.delete_count,
            },
        )
        db.commit()
        logger.info(
            "Preview restructured contracts import completed actor_id=%s file_name=%s rows=%s deletions=%s",
            getattr(actor, "id", None),
            file.filename,
            result.rows_seen,
            result.delete_count,
        )
        return result
    except ValueError as exc:
        db.rollback()
        record_support_action(
            db,
            actor=actor,
            action="preview_restructured_contract_sync",
            result="error",
            request=request,
            target_type="import",
            target_label=file.filename or "liste_restructures.xlsx",
            details={"error": str(exc)},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_contract_import_error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Preview restructured contracts import failed actor_id=%s file_name=%s",
            getattr(actor, "id", None),
            file.filename,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "restructured_contract_import_unexpected_error",
                "message": "Echec de l'import : erreur serveur inattendue pendant la previsualisation.",
            },
        ) from exc


@router.post(
    "/restructured-contracts",
    response_model=RestructuredImportResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def import_restructured_contracts_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _validate_excel_file(file)
    try:
        logger.info(
            "Restructured contracts import started actor_id=%s role=%s file_name=%s",
            getattr(actor, "id", None),
            getattr(actor.role, "value", actor.role),
            file.filename,
        )
        result = import_restructured_contracts(
            db,
            await file.read(),
            file.filename or "liste_restructures.xlsx",
        )
        record_support_action(
            db,
            actor=actor,
            action="import_restructured_contracts",
            result="success",
            request=request,
            target_type="import",
            target_label=file.filename or "liste_restructures.xlsx",
            details={
                "inserted": result.inserted,
                "updated": result.updated,
                "deleted": result.deleted,
                "kept_count": result.kept_count,
                "pending_cleanup_count": result.pending_cleanup_count,
                "rows": result.rows_seen,
            },
        )
        db.commit()
        logger.info(
            "Restructured contracts import completed actor_id=%s file_name=%s rows=%s inserted=%s updated=%s deleted=%s",
            getattr(actor, "id", None),
            file.filename,
            result.rows_seen,
            result.inserted,
            result.updated,
            result.deleted,
        )
        return result
    except ValueError as exc:
        db.rollback()
        record_support_action(
            db,
            actor=actor,
            action="import_restructured_contracts",
            result="error",
            request=request,
            target_type="import",
            target_label=file.filename or "liste_restructures.xlsx",
            details={"error": str(exc)},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_contract_import_error", "message": str(exc)},
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Restructured contracts import failed actor_id=%s file_name=%s",
            getattr(actor, "id", None),
            file.filename,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "restructured_contract_import_unexpected_error",
                "message": "Echec de l'import : erreur serveur inattendue pendant la synchronisation.",
            },
        ) from exc


@router.post(
    "/restructured-schedule",
    response_model=RestructuredImportLogRead,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
async def import_restructured_schedule_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    _validate_schedule_file(file)
    try:
        log = start_restructured_schedule_import_job(
            db,
            content=await file.read(),
            file_name=file.filename or "schedule.xlsx",
        )
        record_support_action(
            db,
            actor=actor,
            action="import_restructured_schedule",
            result="success",
            request=request,
            target_type="import_job",
            target_id=str(log.id),
            target_label=file.filename or "schedule.xlsx",
            details={"phase": log.phase, "status": log.status},
        )
        db.commit()
        return log
    except ValueError as exc:
        record_support_action(
            db,
            actor=actor,
            action="import_restructured_schedule",
            result="error",
            request=request,
            target_type="import",
            target_label=file.filename or "schedule.xlsx",
            details={"error": str(exc)},
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_schedule_import_error", "message": str(exc)},
        ) from exc


@router.get(
    "/restructured-pending",
    response_model=Page[PendingRestructuredContractRead],
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def get_restructured_pending_contracts(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: tuple[int, int] = Depends(pagination),
    db: Session = Depends(get_db),
):
    limit, offset = page
    if q is not None:
        q = q.strip()
        if q == "" or q == "undefined" or q == "null":
            q = None
    if status_filter is not None:
        status_filter = status_filter.strip()
        if status_filter == "" or status_filter == "undefined" or status_filter == "null":
            status_filter = None
    return list_pending_restructured_contracts(
        db,
        q=q,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/restructured-pending/{pending_id}",
    response_model=PendingRestructuredContractRead,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def update_restructured_pending_contract_endpoint(
    pending_id: int,
    payload: PendingRestructuredContractUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        row = update_pending_restructured_contract(db, pending_id, payload)
        record_support_action(
            db,
            actor=actor,
            action="update_pending_restructured_contract",
            result="success",
            request=request,
            target_type="pending_restructured_contract",
            target_id=str(pending_id),
            target_label=row.contract_no,
        )
        db.commit()
        return row
    except ValueError as exc:
        record_support_action(
            db,
            actor=actor,
            action="update_pending_restructured_contract",
            result="error",
            request=request,
            target_type="pending_restructured_contract",
            target_id=str(pending_id),
            details={"error": str(exc)},
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_pending_update_error", "message": str(exc)},
        ) from exc


@router.post(
    "/restructured-pending/{pending_id}/validate",
    response_model=PendingRestructuredContractSaveResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def validate_restructured_pending_contract_endpoint(
    pending_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        result = validate_pending_restructured_contract(db, pending_id, actor=user)
        record_support_action(
            db,
            actor=user,
            action="validate_pending_restructured_contract",
            result="success",
            request=request,
            target_type="pending_restructured_contract",
            target_id=str(pending_id),
            target_label=result.contract.contract_no,
        )
        db.commit()
        return result
    except ValueError as exc:
        record_support_action(
            db,
            actor=user,
            action="validate_pending_restructured_contract",
            result="error",
            request=request,
            target_type="pending_restructured_contract",
            target_id=str(pending_id),
            details={"error": str(exc)},
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_pending_validate_error", "message": str(exc)},
        ) from exc


@router.post(
    "/restructured-pending/validate-all",
    response_model=PendingRestructuredContractSaveResult,
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def validate_all_restructured_pending_contracts_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    request: Request = None,
):
    try:
        result = validate_all_ready_pending_contracts(db, actor=user)
        record_support_action(
            db,
            actor=user,
            action="validate_all_pending_restructured_contracts",
            result="success",
            request=request,
            target_type="pending_restructured_contract_batch",
            target_label="validate_all",
            details={"saved_count": result.saved_count, "remaining_count": result.remaining_count},
        )
        db.commit()
        return result
    except ValueError as exc:
        record_support_action(
            db,
            actor=user,
            action="validate_all_pending_restructured_contracts",
            result="error",
            request=request,
            target_type="pending_restructured_contract_batch",
            target_label="validate_all",
            details={"error": str(exc)},
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_pending_validate_all_error", "message": str(exc)},
        ) from exc


@router.post(
    "/restructured-pending/resync",
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def resync_restructured_pending_contracts_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    request: Request = None,
):
    """
    Force a full re-scan of every MCR row in `loans_raw` to rebuild the
    'Contrats à compléter' list. Safe to re-run: idempotent.
    """
    try:
        summary = resync_pending_restructured_contracts_from_all_mcr(db)
        db.commit()
        record_support_action(
            db,
            actor=user,
            action="resync_restructured_pending_contracts",
            result="success",
            request=request,
            target_type="pending_restructured_contract_batch",
            target_label="resync_all_mcr",
            details=summary,
        )
        db.commit()
        return summary
    except Exception as exc:
        db.rollback()
        record_support_action(
            db,
            actor=user,
            action="resync_restructured_pending_contracts",
            result="error",
            request=request,
            target_type="pending_restructured_contract_batch",
            target_label="resync_all_mcr",
            details={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "restructured_pending_resync_error", "message": str(exc)},
        ) from exc


@router.get(
    "/restructured-pending/diagnostics",
    dependencies=[Depends(require_roles(IMPORT_OPERATOR_ROLES))],
)
def get_restructured_pending_contracts_diagnostics_endpoint(
    db: Session = Depends(get_db),
):
    """
    Returns a stage-by-stage count to help diagnose why the
    'Contrats à compléter' list might be empty:
      A. loans_total
      B. loans_with_category_desc
      C. loans_restructured_distinct / loans_consolidated_distinct
      D. official_restructured_contracts
      E. pending_restructured_contracts
    """
    return get_pending_restructured_contracts_diagnostics(db)
