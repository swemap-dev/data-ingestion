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
def process_commit_blame(self, repo_owner, repo_name, commit_hash, file_path):
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
            try:
                module_obj = ingestion.get_module(repo_obj.id, "ROOT")
                module_id = module_obj.id
            except ingestion.Module.DoesNotExist:
                logger.error(f"ROOT module not found for repo {repo_owner}/{repo_name}. Cannot process file {file_path}")
                return
        
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
def initialize(repo_url):
    """
    Initializes a repo by iterating all files and queuing jobs.
    """
    try:
        logger.info(f"Initializing {repo_url}")
        owner, name = ingestion.parse_repo_url(repo_url)
        if not owner or not name:
            logger.error(f"Invalid Repository URL: {repo_url}")
            return
            
        client = GitHubClient()
        service = FileContentsServiceGQL(client)

        # Get default branch
        repo_meta = client.get_repository(owner, name)
        ref = repo_meta.default_branch
        
        # Get Commit SHA
        commit_sha, _, _ = service._get_tree_sha(owner, name, ref)
        file_paths = service.get_all_file_paths(owner, name, ref)
        logger.info(f"Found {len(file_paths)} files in {owner}/{name}")
        
        # Pre-create Repo and Modules
        from .models import Repo
        repo_obj, _ = Repo.objects.get_or_create(
            name=name,
            owner=owner,
            defaults={'url': repo_url}
        )
        
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
                ingestion.get_or_create_module(repo_obj.id, name_for_module, d)
            except Exception as e:
                logger.error(f"Error creating module {d} for {owner}/{name}: {e}")

        
        # Ingest merged PRs before blame chord so data is ready for finalization
        from .services.pr_ingestion import ingest_merged_prs
        ingest_merged_prs(repo_obj.id, owner, name)

        # Enqueue jobs using Chord
        tasks = [
            process_commit_blame.s(owner, name, commit_sha, fpath)
            for fpath in file_paths
        ]

        # Chord: executing a group of tasks (header) and then a callback (body)
        chord(tasks)(finalize_repo_ingestion.si(repo_obj.id))

        logger.info(f"Queued {len(tasks)} blame tasks for {owner}/{name}")
            
    except Exception as e:
        logger.error(f"Initialization failed for {repo_url}: {e}")

# TODO: Remove this after testing
@shared_task
def initialize_all():
    """
    Initializes a set of default repositories.
    """
    repos = [
        'https://github.com/justin-chung-swemap/swemap-demo',
        'https://github.com/justin-chung-swemap/payment-platform',
        'https://github.com/justin-chung-swemap/data-infrastructure'
    ]
    
    for url in repos:
        logger.info(f"Triggering initialization for {url}")
        initialize.delay(url)
    
    return {"status": "queued", "repos": repos}

@shared_task
def recalculate_affected_modules(module_ids):
    """
    Recalculate metrics for specific modules after a webhook push.
    Only processes the modules that had files modified in the push.
    """
    from risk_dashboard.services.brain_file_analysis import calculate_module_brain_files
    from risk_dashboard.services.structural_complexity import calculate_structural_complexity
    from risk_dashboard.services.change_frequency import calculate_change_frequency
    from .services.pr_ingestion import ingest_merged_prs

    # PR ingestion + change frequency are repo-wide — run once, not per module
    if module_ids:
        from .models import Module
        first_module = Module.objects.get(id=module_ids[0])
        repo = first_module.repo
        ingest_merged_prs(repo.id, repo.owner, repo.name)
        calculate_change_frequency(repo.id)

    for module_id in module_ids:
        logger.info(f"Recalculating metrics for affected module {module_id}")
        ingestion.calculate_module_metrics(module_id)
        calculate_module_brain_files(module_id)
        calculate_structural_complexity(module_id)

    logger.info(f"Recalculated metrics for {len(module_ids)} affected module(s)")

@shared_task
def finalize_repo_ingestion(repo_id):
    """
    Callback task that runs after all file blame tasks are complete.
    Triggers module metrics calculation.
    """
    logger.info(f"All files processed for repo {repo_id}. Starting module metrics calculation.")
    
    try:
        from .models import Module
        from risk_dashboard.services.brain_file_analysis import calculate_module_brain_files
        from risk_dashboard.services.structural_complexity import calculate_structural_complexity
        from risk_dashboard.services.change_frequency import calculate_change_frequency
        modules = Module.objects.filter(repo_id=repo_id)

        for module in modules:
            logger.info(f"Calculating metrics for module {module.id} ({module.name})")
            ingestion.calculate_module_metrics(module.id)

            logger.info(f"Calculating Brain Files for module {module.id}")
            calculate_module_brain_files(module.id)

            logger.info(f"Calculating Structural Complexity for module {module.id}")
            calculate_structural_complexity(module.id)

        # Change frequency is repo-wide (percentile ranking requires all files)
        logger.info(f"Calculating Change Frequency for repo {repo_id}")
        calculate_change_frequency(repo_id)

        logger.info(f"Module metrics calculation complete for repo {repo_id}")

    except Exception as e:
        logger.error(f"Error in finalize_repo_ingestion for repo {repo_id}: {e}")
