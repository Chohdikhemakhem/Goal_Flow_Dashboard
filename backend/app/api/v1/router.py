from fastapi import APIRouter

from app.api.v1 import auth, bonus, imports, lookups, metrics, par_reduction_targets, reports, restructured, taeg, targets, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(imports.router)
api_router.include_router(metrics.router)
api_router.include_router(targets.router)
api_router.include_router(par_reduction_targets.router)
api_router.include_router(users.router)
api_router.include_router(bonus.router)
api_router.include_router(lookups.router)
api_router.include_router(reports.router)
api_router.include_router(taeg.router)
api_router.include_router(restructured.router)
