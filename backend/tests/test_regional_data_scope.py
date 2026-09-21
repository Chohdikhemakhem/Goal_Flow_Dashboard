from pathlib import Path
import sys

from sqlalchemy import column


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.enums import UserRole
from app.services.data_scope import RegionScope, region_scope_condition, role_region_scope


def test_regional_roles_have_an_immutable_server_side_scope():
    assert role_region_scope(UserRole.REGIONAL_MANAGER_NORD) == RegionScope.NORD
    assert role_region_scope(UserRole.REGIONAL_MANAGER_SUD) == RegionScope.SUD


def test_north_and_south_conditions_cannot_be_selected_by_request_parameters():
    agency_name = column("agency_name")
    north_sql = str(region_scope_condition(agency_name, RegionScope.NORD))
    south_sql = str(region_scope_condition(agency_name, RegionScope.SUD))

    assert "IN" in north_sql
    assert "NOT IN" in south_sql
    assert "AGENCE EZAHROUNI" not in north_sql  # bound parameters, not interpolated input
