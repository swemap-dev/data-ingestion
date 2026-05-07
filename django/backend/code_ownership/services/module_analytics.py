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

# TODO: delete this function
def list_module_reviewers_random(module_id: int) -> List[Dict[str, Any]]:
    """
    Randomly returns a list of 2 writers of a given module_id as reviewers.
    """
    import random
    
    # Reuse existing logic to get all writers
    writers = get_module_writers(module_id)
    
    # If fewer than 2 writers, return all of them
    if len(writers) <= 2:
        return writers
        
    # Randomly sample 2
    return random.sample(writers, 2)

def get_repo_overview(repo_id: int) -> Dict[str, Any]:
    """
    Returns a high-level overview of the repository's modules ('services')
    and their key engineering owners.
    """
    from git_blame_ingestion_app.models import Repo, Module, InteractionType
    
    try:
        repo = Repo.objects.get(id=repo_id)
    except Repo.DoesNotExist:
        return {"error": "Repository not found"}
        
    modules = Module.objects.filter(repo_id=repo_id).exclude(name="") # Exclude internal root if cleaner
    
    services_list = []
    
    for module in modules:
        # 1. Designer
        if module.assigned_designer:
            designer_name = module.assigned_designer.name
        else:
            designers = _get_module_ownership_stats(module.id, InteractionType.DESIGNED)
            designer_name = designers[0]['engineer_name'] if designers else "Unassigned"
        
        # 2. Writer
        if module.assigned_writer:
            writer_name = module.assigned_writer.name
        else:
            writers = get_module_writers(module.id)
            writer_name = writers[0]['engineer_name'] if writers else "Unassigned"
        
        # 3. Reviewer
        if module.assigned_reviewer:
            reviewer_name = module.assigned_reviewer.name
        else:
            # Fallback to random if no actual reviewers found yet
            reviewers = list_module_reviewers_random(module.id)
            reviewer_name = reviewers[0]['engineer_name'] if reviewers else "Unassigned"
        
        services_list.append({
            "id": module.id, # Added ID for frontend use
            "name": module.name,
            "designer": designer_name,
            "writer": writer_name,
            "reviewer": reviewer_name
        })
        
    return {
        "repo": {
            "name": repo.name,
            "services": services_list
        }
    }
