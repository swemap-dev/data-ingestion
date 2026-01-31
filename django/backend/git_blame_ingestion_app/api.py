from typing import List, Optional
from ninja import NinjaAPI, Schema
from django.http import HttpRequest
import logging

from .tasks import process_commit_blame

logger = logging.getLogger(__name__)

api = NinjaAPI()

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
                print(f"Enqueuing job for {owner}/{name} {fpath}")
                logger.info(f"Enqueuing job for {owner}/{name} {fpath}")
                process_commit_blame.delay(owner, name, commit_hash, fpath)
                enqueued_count += 1
                
        return {"status": "processing", "jobs_enqueued": enqueued_count}
        
    return {"status": "ignored", "reason": f"Event {event} not handled"}
