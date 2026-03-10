from typing import List, Dict, Any, Optional
from ninja import Router, Schema
from .services.risk_analytics import calculate_knowledge_distribution
from .services.structural_complexity import NESTING_THRESHOLD, INHERITANCE_THRESHOLD
from git_blame_ingestion_app.models import File
from .services.brain_file_analysis import calculate_module_brain_files

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

class BrainFileSchema(Schema):
    file_path: str
    is_brain_file: bool
    inbound_coupling: int
    module_density: float
    loc_count: Optional[int] = None

@router.get("/modules/{module_id}/brain-files", response=List[BrainFileSchema])
def get_brain_files(request, module_id: int):
    from git_blame_ingestion_app.models import File
    files = File.objects.filter(module_id_id=module_id).values(
        "file_path", "is_brain_file", "inbound_coupling", "module_density", "loc_count"
    )
    return list(files)

@router.post("/modules/{module_id}/recalculate-brain-files")
def recalculate_brain_files(request, module_id: int):
    calculate_module_brain_files(module_id)
    files = File.objects.filter(module_id=module_id).values(
        "file_path", "is_brain_file", "inbound_coupling", "module_density", "loc_count"
    )
    return list(files)