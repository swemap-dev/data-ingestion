from typing import List, Dict, Any, Optional
from ninja import Router, Schema
from .services.risk_analytics import calculate_knowledge_distribution

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
