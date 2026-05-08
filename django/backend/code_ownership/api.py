from typing import List, Optional
from django.http import Http404
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

@router.get("/modules/{module_id}/reviewers/random", response=List[EngineerStatsSchema])
def list_module_reviewers_random_api(request, module_id: int):
    from .services.module_analytics import list_module_reviewers_random
    return list_module_reviewers_random(module_id)

class ServiceSchema(Schema):
    module_id: int
    name: str
    designer: str
    writer: str
    reviewer: str

class RepoInfoSchema(Schema):
    name: str
    services: List[ServiceSchema]

class RepoOverviewSchema(Schema):
    repo: RepoInfoSchema

@router.get("/repos/{repo_id}/overview", response=RepoOverviewSchema)
def get_repo_overview_api(request, repo_id: int):
    from .services.module_analytics import get_repo_overview
    return get_repo_overview(repo_id)


class DesignerUpdateSchema(Schema):
    name: Optional[str] = None


class ModuleDesignerSchema(Schema):
    module_id: int
    name: Optional[str] = None
    designer: str


@router.put("/modules/{module_id}/designer", response=ModuleDesignerSchema)
def update_module_designer_api(request, module_id: int, payload: DesignerUpdateSchema):
    """
    Sets (or clears) the manually-assigned designer for a module.
    Pass an empty string or null to reset the designer back to "Unassigned".
    """
    from .services.module_analytics import set_module_designer
    result = set_module_designer(module_id, payload.name)
    if "error" in result:
        raise Http404(result["error"])
    return result
