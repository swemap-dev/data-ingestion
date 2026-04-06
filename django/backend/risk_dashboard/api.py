from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ninja import Router, Schema, Query
from django.conf import settings
from .services.risk_analytics import calculate_knowledge_distribution
from .services.structural_complexity import NESTING_THRESHOLD, INHERITANCE_THRESHOLD
from git_blame_ingestion_app.models import Engineer, File, ModuleOwnershipMetric
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


class NestingInheritanceFileSchema(Schema):
    file_path: str
    max_nesting_depth: int = 0
    max_inheritance_depth: int = 0

class NestingInheritanceSchema(Schema):
    files: List[NestingInheritanceFileSchema]
    total_files: int

@router.get("/modules/{module_id}/nesting-inheritance", response=NestingInheritanceSchema)
def get_nesting_inheritance(request, module_id: int):
    files = File.objects.filter(module_id_id=module_id)
    file_data = [
        {
            "file_path": f.file_path,
            "max_nesting_depth": f.max_nesting_depth,
            "max_inheritance_depth": f.max_inheritance_depth,
        }
        for f in files
    ]
    return {
        "files": file_data,
        "total_files": len(file_data),
    }


class TopStructuralRiskFileSchema(Schema):
    file_path: str
    max_nesting_depth: int = 0
    max_inheritance_depth: int = 0
    structural_risk_score: int = 0

class TopStructuralRiskSchema(Schema):
    total_count: int
    files: List[TopStructuralRiskFileSchema]

@router.get("/repos/{repo_id}/top-structural-risk", response=TopStructuralRiskSchema)
def get_top_structural_risk(request, repo_id: int, k: int = None):
    files = list(
        File.objects.filter(module_id__repo_id=repo_id)
        .order_by('-structural_risk_score')
    )
    total_count = len(files)
    if k is not None:
        files = files[:k]
    return {
        "total_count": total_count,
        "files": [
            {
                "file_path": f.file_path,
                "max_nesting_depth": f.max_nesting_depth,
                "max_inheritance_depth": f.max_inheritance_depth,
                "structural_risk_score": f.structural_risk_score,
            }
            for f in files
        ],
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

class HighRiskGlobalHubFileSchema(Schema):
    file_path: str
    change_frequency_score: float
    global_coupling: int = 0
    loc: int = 0

class HighRiskGlobalHubSchema(Schema):
    total_count: int
    files: List[HighRiskGlobalHubFileSchema]

@router.get("/repos/{repo_id}/high-risk-global-hubs", response=HighRiskGlobalHubSchema)
def get_high_risk_global_hubs(request, repo_id: int, k: int = None, min_churn: float = 7.0):
    files = list(
        File.objects.filter(
            module_id__repo_id=repo_id,
            hub_type='GLOBAL',
            change_frequency_score__gt=min_churn,
        )
        .order_by('-change_frequency_score')
    )
    total_count = len(files)
    if k is not None:
        files = files[:k]
    return {
        "total_count": total_count,
        "files": [
            {
                "file_path": f.file_path,
                "change_frequency_score": f.change_frequency_score,
                "global_coupling": f.inbound_coupling,
                "loc": f.loc_count,
            }
            for f in files
        ],
    }


class TopChurnedFileSchema(Schema):
    file_path: str
    change_frequency_score: float
    change_frequency_raw: float
    is_hotspot: bool

class TopChurnedFilesResponseSchema(Schema):
    total_count: int
    files: List[TopChurnedFileSchema]

@router.get("/repos/{repo_id}/top-churned-files", response=TopChurnedFilesResponseSchema)
def get_top_churned_files(request, repo_id: int, k: int = None, exclude_ext: List[str] = Query(None), exclude_tests: bool = False):
    qs = File.objects.filter(module_id__repo_id=repo_id)
    if exclude_tests:
        qs = qs.exclude(file_path__regex=r'(^|/)test_[^/]*$')
    if exclude_ext:
        for ext in exclude_ext:
            suffix = ext if ext.startswith('.') else f'.{ext}'
            qs = qs.exclude(file_path__endswith=suffix)
    files = list(qs.order_by('-change_frequency_score'))
    total_count = len(files)
    if k is not None:
        files = files[:k]
    hotspot_threshold = settings.RISK_CONFIG["CHURN_HOTSPOT_THRESHOLD"]
    return {
        "total_count": total_count,
        "files": [
            {
                "file_path": f.file_path,
                "change_frequency_score": f.change_frequency_score,
                "change_frequency_raw": f.change_frequency_raw,
                "is_hotspot": f.change_frequency_score >= hotspot_threshold,
            }
            for f in files
        ],
    }

class DominantOwnerEntrySchema(Schema):
    module_id: int
    module_name: str
    engineer_id: int
    engineer_name: str
    lines_owned_percentage: float

class DominantOwnersSchema(Schema):
    total_count: int
    entries: List[DominantOwnerEntrySchema]

# TODO: make it more generalized
@router.get("/repos/{repo_id}/dominant-owners", response=DominantOwnersSchema)
def get_dominant_owners(request, repo_id: int, k: int = None):
    metrics = (
        ModuleOwnershipMetric.objects
        .filter(
            module__repo_id=repo_id,
            lines_owned_percentage__gt=80,
            lines_owned_percentage__lt=100,
            type='WROTE'
        )
        .select_related('module', 'engineer')
        .order_by('-lines_owned_percentage')
    )
    entries = [
        {
            "module_id": m.module_id,
            "module_name": m.module.name or m.module.dir_path or "ROOT",
            "engineer_id": m.engineer_id,
            "engineer_name": m.engineer.name,
            "lines_owned_percentage": m.lines_owned_percentage,
        }
        for m in metrics
    ]
    if k is not None:
        entries = entries[:k]
    return {
        "total_count": len(entries),
        "entries": entries,
    }


class EngineerLastActiveEntry(Schema):
    engineer_id: int
    name: str
    last_active: Optional[datetime] = None

class EngineerLastActiveRequest(Schema):
    engineer_ids: List[int]

class EngineerLastActiveResponse(Schema):
    engineers: List[EngineerLastActiveEntry]

@router.post("/engineers/last-active", response=EngineerLastActiveResponse)
def get_engineers_last_active(request, payload: EngineerLastActiveRequest):
    engineers = Engineer.objects.filter(id__in=payload.engineer_ids).values(
        'id', 'name', 'last_active'
    )
    return {
        "engineers": [
            {
                "engineer_id": e['id'],
                "name": e['name'],
                "last_active": e['last_active'],
            }
            for e in engineers
        ],
    }

class BusFactorEntry(Schema):
    module_id: int
    module_name: str
    engineer_id: int
    engineer_name: str
    lines_owned_percentage: float
    last_active: Optional[datetime] = None

class BusFactorResponse(Schema):
    total_count: int
    entries: List[BusFactorEntry]

# TODO: just for demo. Call this with k=1 will return the needed data
@router.get("/repos/{repo_id}/bus-factor-risk", response=BusFactorResponse)
def get_bus_factor_risk(request, repo_id: int, k: int = None):
    metrics = (
        ModuleOwnershipMetric.objects
        .filter(
            module__repo_id=repo_id,
            lines_owned_percentage__gt=80,
            lines_owned_percentage__lt=100,
            type='WROTE',
        )
        .select_related('module', 'engineer')
        .order_by('-lines_owned_percentage')
    )
    entries = sorted(
        [
            {
                "module_id": m.module_id,
                "module_name": m.module.name or m.module.dir_path or "ROOT",
                "engineer_id": m.engineer_id,
                "engineer_name": m.engineer.name,
                "lines_owned_percentage": m.lines_owned_percentage,
                "last_active": m.engineer.last_active,
            }
            for m in metrics
        ],
        key=lambda e: e["last_active"] or datetime.min.replace(tzinfo=timezone.utc),
    )
    if k is not None:
        entries = entries[:k]
    return {
        "total_count": len(entries),
        "entries": entries,
    }

@router.post("/repos/{repo_id}/recalculate-structural-hubs")
def recalculate_structural_hubs(request, repo_id: int):
    calculate_structural_hubs(repo_id)
    return {"status": "ok"}
