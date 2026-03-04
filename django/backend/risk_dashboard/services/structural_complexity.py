import logging
from git_blame_ingestion_app.models import File

logger = logging.getLogger(__name__)

# Thresholds from spec
NESTING_THRESHOLD = 4
INHERITANCE_THRESHOLD = 3
NESTING_PENALTY = 4
INHERITANCE_PENALTY = 4


def _compute_inheritance_depths(all_classes: list) -> dict:
    """
    Given a flat list of {"name", "bases"} dicts collected across all files,
    build the parent map and compute inheritance depth for each class.

    Returns: {class_name: depth}  where depth = number of edges to root.
    """
    parent_map = {}
    for cls in all_classes:
        name = cls["name"]
        bases = cls.get("bases", [])
        if bases:
            # Use first base for single-inheritance depth (most common)
            parent_map[name] = bases[0]

    depth_cache = {}

    def _depth(class_name: str, visited: set) -> int:
        if class_name in depth_cache:
            return depth_cache[class_name]
        if class_name not in parent_map:
            depth_cache[class_name] = 0
            return 0
        if class_name in visited:
            # Cycle detected — stop
            depth_cache[class_name] = 0
            return 0
        visited.add(class_name)
        d = 1 + _depth(parent_map[class_name], visited)
        depth_cache[class_name] = d
        return d

    for cls_name in parent_map:
        _depth(cls_name, set())

    return depth_cache


def calculate_structural_complexity(module_id: int):
    """
    Evaluates structural complexity metrics for all files in a given module.

    1. Reads max_nesting_depth from ast_summary for each file.
    2. Reconstructs inheritance chains across all files in the module
       to determine max_inheritance_depth per file.
    3. Computes structural_risk_score = sum of applicable penalties.
    """
    files = list(File.objects.filter(module_id_id=module_id))
    if not files:
        return

    # --- Pass 1: Collect all class info across the module ---
    all_classes = []
    class_to_file_id = {}   # class_name -> file.id

    for f in files:
        ast_info = f.ast_summary or {}
        classes = ast_info.get("classes", [])
        for cls in classes:
            all_classes.append(cls)
            class_to_file_id[cls["name"]] = f.id

    # --- Compute inheritance depths globally ---
    depth_map = _compute_inheritance_depths(all_classes)

    # Max inheritance depth per file
    file_max_inheritance = {}
    for cls_name, depth in depth_map.items():
        fid = class_to_file_id.get(cls_name)
        if fid is not None:
            file_max_inheritance[fid] = max(file_max_inheritance.get(fid, 0), depth)

    # --- Score each file ---
    files_to_update = []
    for f in files:
        ast_info = f.ast_summary or {}
        f.max_nesting_depth = ast_info.get("max_nesting_depth", 0)
        f.max_inheritance_depth = file_max_inheritance.get(f.id, 0)

        nesting_penalty = NESTING_PENALTY if f.max_nesting_depth >= NESTING_THRESHOLD else 0
        inheritance_penalty = INHERITANCE_PENALTY if f.max_inheritance_depth >= INHERITANCE_THRESHOLD else 0
        f.structural_risk_score = nesting_penalty + inheritance_penalty

        files_to_update.append(f)

    File.objects.bulk_update(
        files_to_update,
        ['max_nesting_depth', 'max_inheritance_depth', 'structural_risk_score']
    )
    logger.info(f"Structural complexity calculated for module {module_id}")
