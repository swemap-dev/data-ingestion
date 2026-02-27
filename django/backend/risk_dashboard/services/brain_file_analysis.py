import logging
from django.db.models import F
from git_blame_ingestion_app.models import File, Module

logger = logging.getLogger(__name__)

# Default Configuration
USAGE_THRESHOLD = 0.8
LINES_THRESHOLD = 50
LINES_PERCENTAGE = 0.10
MIN_MODULE_SIZE = 5

def calculate_module_brain_files(module_id: int):
    """
    Evaluates Brain File metrics for all files in a given module.
    """
    files = list(File.objects.filter(module_id_id=module_id))
    N = len(files)
    
    if N < MIN_MODULE_SIZE:
        logger.info(f"Module {module_id} is too small ({N} files) for Brain File analysis. Skipping.")
        # Reset all files in module to not brain file
        for f in files:
            f.inbound_coupling = 0
            f.module_density = 0.0
            f.is_brain_file = False
        if files:
            File.objects.bulk_update(files, ['inbound_coupling', 'module_density', 'is_brain_file'])
        return
        
    file_map = {f.file_path: f for f in files}
    file_paths = list(file_map.keys())
    
    # Initialize inbound coupling
    # We use a set of unique importer file IDs for each file to calculate unique files that import it
    inbound_importers = {f.id: set() for f in files}
    
    for f in files:
        ast_info = f.ast_summary or {}
        imports = ast_info.get("imports", [])
        
        # update LOC
        f.loc_count = ast_info.get("loc", f.line_count or 0)
        
        for imp in imports:
            # Fuzzy match import paths to file paths in the DB
            imp_path = imp.replace(".", "/").strip("./\\")
            import_base = imp_path.split('/')[-1]
            
            matched_file_id = None
            for p in file_paths:
                path_base = p.split('/')[-1].rsplit('.', 1)[0]
                # Match strict path ending or exact basename
                if ('/' + imp_path in '/' + p) or (import_base == path_base):
                    matched_file_id = file_map[p].id
                    break
            
            if matched_file_id and matched_file_id != f.id:
                inbound_importers[matched_file_id].add(f.id)
                
    # Calculate LOC threshold (Top 10% in the repo)
    try:
        repo_id = files[0].module_id.repo_id
        all_repo_files_loc = list(File.objects.filter(module_id__repo_id=repo_id).values_list('loc_count', flat=True))
        all_repo_files_loc = [x for x in all_repo_files_loc if x is not None]
        if all_repo_files_loc:
            all_repo_files_loc.sort()
            idx = int(len(all_repo_files_loc) * (1.0 - LINES_PERCENTAGE))
            p90_loc = all_repo_files_loc[min(idx, len(all_repo_files_loc)-1)]
        else:
            p90_loc = LINES_THRESHOLD
    except Exception as e:
        logger.error(f"Error calculating 90th percentile LOC for module {module_id}: {e}")
        p90_loc = LINES_THRESHOLD

    # The file has a significant size if LOC > LINES or LOC > Top 10%
    loc_threshold = min(LINES_THRESHOLD, p90_loc)
    if loc_threshold == 0:
        loc_threshold = LINES_THRESHOLD

    # Evaluate Thresholds
    files_to_update = []
    for f in files:
        # C_in: The number of unique files within the same module that import the target file
        f.inbound_coupling = len(inbound_importers[f.id])
        f.module_density = float(f.inbound_coupling) / (N - 1) if N > 1 else 0.0
        
        high_usage = f.module_density >= USAGE_THRESHOLD
        large_size = f.loc_count > loc_threshold
        
        f.is_brain_file = bool(high_usage and large_size)
        files_to_update.append(f)
        
    File.objects.bulk_update(files_to_update, ['loc_count', 'inbound_coupling', 'module_density', 'is_brain_file'])
    logger.info(f"Successfully calculated Brain Files for module {module_id}")

