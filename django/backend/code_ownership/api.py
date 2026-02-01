from typing import List
from ninja import Router, Schema
from .services.module_analytics import get_module_writers, get_module_reviewers

router = Router()

class EngineerStatsSchema(Schema):
    engineer_id: int
    engineer_name: str
    type: str
    lines_owned: int
    percentage: float

@router.get("/modules/{module_id}/writers", response=List[EngineerStatsSchema])
def list_module_writers(request, module_id: int):
    return get_module_writers(module_id)

@router.get("/modules/{module_id}/reviewers", response=List[EngineerStatsSchema])
def list_module_reviewers(request, module_id: int):
    return get_module_reviewers(module_id)
