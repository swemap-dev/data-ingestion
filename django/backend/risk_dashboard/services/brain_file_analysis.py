import json
import logging
import os
from django.conf import settings
from git_blame_ingestion_app.models import File, Module, HubType

logger = logging.getLogger(__name__)

# Source code extensions eligible for structural hub analysis.
SOURCE_CODE_EXTENSIONS = {
    '.py', '.js', '.jsx', '.ts', '.tsx',
    '.java', '.kt', '.kts',
    '.go', '.rs', '.rb',
    '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp',
    '.cs', '.swift', '.scala',
    '.php', '.lua', '.r',
}


def _resolve_import(imp, file_paths, file_map):
    """Match an import string to a file in the repo.

    Resolution order:
      1. Exact stem match  — "pkg/utils" matches "pkg/utils.py"
      2. Package __init__  — "pkg/utils" matches "pkg/utils/__init__.py"
      3. Parent fallback    — "pkg/utils/func" (symbol, not file) → try "pkg/utils.py"
         then "pkg/utils/__init__.py"
      4. Basename fallback — last resort loose match on filename
    """
    imp_path = imp.replace(".", "/").strip("./\\")
    if not imp_path:
        return None

    def _match_stem(target):
        """Find a file whose stem (path without extension) matches target."""
        for p in file_paths:
            stem = p.rsplit('.', 1)[0]
            if stem == target or stem.endswith('/' + target):
                return file_map[p]
        return None

    # 1. Exact file stem match (e.g., "pkg/utils.py" exists: "pkg/utils" → "pkg/utils.py")
    result = _match_stem(imp_path)
    if result:
        return result

    # 2. Package __init__ match (e.g., "pkg/utils.py" not exists: "pkg/utils" → "pkg/utils/__init__.py")
    result = _match_stem(imp_path + '/__init__')
    if result:
        return result

    # 3. Parent fallback — last segment may be a symbol, not a file
    #    e.g., "pkg/utils/MyClass" → try "pkg/utils.py" then "pkg/utils/__init__.py"
    if '/' in imp_path:
        parent = imp_path.rsplit('/', 1)[0]
        result = _match_stem(parent)
        if result:
            return result
        result = _match_stem(parent + '/__init__')
        if result:
            return result

    # 4. Basename fallback (e.g., "utils" matches any "utils.py")
    import_base = imp_path.split('/')[-1]
    if import_base != '__init__':
        for p in file_paths:
            path_base = p.split('/')[-1].rsplit('.', 1)[0]
            if import_base == path_base:
                return file_map[p]

    return None


def calculate_structural_hubs(repo_id: int):
    """
    Classify every source file in a repo as a Global Hub, Boundary Hub,
    Local Hub, or None based on its import topology.

    Algorithm (per spec):
      1. Build a global directed import graph across all files in the repo.
      2. Identify Global Hubs (high total in-degree).
      3. Remove Global Hubs from domain-specific calculations.
      4. Classify remaining files as Boundary Hubs or Local Hubs.
    """
    config = settings.RISK_CONFIG

    # ── 0. Load all files ────────────────────────────────────────────
    all_files = list(
        File.objects.filter(module_id__repo_id=repo_id)
        .select_related('module_id')
    )
    files = [f for f in all_files
             if os.path.splitext(f.file_path)[1].lower() in SOURCE_CODE_EXTENSIONS]
    non_code_files = [f for f in all_files if f not in files]

    # Reset non-code files
    if non_code_files:
        for f in non_code_files:
            f.inbound_coupling = 0
            f.internal_imports = 0
            f.external_imports = 0
            f.module_density = 0.0
            f.hub_type = None
        File.objects.bulk_update(
            non_code_files,
            ['inbound_coupling', 'internal_imports', 'external_imports',
             'module_density', 'hub_type'],
        )

    total_files = len(files)
    if total_files == 0:
        logger.info(f"Repo {repo_id} has no source code files. Skipping hub analysis.")
        return

    # Pre-pass: sync loc_count from ast_summary
    for f in files:
        ast_info = f.ast_summary or {}
        f.loc_count = ast_info.get("loc", f.line_count or 0)
    File.objects.bulk_update(files, ['loc_count'])

    # ── 1. Build global import graph ─────────────────────────────────
    file_map = {f.file_path: f for f in files}
    file_paths = sorted(file_map.keys(), key=lambda p: -len(p))

    # importers[file_id] = {importer_file_id: importer_module_id, ...}
    importers = {f.id: {} for f in files}

    for f in files:
        ast_info = f.ast_summary or {}
        for imp in ast_info.get("imports", []):
            matched = _resolve_import(imp, file_paths, file_map)
            if matched and matched.id != f.id:
                importers[matched.id][f.id] = f.module_id_id

    # Dump importers graph to JSON for debugging
    id_to_path = {f.id: f.file_path for f in files}
    debug_importers = {
        id_to_path[fid]: sorted(id_to_path[imp_id] for imp_id in imp_map)
        for fid, imp_map in importers.items()
        if imp_map
    }
    debug_path = os.path.join(settings.BASE_DIR, "..", "..", "data", "debug_importers.json")
    with open(debug_path, "w") as fp:
        json.dump(debug_importers, fp, indent=2, sort_keys=True)
    logger.info(f"Wrote importer debug dump to {debug_path}")

    # Compute raw N_F (total in-degree) for every file
    for f in files:
        f.inbound_coupling = len(importers[f.id])

    # ── 2. Identify Global Hubs ──────────────────────────────────────
    global_abs = config.get("GLOBAL_HUB_ABS_THRESHOLD", 30)
    global_rel = config.get("GLOBAL_HUB_REL_THRESHOLD", 0.15)

    global_hub_ids = set()
    for f in files:
        n_f = f.inbound_coupling
        if n_f >= global_abs or (total_files > 0 and n_f / total_files >= global_rel):
            f.hub_type = HubType.GLOBAL
            global_hub_ids.add(f.id)
        else:
            f.hub_type = None

    # ── 3. Compute adjusted I_F / E_F (excluding Global Hub importers) ──
    for f in files:
        file_importers = importers[f.id]
        f_module = f.module_id_id

        if f.id in global_hub_ids:
            # Global Hubs keep raw I_F / E_F for informational purposes
            f.internal_imports = sum(
                1 for mid in file_importers.values() if mid == f_module
            )
            f.external_imports = sum(
                1 for mid in file_importers.values() if mid != f_module
            )
        else:
            # Exclude Global Hub importers to avoid skewing local metrics
            filtered = {
                fid: mid for fid, mid in file_importers.items()
                if fid not in global_hub_ids
            }
            f.internal_imports = sum(
                1 for mid in filtered.values() if mid == f_module
            )
            f.external_imports = sum(
                1 for mid in filtered.values() if mid != f_module
            )

    # Module sibling counts (excluding Global Hubs) for Local Hub check
    adj_module_counts = {}
    for f in files:
        if f.id not in global_hub_ids:
            mid = f.module_id_id
            adj_module_counts[mid] = adj_module_counts.get(mid, 0) + 1

    # Raw module counts for module_density metric
    raw_module_counts = {}
    for f in files:
        mid = f.module_id_id
        raw_module_counts[mid] = raw_module_counts.get(mid, 0) + 1

    # ── 4. Classify Boundary and Local Hubs ──────────────────────────
    boundary_ext_min = config.get("BOUNDARY_HUB_EXT_MIN", 5)
    boundary_ext_ratio = config.get("BOUNDARY_HUB_EXT_RATIO", 0.80)
    local_min_module = config.get("LOCAL_HUB_MIN_MODULE_SIZE", 3)
    local_internal_ratio = config.get("LOCAL_HUB_INTERNAL_RATIO", 0.70)
    local_internal_dominance = config.get("LOCAL_HUB_INTERNAL_DOMINANCE", 0.50)

    for f in files:
        if f.id in global_hub_ids:
            continue

        e_f = f.external_imports
        i_f = f.internal_imports
        total_imp = i_f + e_f

        # Boundary Hub: heavily imported from outside its module
        if (e_f >= boundary_ext_min
                and total_imp > 0
                and e_f / total_imp >= boundary_ext_ratio):
            f.hub_type = HubType.BOUNDARY
            continue

        # Local Hub: heavily imported within its own module
        s_m = adj_module_counts.get(f.module_id_id, 0) - 1  # siblings (exclude self)
        if s_m >= local_min_module:
            if i_f > 0 and i_f / s_m >= local_internal_ratio:
                if total_imp > 0 and i_f / total_imp >= local_internal_dominance:
                    f.hub_type = HubType.LOCAL

    # ── 5. Compute module_density ────────────────────────────────────
    for f in files:
        siblings = raw_module_counts.get(f.module_id_id, 0) - 1
        f.module_density = f.internal_imports / siblings if siblings > 0 else 0.0

    # ── 6. Persist ───────────────────────────────────────────────────
    File.objects.bulk_update(files, [
        'loc_count', 'inbound_coupling', 'internal_imports',
        'external_imports', 'module_density', 'hub_type',
    ])

    global_count = len(global_hub_ids)
    boundary_count = sum(1 for f in files if f.hub_type == HubType.BOUNDARY)
    local_count = sum(1 for f in files if f.hub_type == HubType.LOCAL)
    logger.info(
        f"Structural hub analysis complete for repo {repo_id}: "
        f"{global_count} global, {boundary_count} boundary, {local_count} local hubs "
        f"out of {total_files} source files"
    )
