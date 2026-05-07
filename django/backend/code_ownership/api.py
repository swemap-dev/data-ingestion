from typing import List
from datetime import datetime
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

class RoleUpdateSchema(Schema):
    role: str # 'designer', 'writer', 'reviewer'
    engineer_id: int

class UpdateRoleResponseSchema(Schema):
    status: str
    message: str

@router.patch("/modules/{module_id}/roles", response=UpdateRoleResponseSchema)
def patch_module_roles_api(request, module_id: int, payload: RoleUpdateSchema):
    from git_blame_ingestion_app.models import Module, Engineer, ModuleRoleAssignment
    from django.shortcuts import get_object_or_404
    from django.db import transaction

    module = get_object_or_404(Module, id=module_id)
    engineer = get_object_or_404(Engineer, id=payload.engineer_id)
    
    role = payload.role.lower()
    
    with transaction.atomic():
        if role == 'designer':
            module.assigned_designer = engineer
        elif role == 'writer':
            module.assigned_writer = engineer
        elif role == 'reviewer':
            module.assigned_reviewer = engineer
        else:
            return {"status": "error", "message": "Invalid role. Use 'designer', 'writer', or 'reviewer'."}
        
        module.save()
        
        # Log the assignment for history
        ModuleRoleAssignment.objects.create(
            module=module,
            role=role.upper(),
            engineer=engineer
        )

    return {"status": "ok", "message": f"Successfully assigned {engineer.name} as {role}."}

class OwnershipUpdateEntrySchema(Schema):
    module_name: str
    role: str
    engineer_name: str
    assigned_at: datetime

class OwnershipUpdatesResponseSchema(Schema):
    updates: List[OwnershipUpdateEntrySchema]

@router.get("/repos/{repo_id}/updates", response=OwnershipUpdatesResponseSchema)
def get_repo_updates_api(request, repo_id: int):
    from git_blame_ingestion_app.models import ModuleRoleAssignment
    from datetime import timedelta
    from django.utils import timezone
    
    since = timezone.now() - timedelta(days=7)
    
    updates = (
        ModuleRoleAssignment.objects
        .filter(module__repo_id=repo_id, assigned_at__gte=since)
        .select_related('module', 'engineer')
        .order_by('-assigned_at')
    )
    
    return {
        "updates": [
            {
                "module_name": u.module.name or u.module.dir_path or "ROOT",
                "role": u.role,
                "engineer_name": u.engineer.name,
                "assigned_at": u.assigned_at
            }
            for u in updates
        ]
    }
