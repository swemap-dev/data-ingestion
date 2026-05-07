import logging
import os
import time
from celery import shared_task, chord
from celery.contrib import rdb
from django.conf import settings

from .services.client import GitHubClient
from .services.file_contents_gql import FileContentsServiceGQL
from .services import ingestion
from .models import Repo

logger = logging.getLogger(__name__)

_client = None
_reviewer_cache = {}

def get_shared_client():
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client

@shared_task(bind=True, max_retries=3)
def process_commit_blame(self, repo_owner, repo_name, commit_hash, file_path, ref='main'):
    """
    Task to fetch blame data and ingest it.
    """
    try:
        logger.info(f"Processing blame for {repo_owner}/{repo_name} {file_path} @ {commit_hash}")
        
        client = get_shared_client()
        service = FileContentsServiceGQL(client)
        
        blame_data, content_bytes = service.get_blame_with_content(
            repo_owner, repo_name, file_path, ref='main',
            reviewer_cache=_reviewer_cache,
        )  # TODO: include other branches
        
        if not blame_data:
            logger.warning(f"No blame data returned for {file_path} (possibly empty or GraphQL error)")
            return
            
        
        start_time = time.time()
        
        # Determine Module ID using the DB resolver helper
        # Logic: Find the longest matching directory path that is a registered module.
        repo_obj, _ = Repo.objects.get_or_create(
            name=repo_name,
            owner=repo_owner,
            defaults={'url': f"https://github.com/{repo_owner}/{repo_name}"}
        )
        
        module_id = ingestion.resolve_module_from_db(repo_obj.id, file_path)
        
        # If no module is found, this file belongs to the ROOT module
        if not module_id:
            logger.warning(f"Could not resolve module for {file_path}. Falling back to ROOT module.")
            root_module = ingestion.get_or_create_module(repo_obj.id, "ROOT", "")
            module_id = root_module.id
        
        # Perform static analysis on file content (already fetched with blame)
        ast_summary = None
        if content_bytes is not None:
            from .services.static_analysis import analyze_code_file
            ast_summary = analyze_code_file(file_path, content_bytes)

        ingestion.process_blame_response(module_id, blame_data, file_path, ast_summary=ast_summary)
        
        duration = time.time() - start_time
        logger.info(f"Task finished in {duration:.2f}s for {file_path}")
        
    except Exception as e:
        logger.error(f"Task failed: {e}")
        # Retry on failure, specifically for rate limits or network issues
        try:
             self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
             logger.error("Max retries exceeded for task.")

@shared_task
def initialize(repo_url, ref=None):
    """
    Initializes a repo by iterating all files and queuing jobs.
    Optionally accepts a ref (branch name or commit SHA) to pin the ingestion.
    """
    try:
        logger.info(f"Initializing {repo_url} at ref={ref or 'default branch'}")
        owner, name = ingestion.parse_repo_url(repo_url)
        if not owner or not name:
            logger.error(f"Invalid Repository URL: {repo_url}")
            return

        client = GitHubClient()
        service = FileContentsServiceGQL(client)

        repo_meta = client.get_repository(owner, name)
        # Use provided ref, otherwise fall back to default branch
        ref = ref or repo_meta.default_branch

        commit_sha, _, _ = service._get_tree_sha(owner, name, ref)
        all_file_paths = service.get_all_file_paths(owner, name, ref)
        
        # Filter out data files and only process source code to drastically speed up ingestion
        from risk_dashboard.services.brain_file_analysis import SOURCE_CODE_EXTENSIONS
        file_paths = [
            f for f in all_file_paths 
            if any(f.endswith(ext) for ext in SOURCE_CODE_EXTENSIONS)
        ]
        
        logger.info(f"Found {len(file_paths)} source files (out of {len(all_file_paths)} total) in {owner}/{name}")
        
        # Pre-create Repo and Modules
        from .models import Repo
        repo_obj, _ = Repo.objects.get_or_create(
            name=name,
            owner=owner,
            defaults={'url': repo_url}
        )
        
        from django.utils import timezone
        repo_obj.last_synced_at = timezone.now()
        repo_obj.save(update_fields=['last_synced_at'])
        
        from .services.module_resolver import ModuleResolver
        resolver = ModuleResolver(file_paths)
        
        # Get set of all module root directories
        module_roots = resolver.known_modules
        logger.info(f"Found {len(module_roots)} functional modules to initialize for {owner}/{name}")
        
        # Ensure ROOT module is present (ModuleResolver logic might have it or not depending on markers)
        # But for our DB, we want an entry for the root if files fall back to it.
        # resolve_module logic falls back to ""; let's ensure "" is a module.
        module_roots.add("") 
        
        logger.info(f"Found {len(module_roots)} functional modules to initialize for {owner}/{name}")

        for d in module_roots:
            try:
                # Upsert module using ingestion service
                # Name will be the dir path (empty string for root)
                name_for_module = d if d else "ROOT"
                mod = ingestion.get_or_create_module(repo_obj.id, name_for_module, d)
                logger.info(f"Created/found module '{name_for_module}' (id={mod.id}, dir_path='{d}')")
            except Exception as e:
                logger.error(f"Error creating module '{d}' for {owner}/{name}: {e}", exc_info=True)

        # Verify ROOT exists before dispatching chord
        from .models import Module as ModuleModel
        root_check = ModuleModel.objects.filter(repo=repo_obj, name="ROOT").first()
        if root_check:
            logger.info(f"ROOT module verified: id={root_check.id}, dir_path='{root_check.dir_path}'")
        else:
            logger.error(f"ROOT module MISSING after creation loop! module_roots contained '': {'' in module_roots}")

        # Second pass: wire up parent references for hierarchical modules
        from .models import Module as ModuleModel
        for d in module_roots:
            if d == "":
                continue  # ROOT has no parent
            parent_dir = resolver.get_parent_module(d)
            if parent_dir is not None:
                name_for_module = d if d else "ROOT"
                parent_name = parent_dir if parent_dir else "ROOT"
                try:
                    module_obj = ModuleModel.objects.get(repo=repo_obj, name=name_for_module)
                    parent_obj = ModuleModel.objects.get(repo=repo_obj, name=parent_name)
                    if module_obj.parent_id != parent_obj.id:
                        module_obj.parent = parent_obj
                        module_obj.save(update_fields=['parent'])
                        logger.info(f"Set parent of '{name_for_module}' -> '{parent_name}'")
                except ModuleModel.DoesNotExist as e:
                    logger.warning(f"Could not set parent for module '{d}': {e}")
        
        # Ingest merged PRs before blame chord so data is ready for finalization
        from .services.pr_ingestion import ingest_merged_prs
        ingest_merged_prs(repo_obj.id, owner, name)

        # Enqueue jobs using Chord
        tasks = [
            process_commit_blame.s(owner, name, commit_sha, fpath, ref)
            for fpath in file_paths
        ]

        # Chord: executing a group of tasks (header) and then a callback (body)
        chord(tasks)(finalize_repo_ingestion.si(repo_obj.id))

        logger.info(f"Queued {len(tasks)} blame tasks for {owner}/{name}")
            
    except Exception as e:
        logger.error(f"Initialization failed for {repo_url}: {e}")

# TODO: Remove this after testing

@shared_task
def initialize_all(ref=None):
    env_repos = os.getenv("GITHUB_REPO_URLS", "")
    if not env_repos:
        repos = [
            'https://github.com/justin-chung-swemap/swemap-demo',
            'https://github.com/justin-chung-swemap/payment-platform',
            'https://github.com/justin-chung-swemap/data-infrastructure'
        ]
    else:
        repos = [r.strip() for r in env_repos.split(",") if r.strip()]

    from .models import File, Module, Repo
    logger.info("Clearing all existing repo data before re-initialization.")
    File.objects.all().delete()
    Module.objects.all().delete()
    Repo.objects.all().delete()

    for url in repos:
        logger.info(f"Triggering initialization for {url} at ref={ref or 'default'}")
        initialize.delay(url, ref=ref)

    return {"status": "queued", "repos": repos}

@shared_task
def incremental_sync(repo_id=None):
    """
    Polls GitHub for commits since the last sync timestamp and enqueues blame tasks ONLY for changed files.
    """
    from .models import Repo
    from django.utils import timezone
    repos = Repo.objects.filter(id=repo_id) if repo_id else Repo.objects.all()

    client = get_shared_client()
    for repo in repos:
        if not repo.last_synced_at:
            logger.warning(f"Repo {repo.name} has no last_synced_at, skipping incremental sync. Please run initialize first.")
            continue

        logger.info(f"Starting incremental sync for {repo.owner}/{repo.name} since {repo.last_synced_at}")
        try:
            changed_files = client.get_changed_files_since(repo.owner, repo.name, repo.last_synced_at)
            
            if not changed_files:
                logger.info(f"No files changed for {repo.owner}/{repo.name} since {repo.last_synced_at}")
            else:
                commit_sha = 'main'
                
                tasks = [
                    process_commit_blame.s(repo.owner, repo.name, commit_sha, fpath, 'main')
                    for fpath in changed_files
                ]
                
                # Identify affected modules
                affected_module_ids = set()
                for fpath in changed_files:
                    module_id = ingestion.resolve_module_from_db(repo.id, fpath)
                    if module_id:
                        affected_module_ids.add(module_id)
                
                if tasks:
                    chord(tasks)(recalculate_affected_modules.si(list(affected_module_ids)))
                    logger.info(f"Queued {len(tasks)} blame tasks for {repo.owner}/{repo.name} incremental sync")
            
            repo.last_synced_at = timezone.now()
            repo.save(update_fields=['last_synced_at'])
        except Exception as e:
            logger.error(f"Incremental sync failed for {repo.owner}/{repo.name}: {e}")

@shared_task
def recalculate_affected_modules(module_ids):
    """
    Recalculate metrics for specific modules after a webhook push.
    Only processes the modules that had files modified in the push.
    Runs fast file/module level metrics (ownership, AST complexity).
    """
    from risk_dashboard.services.structural_complexity import calculate_structural_complexity

    for module_id in module_ids:
        logger.info(f"Recalculating real-time metrics for affected module {module_id}")
        ingestion.calculate_module_metrics(module_id)
        calculate_structural_complexity(module_id)

    logger.info(f"Recalculated real-time metrics for {len(module_ids)} affected module(s)")

@shared_task
def nightly_repo_recalculation(repo_id=None):
    """
    Nightly cron job to calculate heavy repository-wide metrics.
    If repo_id is provided, runs for that repo. Otherwise runs for all repos.
    """
    from .models import Repo
    from risk_dashboard.services.brain_file_analysis import calculate_structural_hubs
    from risk_dashboard.services.change_frequency import calculate_change_frequency
    from risk_dashboard.services.composite_risk import calculate_composite_risk
    from .services.pr_ingestion import ingest_merged_prs

    repos = Repo.objects.filter(id=repo_id) if repo_id else Repo.objects.all()

    for repo in repos:
        logger.info(f"Starting nightly recalculation for repo {repo.id} ({repo.name})")
        
        try:
            logger.info(f"Ingesting merged PRs for repo {repo.id}")
            ingest_merged_prs(repo.id, repo.owner, repo.name)
            
            logger.info(f"Calculating Change Frequency for repo {repo.id}")
            calculate_change_frequency(repo.id)
            
            logger.info(f"Calculating Structural Hubs for repo {repo.id}")
            calculate_structural_hubs(repo.id)
            
            logger.info(f"Calculating Composite Risk for repo {repo.id}")
            calculate_composite_risk(repo.id)
            
            logger.info(f"Nightly recalculation complete for repo {repo.id}")
        except Exception as e:
            logger.error(f"Error during nightly recalculation for repo {repo.id}: {e}", exc_info=True)

@shared_task
def finalize_repo_ingestion(repo_id):
    """
    Callback task that runs after all file blame tasks are complete.
    Triggers module metrics calculation.
    """
    logger.info(f"All files processed for repo {repo_id}. Starting module metrics calculation.")
    
    try:
        from .models import Module
        from risk_dashboard.services.brain_file_analysis import calculate_structural_hubs
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        from risk_dashboard.services.change_frequency import calculate_change_frequency
        modules = Module.objects.filter(repo_id=repo_id)

        for module in modules:
            logger.info(f"Calculating metrics for module {module.id} ({module.name})")
            ingestion.calculate_module_metrics(module.id)

            logger.info(f"Calculating Structural Complexity for module {module.id}")
            calculate_structural_complexity(module.id)

        # Structural hubs + change frequency are repo-wide
        logger.info(f"Calculating Structural Hubs for repo {repo_id}")
        calculate_structural_hubs(repo_id)

        logger.info(f"Calculating Change Frequency for repo {repo_id}")
        calculate_change_frequency(repo_id)

        from risk_dashboard.services.composite_risk import calculate_composite_risk
        logger.info(f"Calculating Composite Risk for repo {repo_id}")
        calculate_composite_risk(repo_id)

        logger.info(f"Module metrics calculation complete for repo {repo_id}")

    except Exception as e:
        logger.error(f"Error in finalize_repo_ingestion for repo {repo_id}: {e}")
