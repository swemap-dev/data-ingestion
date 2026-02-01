import logging
import os
import time
from celery import shared_task
from django.conf import settings

from .services.client import GitHubClient
from .services.file_contents import FileContentsService
from .services import ingestion
from .models import Repo

logger = logging.getLogger(__name__)

_client = None

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
        service = FileContentsService(client)
        
        # We generally blame 'main' or the specific commit?
        # If we blame the specific commit, use commit_hash (SHA) as ref.
        # However, GraphQL blame usually works best with a Branch Name or Commit SHA.
        # "ref" in get_raw_blame logic is used for QualifiedName or SHA.
        
        blame_data = service.get_raw_blame(repo_owner, repo_name, file_path, ref='main') # TODO: include other branches
        
        if not blame_data:
            logger.warning(f"No blame data returned for {file_path} (possibly empty or GraphQL error)")
            return
            
        
        start_time = time.time()
        
        # Determine Module ID using the DB resolver helper
        # Logic: Find the longest matching directory path that is a registered module.
        repo_obj, _ = Repo.objects.get_or_create(
            name=repo_name,
            defaults={'url': f"https://github.com/{repo_owner}/{repo_name}"}
        )
        
        module_id = ingestion.resolve_module_from_db(repo_obj.id, file_path)
        
        if not module_id:
            # Fallback (should typically find ROOT if initialized properly)
            # If resolve returning None despite root being present, it might be a new file in a path not covered?
            # Or root module is missing.
            logger.warning(f"Could not resolve module for {file_path}. Falling back to dynamic creation (legacy behavior) or skipping.")
            # For robustness, let's create a directory-based module if resolution fails, or just log error?
            # Spec says "Fallback: ... Root_Module".
            # If resolve_module_from_db returns None, it means even ROOT wasn't found in DB.
            # Let's try to ensure we have a module.
            dir_path = os.path.dirname(file_path)
            module_obj = ingestion.get_or_create_module(repo_obj.id, dir_path, dir_path)
            module_id = module_obj.id
        
        ingestion.process_blame_response(module_id, blame_data, file_path)
        
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
        service = FileContentsService(client)
        
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
            defaults={'url': repo_url}
        )
        
        from .services.module_resolver import ModuleResolver
        resolver = ModuleResolver(file_paths)
        
        # Get set of all module root directories
        module_roots = resolver.known_modules
        
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
                ingestion.get_or_create_module(repo_obj.id, d, d)
            except Exception as e:
                logger.error(f"Error creating module {d} for {owner}/{name}: {e}")

        
        # Enqueue jobs
        for fpath in file_paths:
            process_commit_blame.delay(owner, name, commit_sha, fpath)
            
    except Exception as e:
        logger.error(f"Initialization failed for {repo_url}: {e}")
