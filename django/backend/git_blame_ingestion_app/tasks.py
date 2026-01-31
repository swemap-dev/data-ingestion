import logging
import os
from celery import shared_task
from django.conf import settings

from .services.client import GitHubClient
from .services.file_contents import FileContentsService
from .services import ingestion

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
        print(blame_data)
        
        if not blame_data:
            logger.warning(f"No blame data returned for {file_path} (possibly empty or GraphQL error)")
            return
            
        # Determine Module ID
        dir_path = os.path.dirname(file_path)
        
        # We need repo_id. 
        # Ideally, we should pass repo_id or look it up.
        # For MVP, we can lookup repo check if exists.
        # But for ingestion.process_blame_response, it expects module_id.
        
        # Let's find repo_id first.
        # Optimization: We could pass repo_id in the task args, but let's lookup.
        # For now, let's assume we have a function or query.
        from .models import Repo
        # We can implement a helper or just query.
        # Assuming Repo exists (created by initialize or hook receiver).
        # We'll rely on the hook/initializer to have created the Repo.
        repo_obj = Repo.objects.filter(name=repo_name).first() # Name might not be unique if different owners?
        # Actually Repo model has 'url'.
        # Let's just create/get Repo by name/owner logic?
        # Current model has 'name' and 'url'.
        # Let's assume name is "repo_name" (short) or "owner/repo_name"?
        # Flask logic used `url` to find repos.
        
        # Let's simplify: In the future we pass IDs. 
        # For now, let's try to find module_id.
        # If we can't find repo, we might need to create it?
        
        # In `process_blame_response`, we need module_id.
        # Let's use `ingestion.get_or_create_module`.
        # But we need repo_id.
        
        repo_obj, _ = Repo.objects.get_or_create(
            name=repo_name,
            defaults={'url': f"https://github.com/{repo_owner}/{repo_name}"}
        )
        
        module_obj = ingestion.get_or_create_module(repo_obj.id, dir_path, dir_path)
        
        ingestion.process_blame_response(module_obj.id, blame_data, file_path)
        
    except Exception as e:
        logger.error(f"Task failed: {e}")
        # Retry on failure, specifically for rate limits or network issues
        try:
             self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
             logger.error("Max retries exceeded for task.")

@shared_task
def initialize_repo(repo_url):
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
        
        # Enqueue jobs
        for fpath in file_paths:
            process_commit_blame.delay(owner, name, commit_sha, fpath)
            
    except Exception as e:
        logger.error(f"Initialization failed for {repo_url}: {e}")
