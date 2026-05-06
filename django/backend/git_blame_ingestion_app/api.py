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

@api.get("/health")
def health_check(request):
    """Used by cron-job.org to keep the free Render server awake before midnight"""
    try:
        import subprocess
        import sys
        pip_freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"]).decode("utf-8").split("\n")
        sys_path = sys.path
    except Exception as e:
        pip_freeze = str(e)
        sys_path = []
        
    return {
        "status": "awake",
        "sys_path": sys_path,
        "pip_freeze": pip_freeze
    }

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
        enqueued_count = 0
        
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

class InitRepoSchema(Schema):
    repo_url: str
    ref: Optional[str] = None

@api.post("/init-repo")
def init_repo(request, payload: InitRepoSchema):
    """
    Triggers initialization for a specific repository URL.
    Optionally accepts a ref (branch or SHA) to pin ingestion.
    """
    from .tasks import initialize
    result = initialize.delay(payload.repo_url, ref=payload.ref)
    return {"status": "triggered", "task_id": result.id, "repo": payload.repo_url}

class InitAllSchema(Schema):
    ref: Optional[str] = None

# TODO: the repos in initialize_all() are hardcoded; change to be configurable

@api.post("/init-all")
def init_all(request, payload: InitAllSchema = None):
    """
    Triggers initialization for all default repositories.
    Optionally accepts a ref (branch or SHA) to pin ingestion.
    """
    result = initialize_all.delay()
    return {"status": "triggered", "task_id": result.id}

class SyncIncrementalSchema(Schema):
    repo_id: Optional[int] = None

@api.post("/sync-incremental")
def trigger_incremental_sync(request, payload: SyncIncrementalSchema = None):
    """
    Triggers incremental sync for a specific repository, or all repositories if not provided.
    """
    repo_id = payload.repo_id if payload else None
    from .tasks import incremental_sync
    result = incremental_sync.delay(repo_id=repo_id)
    return {"status": "triggered", "task_id": result.id}


def _build_module_tree(module):
    """Recursively builds a nested dict for a module and its children."""
    children = module.children.all().order_by('name')
    return {
        "module_id": module.id,
        "module_name": module.name or "ROOT",
        "dir_path": module.dir_path or "",
        "children": [_build_module_tree(child) for child in children],
    }

@api.get("/modules/tree")
def get_module_tree(request, repo_id: int):
    """
    Returns the module hierarchy as a nested JSON tree.
    Root modules (parent=None) are the top-level nodes.
    """
    root_modules = Module.objects.filter(
        repo_id=repo_id, parent__isnull=True
    ).order_by('name')

    return [_build_module_tree(m) for m in root_modules]

