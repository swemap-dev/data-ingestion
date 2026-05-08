from typing import List, Optional
from datetime import datetime
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

class RoleUpdateSchema(Schema):
    role: str # 'DESIGNER', 'WRITER', 'REVIEWER'
    name: Optional[str] = None

@router.put("/modules/{module_id}/role")
def update_module_role_api(request, module_id: int, payload: RoleUpdateSchema):
    """
    Sets (or clears) a manually-assigned role for a module.
    """
    from .services.module_analytics import set_module_role
    result = set_module_role(module_id, payload.role, payload.name)
    if "error" in result:
        raise Http404(result["error"])
    return result

class OwnershipUpdateEntrySchema(Schema):
    role: str
    module_name: str
    assigned_at: datetime

class OwnershipUpdatesResponseSchema(Schema):
    updates: List[OwnershipUpdateEntrySchema]

@router.get("/repos/{repo_id}/updates", response=OwnershipUpdatesResponseSchema)
def get_repo_updates_api(request, repo_id: int):
    """
    Returns a summary of code ownership changes (manual assignments) over the last week.
    """
    from git_blame_ingestion_app.models import ModuleRoleAssignment
    from datetime import timedelta
    from django.utils import timezone
    
    since = timezone.now() - timedelta(days=7)
    
    updates = (
        ModuleRoleAssignment.objects
        .filter(module__repo_id=repo_id, assigned_at__gte=since)
        .select_related('module')
        .order_by('-assigned_at')
    )
    
    return {
        "updates": [
            {
                "role": u.role,
                "module_name": u.module.name or u.module.dir_path or "ROOT",
                "assigned_at": u.assigned_at
            }
            for u in updates
        ]
    }
