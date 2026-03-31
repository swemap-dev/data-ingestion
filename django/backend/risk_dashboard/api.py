from typing import List, Dict, Any, Optional
from ninja import Router, Schema
from django.conf import settings
from .services.risk_analytics import calculate_knowledge_distribution
from .services.structural_complexity import NESTING_THRESHOLD, INHERITANCE_THRESHOLD
from git_blame_ingestion_app.models import File, Module
from .services.brain_file_analysis import calculate_module_brain_files
from code_ownership.services.module_analytics import get_module_writers

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

class RiskDataSchema(Schema):
    service: str
    riskScore: int
    type: str

class OwnershipGapSchema(Schema):
    area: str
    issue: str
    recommendation: str
    severity: str

class DistributionDataSchema(Schema):
    name: str # 'Critical', 'High', 'Medium', 'Low'
    value: int
    color: str

class KnowledgeMatrixEngineerSchema(Schema):
    engineer: str
    contributions: List[int]

class DashboardSummarySchema(Schema):
    riskData: List[RiskDataSchema]
    ownershipGaps: List[OwnershipGapSchema]
    distributionData: List[DistributionDataSchema]
    knowledgeMatrix: List[KnowledgeMatrixEngineerSchema]
    services: List[str]
    brainFiles: List[BrainFileSchema]
    highChurnFiles: List[ChangeFrequencyFileSchema]
    complexFiles: List[FlaggedFileSchema]

@router.get("/repos/{repo_id}/dashboard-summary", response=DashboardSummarySchema)
def get_dashboard_summary(request, repo_id: int):
    # --- HARDCODED MOCK DATA FOR FRONTEND DEVELOPMENT ---
    return {
        "services": [
            "api-gateway",
            "auth-service",
            "data-pipeline",
            "frontend-web",
            "notification-svc"
        ],
        "riskData": [
            {"service": "api-gateway", "riskScore": 85, "type": "Critical"},
            {"service": "auth-service", "riskScore": 72, "type": "High"},
            {"service": "data-pipeline", "riskScore": 58, "type": "Medium"},
            {"service": "frontend-web", "riskScore": 45, "type": "Medium"},
            {"service": "notification-svc", "riskScore": 28, "type": "Low"}
        ],
        "distributionData": [
            {"name": "Critical", "value": 1, "color": "#ef4444"},
            {"name": "High", "value": 1, "color": "#f97316"},
            {"name": "Medium", "value": 2, "color": "#f59e0b"},
            {"name": "Low", "value": 1, "color": "#22c55e"}
        ],
        "ownershipGaps": [
            {"area": "auth-service", "issue": "Single Point of Failure", "recommendation": "Knowledge transfer to 2 additional engineers", "severity": "high"},
            {"area": "data-pipeline", "issue": "Abandoned Code", "recommendation": "Identify new owner or explicitly deprecate", "severity": "critical"}
        ],
        "knowledgeMatrix": [
            {"engineer": "Sarah M.", "contributions": [15, 85, 10, 5, 0]},
            {"engineer": "Mike R.", "contributions": [25, 10, 20, 25, 15]},
            {"engineer": "Emma D.", "contributions": [60, 5, 5, 20, 10]},
            {"engineer": "Alex K.", "contributions": [0, 0, 25, 30, 35]},
            {"engineer": "James L.", "contributions": [0, 0, 70, 15, 5]}
        ],
        "brainFiles": [
            {"file_path": "auth-service/src/core/auth_manager.ts", "is_brain_file": True, "inbound_coupling": 42, "module_density": 0.85, "loc_count": 2100},
            {"file_path": "api-gateway/handlers/request_router.go", "is_brain_file": True, "inbound_coupling": 56, "module_density": 0.92, "loc_count": 3400}
        ],
        "highChurnFiles": [
            {"file_path": "frontend-web/components/BillingModal.tsx", "change_frequency_score": 9.2, "change_frequency_raw": 18.5, "is_hotspot": True},
            {"file_path": "data-pipeline/etl/transform_worker.py", "change_frequency_score": 8.7, "change_frequency_raw": 15.2, "is_hotspot": True}
        ],
        "complexFiles": [
            {"file_path": "api-gateway/middleware/rate_limiter.go", "max_nesting_depth": 5, "max_inheritance_depth": 0},
            {"file_path": "notification-svc/src/email/BaseEmailTemplate.java", "max_nesting_depth": 2, "max_inheritance_depth": 4}
        ]
    }
    # ----------------------------------------------------

    modules = Module.objects.filter(repo_id=repo_id).exclude(name__exact='').exclude(name__isnull=True)

    services_list = []
    risk_data = []
    ownership_gaps = []
    brain_files_list = []
    high_churn_list = []
    complex_files_list = []

    engineer_map = {} # Context across all modules: engineer_name -> dict of module_name -> pct

    for module in modules:
        # Module name fallback if empty somehow
        mod_name = module.name if module.name else "ROOT"
        services_list.append(mod_name)

        # 1. Structural Complexity Score & Change Frequency Score to build unified riskScore
        struct_data = get_structural_complexity(request, module.id)
        struct_score = struct_data.get("total_structural_risk_score", 0)
        complex_files_list.extend(struct_data.get("files_with_deep_nesting", []))
        complex_files_list.extend(struct_data.get("files_with_deep_inheritance", []))
        
        freq_data = get_change_frequency(request, module.id)
        avg_freq = freq_data.get("average_score", 0)
        high_churn_list.extend([f for f in freq_data.get("files", []) if f.get("is_hotspot")])

        # Brain files
        bf_data = get_brain_files(request, module.id)
        brain_files_list.extend([f for f in bf_data if f.get("is_brain_file")])
        
        # Simple Risk Heuristic: (Average churn score 0-10) * 5 + Structural Risk
        raw_score = (avg_freq * 5) + (struct_score)
        
        # Clamp to 100 max for percentage UI
        final_risk_score = min(int(raw_score), 100)
        
        if final_risk_score >= 80:
            risk_type = "Critical"
        elif final_risk_score >= 60:
            risk_type = "High"
        elif final_risk_score >= 40:
            risk_type = "Medium"
        else:
            risk_type = "Low"

        risk_data.append({
            "service": mod_name,
            "riskScore": final_risk_score,
            "type": risk_type
        })

        # 2. Knowledge Distribution for gaps
        kd = calculate_knowledge_distribution(module.id)
        if kd.get("bus_factor"):
            ownership_gaps.append({
                "area": mod_name,
                "issue": "Single Point of Failure",
                "recommendation": "Knowledge transfer to 2 additional engineers",
                "severity": "high"
            })
        elif kd.get("abandoned_code"):
            ownership_gaps.append({
                "area": mod_name,
                "issue": "Abandoned Code",
                "recommendation": "Identify new owner or explicitly deprecate",
                "severity": "critical"
            })

        # 3. Engineer Module Writers array
        writers = get_module_writers(module.id)
        for w in writers:
            eng_name = w["engineer_name"]
            if eng_name not in engineer_map:
                engineer_map[eng_name] = {}
            engineer_map[eng_name][mod_name] = w["percentage"]

    # Process overall pie chart
    risk_type_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for rd in risk_data:
        if rd["type"] in risk_type_counts:
            risk_type_counts[rd["type"]] += 1

    color_map = {
        "Critical": "#ef4444",
        "High": "#f97316",
        "Medium": "#f59e0b",
        "Low": "#22c55e"
    }

    distribution_data = []
    # Force static ordering to match UI colors consistently
    for rt in ["Critical", "High", "Medium", "Low"]:
        cnt = risk_type_counts[rt]
        if cnt >= 0: # UI might expect empty buckets or we omit them. Let's include all for a stable legend
            distribution_data.append({
                "name": rt,
                "value": cnt,
                "color": color_map[rt]
            })

    # Process Matrix
    knowledge_matrix = []
    for eng_name in sorted(engineer_map.keys()):
        contribs = []
        for svc in services_list:
            pct = engineer_map[eng_name].get(svc, 0)
            contribs.append(int(pct))
        knowledge_matrix.append({
            "engineer": eng_name,
            "contributions": contribs
        })

    return {
        "riskData": risk_data,
        "ownershipGaps": ownership_gaps,
        "distributionData": distribution_data,
        "knowledgeMatrix": knowledge_matrix,
        "services": services_list,
        "brainFiles": brain_files_list,
        "highChurnFiles": high_churn_list,
        "complexFiles": complex_files_list
    }