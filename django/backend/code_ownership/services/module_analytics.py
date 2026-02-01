from typing import Dict, List, Any
import argparse
import os
import sys
import django

def _get_module_ownership_stats(module_id: int, interaction_type: str = None) -> List[Dict[str, Any]]:
    from django.db.models import Sum
    from git_blame_ingestion_app.models import Module, File, FileOwnershipMetric

    # 1. Calculate total lines in the module
    files_qs = File.objects.filter(module_id=module_id)
    total_module_lines = files_qs.aggregate(total=Sum('line_count'))['total'] or 0

    if total_module_lines == 0:
        return []

    # 2. Key by engineer and type
    metrics_qs = FileOwnershipMetric.objects.filter(file__module_id=module_id)
    
    if interaction_type:
        metrics_qs = metrics_qs.filter(type=interaction_type)
    
    aggregated_metrics = (
        metrics_qs
        .values('engineer_id', 'engineer__name', 'type')
        .annotate(total_lines_owned=Sum('lines_owned'))
        .order_by('-total_lines_owned')
    )

    results = []
    for item in aggregated_metrics:
        lines_owned = item['total_lines_owned'] or 0
        percentage = (lines_owned / total_module_lines) * 100
        
        results.append({
            "engineer_id": item['engineer_id'],
            "engineer_name": item['engineer__name'],
            "type": item['type'],
            "lines_owned": lines_owned,
            "percentage": round(percentage, 2)
        })
    return results

def get_module_writers(module_id: int) -> List[Dict[str, Any]]:
    from git_blame_ingestion_app.models import InteractionType
    return _get_module_ownership_stats(module_id, InteractionType.WROTE)

def get_module_reviewers(module_id: int) -> List[Dict[str, Any]]:
    from git_blame_ingestion_app.models import InteractionType
    return _get_module_ownership_stats(module_id, InteractionType.REVIEWED)

def calculate_module_ownership(module_id: int) -> Dict[str, Any]:
    """
    Aggregates file-level ownership metrics to calculate the contribution percentage
    of each Writer/Reviewer engineer to the entire module.
    
    Returns a dictionary structure:
    {
        "module_id": int,
        "module_name": str,
        "total_lines": int,
        "ownership": [
            {
                "engineer_id": int,
                "engineer_name": str,
                "type": "WROTE" | "REVIEWED",
                "lines_owned": int,
                "percentage": float
            },
            ...
        ]
    }
    """
    from django.db.models import Sum
    from git_blame_ingestion_app.models import Module, File
    
    try:
        module = Module.objects.get(id=module_id)
    except Module.DoesNotExist:
        return {"error": "Module not found"}
        
    # Get total lines again just for the summary (or could refactor helper to return it)
    files_qs = File.objects.filter(module_id=module_id)
    total_module_lines = files_qs.aggregate(total=Sum('line_count'))['total'] or 0

    ownership_list = _get_module_ownership_stats(module_id)

    return {
        "module_id": module_id,
        "module_name": module.name,
        "total_lines": total_module_lines,
        "ownership": ownership_list
    }

if __name__ == "__main__":
    # Setup Django Environment
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(base_dir)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    django.setup()

    parser = argparse.ArgumentParser()
    parser.add_argument("module_id", type=int, help="Module ID")
    args = parser.parse_args()
    
    print(calculate_module_ownership(args.module_id))