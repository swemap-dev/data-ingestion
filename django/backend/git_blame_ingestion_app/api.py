from typing import List, Optional
from ninja import NinjaAPI, Schema
from django.http import HttpRequest
import logging

from celery import chord
from .tasks import process_commit_blame, initialize_all, recalculate_affected_modules
from .models import Module
from code_ownership.api import router as ownership_router
from risk_dashboard.api import router as risk_router

logger = logging.getLogger(__name__)

api = NinjaAPI()
api.add_router("/ownership", ownership_router)
api.add_router("/risk", risk_router)

class ModuleSchema(Schema):
    module_id: int
    module_name: str

@api.get("/modules", response=List[ModuleSchema])
def get_all_modules(request):
    # TODO: a module with empty 'module_name' somehow got added to the DB; hardcode filter for now
    # modules = Modules.objects.all()
    modules = Module.objects.exclude(name__isnull=True).exclude(name__exact='')
    return [{"module_id": m.id, "module_name": m.name} for m in modules]

class FileSchema(Schema):
    id: int
    file_path: str
    line_count: Optional[int] = None

@api.get("/modules/{module_id}/files", response=List[FileSchema])
def get_module_files(request, module_id: int):
    from .models import File
    files = File.objects.filter(module_id_id=module_id)
    return list(files)

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
            
        from .models import Repo
        try:
            repo = Repo.objects.get(owner=owner, name=name)
        except Repo.DoesNotExist:
            return api.create_response(request, {"error": "Unknown repo"}, status=404)
            
        all_tasks = []
        affected_module_ids = set()

        import os
        from .services.module_resolver import ModuleResolver
        from .services import ingestion

        for commit in payload.commits:
            commit_hash = commit.id
            changed_files = commit.added + commit.modified

            # Create any new modules introduced in this commit
            new_modules = set()
            for fpath in changed_files:
                dirname, basename = os.path.split(fpath)
                if basename in ModuleResolver.MODULE_MARKERS:
                    resolver = ModuleResolver([]) # Dummy instance just to check ignored dirs
                    if not resolver._is_ignored(dirname):
                        new_modules.add(dirname)

            for d in new_modules:
                name_for_module = d if d else "ROOT"
                logger.info(f"Webhook detected new module marker in '{name_for_module}'. Creating preemptively.")
                ingestion.get_or_create_module(repo.id, name_for_module, d)

            # Collect blame tasks and resolve affected modules
            for fpath in changed_files:
                logger.info(f"Enqueuing job for {owner}/{name} {fpath}")
                all_tasks.append(process_commit_blame.s(owner, name, commit_hash, fpath))
                module_id = ingestion.resolve_module_from_db(repo.id, fpath)
                if module_id:
                    affected_module_ids.add(module_id)

        if all_tasks:
            chord(all_tasks)(recalculate_affected_modules.si(list(affected_module_ids)))

        return {"status": "processing", "jobs_enqueued": len(all_tasks)}
        
    return {"status": "ignored", "reason": f"Event {event} not handled"}

# TODO: the repos in initialize_all() are hardcoded; change to be configurable
@api.post("/init-all")
def init_all(request):
    """
    Triggers initialization for all default repositories.
    """
    result = initialize_all.delay()
    return {"status": "triggered", "task_id": result.id}
