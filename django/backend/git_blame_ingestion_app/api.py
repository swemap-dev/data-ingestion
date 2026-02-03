from typing import List, Optional
from ninja import NinjaAPI, Schema
from django.http import HttpRequest
import logging

from .tasks import process_commit_blame, initialize_all
from .models import Module
from code_ownership.api import router as ownership_router

logger = logging.getLogger(__name__)

api = NinjaAPI()
api.add_router("/ownership", ownership_router)

class ModuleSchema(Schema):
    module_id: int
    module_name: str

@api.get("/modules", response=List[ModuleSchema])
def get_all_modules(request):
    # TODO: a module with empty 'module_name' somehow got added to the DB; hardcode filter for now
    # modules = Modules.objects.all()
    modules = Module.objects.exclude(name__isnull=True).exclude(name__exact='')
    return [{"module_id": m.id, "module_name": m.name} for m in modules]

class RepoSchema(Schema):
    id: int
    name: str
    owner: str
    url: Optional[str] = None

@api.get("/repos", response=List[RepoSchema])
def get_all_repos(request):
    from .models import Repo
    repos = Repo.objects.all()
    return list(repos)

class CommitInfo(Schema):
    id: str
    modified: List[str] = []
    added: List[str] = []

class RepositoryInfo(Schema):
    full_name: str

class WebhookPayload(Schema):
    repository: RepositoryInfo
    commits: List[CommitInfo]

@api.post("/webhook")
def webhook(request: HttpRequest, payload: WebhookPayload):
    """
    Receives GitHub App Webhook events.
    Currently handles 'push' events.
    """
    event = request.headers.get("X-GitHub-Event", "ping")
    
    if event == "ping":
        return {"status": "pong"}
        
    if event == "push":
        repo_full_name = payload.repository.full_name
        try:
            owner, name = repo_full_name.split('/')
        except ValueError:
            return api.create_response(request, {"error": "Invalid repo name format"}, status=400)
            
        enqueued_count = 0
        
        for commit in payload.commits:
            commit_hash = commit.id
            changed_files = commit.added + commit.modified
            
            for fpath in changed_files:
                # Security Check: Only process if we know this repo
                # This prevents "leakage" where we process webhooks for random repos 
                # that just happen to point to our webhook URL
                from .models import Repo
                try:
                    repo = Repo.objects.get(owner=owner, name=name)
                    print(f"Enqueuing job for {owner}/{name} {fpath}")
                    logger.info(f"Enqueuing job for {owner}/{name} {fpath}")
                    process_commit_blame.delay(owner, name, commit_hash, fpath)
                    enqueued_count += 1
                except Repo.DoesNotExist:
                     print(f"Skipping webhook for unknown repo: {owner}/{name}")
                     logger.warning(f"Skipping webhook for unknown repo: {owner}/{name}")
                     continue
                
        return {"status": "processing", "jobs_enqueued": enqueued_count}
        
    return {"status": "ignored", "reason": f"Event {event} not handled"}

@api.post("/init-all")
def init_all(request):
    """
    Triggers initialization for all default repositories.
    """
    result = initialize_all.delay()
    return {"status": "triggered", "task_id": result.id}
