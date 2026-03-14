from typing import List, Dict, Any, Optional
from ninja import Router, Schema
from django.conf import settings
from .services.risk_analytics import calculate_knowledge_distribution
from .services.structural_complexity import NESTING_THRESHOLD, INHERITANCE_THRESHOLD
from git_blame_ingestion_app.models import File

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

