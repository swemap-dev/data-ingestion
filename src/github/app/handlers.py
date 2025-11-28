import logging
from typing import Dict, Any, Set
from .webhook import WebhookVerifier

logger = logging.getLogger(__name__)


class EventHandlers:
    """Handlers for GitHub webhook events."""
    
    def __init__(self):
        """Initialize event handlers."""
        self.verifier = WebhookVerifier()
    
    def handle_push(self, payload: Dict[str, Any]) -> None:
        """
        Handle push event - code was pushed to a repository.
        Logs the repository, branch, and affected files.
        
        Args:
            payload: Webhook event payload
        """
        repo_info = self.verifier.extract_repository_info(payload)
        if not repo_info:
            logger.warning("Could not extract repository info from push event")
            return
        
        owner = repo_info['owner']
        repo = repo_info['repo']
        repo_full_name = f"{owner}/{repo}"
        
        # Extract branch from ref (e.g., "refs/heads/main" -> "main")
        ref = payload.get('ref', '')
        branch = ref.replace('refs/heads/', '') if ref.startswith('refs/heads/') else ref
        
        # Collect all affected files from all commits
        commits = payload.get('commits', [])
        affected_files: Set[str] = set()
        
        for commit in commits:
            # Get files added, modified, and removed
            added = commit.get('added', [])
            modified = commit.get('modified', [])
            removed = commit.get('removed', [])
            
            affected_files.update(added)
            affected_files.update(modified)
            affected_files.update(removed)
        
        # Log the push event information
        logger.info("=" * 80)
        logger.info(f"Push Event Received")
        logger.info(f"  Repository: {repo_full_name}")
        logger.info(f"  Branch: {branch}")
        logger.info(f"  Commits: {len(commits)}")
        logger.info(f"  Affected Files ({len(affected_files)}):")
        
        if affected_files:
            # Sort files for consistent logging
            for file_path in sorted(affected_files):
                logger.info(f"    - {file_path}")
        else:
            logger.info("    (no files affected)")
        
        logger.info("=" * 80)
    
    def handle_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Route event to appropriate handler.
        Only handles push events; other events are ignored.
        
        Args:
            event_type: Type of GitHub event
            payload: Webhook event payload
        """
        if event_type == 'push':
            try:
                self.handle_push(payload)
            except Exception as e:
                logger.error(f"Error handling push event: {e}", exc_info=True)
        else:
            logger.debug(f"Ignoring event type: {event_type}")
