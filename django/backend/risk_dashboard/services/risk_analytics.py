from typing import Dict, Any, List
from datetime import timedelta
from django.utils import timezone
from code_ownership.services.module_analytics import get_module_writers
from git_blame_ingestion_app.models import Engineer

def calculate_knowledge_distribution(module_id: int) -> Dict[str, Any]:
    """
    Calculates the Knowledge Distribution risk metrics for a given module.
    
    Metrics:
    - Bus Factor: Critical if top developer has > 90% ownership.
    - Abandoned Code: Critical if main owner (>30%) is inactive (>90 days).
    - Healthy Silo: Top owner has 50-70%, others have 10-20%.
    - Toxic Silo: Top owner has > 90% (Monopoly).
    """
    from django.conf import settings
    
    config = settings.RISK_CONFIG
    
    writers = get_module_writers(module_id)
    
    if not writers:
        return {
            "bus_factor": False,
            "abandoned_code": False,
            "abandoned_details": "No writers found",
            "silo_type": "NONE",
            "distribution_snapshot": []
        }

    # Calculate total ownership percentage (should be close to 100%, but metrics might be partial)
    # The get_module_writers returns a list with 'percentage' key.
    
    top_writer = writers[0]
    top_percentage = top_writer['percentage']
    
    # 1. Bus Factor / Toxic Silo
    is_bus_factor = top_percentage > config["BUS_FACTOR_THRESHOLD"]
    
    # 2. Abandoned Code
    is_abandoned = False
    abandoned_details = None
    
    # Check if any major owner (>30%) is inactive
    # We need to fetch the Engineer object to check 'last_active'
    threshold_date = timezone.now() - timedelta(days=config["ABANDONED_INACTIVE_DAYS"])
    abandoned_threshold = config["ABANDONED_CODE_THRESHOLD"]
    
    for writer in writers:
        if writer['percentage'] > abandoned_threshold:
            try:
                engineer = Engineer.objects.get(id=writer['engineer_id'])
                if engineer.last_active and engineer.last_active < threshold_date:
                    is_abandoned = True
                    abandoned_details = f"Owner {engineer.name} ({writer['percentage']}%) inactive since {engineer.last_active.date()}"
                    break
            except Engineer.DoesNotExist:
                continue

    # 3. Silo Classification
    silo_type = "DISTRIBUTED" # Default
    
    if top_percentage > config["BUS_FACTOR_THRESHOLD"]:
        silo_type = "TOXIC_SILO"
    elif config["HEALTHY_SILO_TOP_MIN"] <= top_percentage <= config["HEALTHY_SILO_TOP_MAX"]:
        # Check if others have 10-20%
        # We check the second writer
        if len(writers) > 1:
            second_percentage = writers[1]['percentage']
            if config["HEALTHY_SILO_OTHER_MIN"] <= second_percentage <= config["HEALTHY_SILO_OTHER_MAX"]:
                 silo_type = "HEALTHY_SILO"
            else:
                # If second is too low, it might deemed risky, but let's stick to spec
                pass
        else:
            # Only one writer but between 50-70 (rest is unowned??)
            # Unlikely in this system unless unassigned lines count.
            pass

    return {
        "bus_factor": is_bus_factor,
        "abandoned_code": is_abandoned,
        "abandoned_details": abandoned_details,
        "silo_type": silo_type,
        "distribution_snapshot": writers[:5] # Return top 3 for UI context
    }
