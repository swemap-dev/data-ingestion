from typing import List, Dict, Any, Optional
from ninja import Router, Schema
from django.conf import settings
from .services.risk_analytics import calculate_knowledge_distribution
from .services.structural_complexity import NESTING_THRESHOLD, INHERITANCE_THRESHOLD
from git_blame_ingestion_app.models import File
from .services.brain_file_analysis import calculate_structural_hubs

router = Router()

class DistributionSnapshotSchema(Schema):
    engineer_id: int
    engineer_name: str
    type: str
    lines_owned: int
    percentage: float

class KnowledgeDistributionSchema(Schema):
    bus_factor: bool
    abandoned_code: bool
    abandoned_details: Optional[str] = None
    silo_type: str
    distribution_snapshot: List[DistributionSnapshotSchema]

@router.get("/modules/{module_id}/knowledge-distribution", response=KnowledgeDistributionSchema)
def get_knowledge_distribution(request, module_id: int):
    return calculate_knowledge_distribution(module_id)


class FlaggedFileSchema(Schema):
    file_path: str
    max_nesting_depth: int = 0
    max_inheritance_depth: int = 0

class StructuralComplexitySchema(Schema):
    files_with_deep_nesting: List[FlaggedFileSchema]
    files_with_deep_inheritance: List[FlaggedFileSchema]
    total_structural_risk_score: int

@router.get("/modules/{module_id}/structural-complexity", response=StructuralComplexitySchema)
def get_structural_complexity(request, module_id: int):
    # Scores are pre-computed during ingestion — just read from DB
    files = File.objects.filter(module_id_id=module_id)

    deep_nesting = [
        {"file_path": f.file_path, "max_nesting_depth": f.max_nesting_depth, "max_inheritance_depth": f.max_inheritance_depth}
        for f in files if f.max_nesting_depth >= NESTING_THRESHOLD
    ]
    deep_inheritance = [
        {"file_path": f.file_path, "max_nesting_depth": f.max_nesting_depth, "max_inheritance_depth": f.max_inheritance_depth}
        for f in files if f.max_inheritance_depth >= INHERITANCE_THRESHOLD
    ]
    total_risk = sum(f.structural_risk_score for f in files)

    return {
        "files_with_deep_nesting": deep_nesting,
        "files_with_deep_inheritance": deep_inheritance,
        "total_structural_risk_score": total_risk,
    }


class ChangeFrequencyFileSchema(Schema):
    file_path: str
    change_frequency_score: float
    change_frequency_raw: float
    is_hotspot: bool

class ChangeFrequencySchema(Schema):
    files: List[ChangeFrequencyFileSchema]
    hotspot_count: int
    average_score: float

@router.get("/modules/{module_id}/change-frequency", response=ChangeFrequencySchema)
def get_change_frequency(request, module_id: int):
    # Scores are pre-computed during ingestion — just read from DB
    files = File.objects.filter(module_id_id=module_id)

    hotspot_threshold = settings.RISK_CONFIG["CHURN_HOTSPOT_THRESHOLD"]

    file_data = [
        {
            "file_path": f.file_path,
            "change_frequency_score": f.change_frequency_score,
            "change_frequency_raw": f.change_frequency_raw,
            "is_hotspot": f.change_frequency_score >= hotspot_threshold,
        }
        for f in files
    ]

    hotspot_count = sum(1 for f in file_data if f["is_hotspot"])
    average_score = (
        sum(f["change_frequency_score"] for f in file_data) / len(file_data)
        if file_data
        else 0.0
    )

    return {
        "files": file_data,
        "hotspot_count": hotspot_count,
        "average_score": average_score,
    }


class ChildRiskSchema(Schema):
    module_id: int
    module_name: str
    global_hub_count: int = 0
    boundary_hub_count: int = 0
    local_hub_count: int = 0
    structural_risk_score: int = 0
    hotspot_count: int = 0
    file_count: int = 0

class AggregateRiskSchema(Schema):
    module_name: str
    own_risk: ChildRiskSchema
    children: List[ChildRiskSchema]
    rolled_up_risk: ChildRiskSchema

def _get_module_risk(module) -> dict:
    """Compute risk summary for a single module from its pre-calculated file metrics."""
    files = File.objects.filter(module_id_id=module.id)
    hotspot_threshold = settings.RISK_CONFIG.get("CHURN_HOTSPOT_THRESHOLD", 0.8)
    return {
        "module_id": module.id,
        "module_name": module.name or "ROOT",
        "global_hub_count": sum(1 for f in files if f.hub_type == 'GLOBAL'),
        "boundary_hub_count": sum(1 for f in files if f.hub_type == 'BOUNDARY'),
        "local_hub_count": sum(1 for f in files if f.hub_type == 'LOCAL'),
        "structural_risk_score": sum(f.structural_risk_score for f in files),
        "hotspot_count": sum(1 for f in files if f.change_frequency_score >= hotspot_threshold),
        "file_count": files.count(),
    }

def _get_all_descendants(module):
    """Recursively collect all descendant modules."""
    descendants = []
    for child in module.children.all():
        descendants.append(child)
        descendants.extend(_get_all_descendants(child))
    return descendants

@router.get("/modules/{module_id}/aggregate-risk", response=AggregateRiskSchema)
def get_aggregate_risk(request, module_id: int):
    from git_blame_ingestion_app.models import Module
    module = Module.objects.get(id=module_id)

    own_risk = _get_module_risk(module)
    descendants = _get_all_descendants(module)
    children_risks = [_get_module_risk(d) for d in descendants]

    # Roll up: sum own + all descendants
    rolled_up = {
        "module_id": module.id,
        "module_name": module.name or "ROOT",
        "global_hub_count": own_risk["global_hub_count"] + sum(c["global_hub_count"] for c in children_risks),
        "boundary_hub_count": own_risk["boundary_hub_count"] + sum(c["boundary_hub_count"] for c in children_risks),
        "local_hub_count": own_risk["local_hub_count"] + sum(c["local_hub_count"] for c in children_risks),
        "structural_risk_score": own_risk["structural_risk_score"] + sum(c["structural_risk_score"] for c in children_risks),
        "hotspot_count": own_risk["hotspot_count"] + sum(c["hotspot_count"] for c in children_risks),
        "file_count": own_risk["file_count"] + sum(c["file_count"] for c in children_risks),
    }

    return {
        "module_name": module.name or "ROOT",
        "own_risk": own_risk,
        "children": children_risks,
        "rolled_up_risk": rolled_up,
    }

class HubFileEntrySchema(Schema):
    path: str
    module_id: int
    module: str
    loc: int = 0
    global_coupling: int = 0
    external_imports: int = 0
    internal_imports: int = 0
    module_density: float = 0.0

class HubListSchema(Schema):
    type: str
    total_count: int
    files: List[HubFileEntrySchema]

def _get_hub_files(repo_id: int, hub_type: str, k: int = None) -> dict:
    files = list(
        File.objects.filter(module_id__repo_id=repo_id, hub_type=hub_type)
        .select_related('module_id')
    )
    total_count = len(files)
    if k is not None:
        files = files[:k]
    return {
        "type": hub_type,
        "total_count": total_count,
        "files": [
            {
                "path": f.file_path,
                "module_id": f.module_id_id,
                "module": f.module_id.dir_path or f.module_id.name or "",
                "loc": f.loc_count,
                "global_coupling": f.inbound_coupling,
                "external_imports": f.external_imports,
                "internal_imports": f.internal_imports,
                "module_density": f.module_density,
            }
            for f in files
        ],
    }

@router.get("/repos/{repo_id}/global-hubs", response=HubListSchema)
def get_global_hubs(request, repo_id: int, k: int = None):
    return _get_hub_files(repo_id, 'GLOBAL', k)

@router.get("/repos/{repo_id}/boundary-hubs", response=HubListSchema)
def get_boundary_hubs(request, repo_id: int, k: int = None):
    return _get_hub_files(repo_id, 'BOUNDARY', k)

@router.get("/repos/{repo_id}/local-hubs", response=HubListSchema)
def get_local_hubs(request, repo_id: int, k: int = None):
    return _get_hub_files(repo_id, 'LOCAL', k)

@router.post("/repos/{repo_id}/recalculate-structural-hubs")
def recalculate_structural_hubs(request, repo_id: int):
    calculate_structural_hubs(repo_id)
    return {"status": "ok"}
