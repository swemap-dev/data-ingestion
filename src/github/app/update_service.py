import logging
from typing import Optional, Dict, Any
from .client import GitHubAppClient
from ..models import RepositoryMetadata

logger = logging.getLogger(__name__)


class UpdateService:
    """Service to fetch and process repository metadata updates."""
    
    def __init__(self, app_client: Optional[GitHubAppClient] = None):
        """
        Initialize update service.
        
        Args:
            app_client: GitHubAppClient instance (creates one if not provided)
        """
        self.app_client = app_client or GitHubAppClient()
    
    def fetch_repository_metadata(self, owner: str, repo: str) -> Optional[RepositoryMetadata]:
        """
        Fetch latest repository metadata from GitHub.
        
        Args:
            owner: Repository owner
            repo: Repository name
        
        Returns:
            RepositoryMetadata instance or None if fetch fails
        """
        try:
            logger.info(f"Fetching repository metadata for {owner}/{repo}")
            metadata = self.app_client.get_repository(owner, repo)
            logger.info(f"Successfully fetched metadata for {owner}/{repo}: {metadata.name}")
            return metadata
        except Exception as e:
            logger.error(f"Failed to fetch repository metadata for {owner}/{repo}: {e}")
            return None
    
    def process_repository_update(self, owner: str, repo: str, event_type: str) -> None:
        """
        Process a repository update event.
        
        Args:
            owner: Repository owner
            repo: Repository name
            event_type: Type of event that triggered the update
        """
        logger.info(f"Processing {event_type} event for {owner}/{repo}")
        
        # Fetch latest metadata
        metadata = self.fetch_repository_metadata(owner, repo)
        
        if not metadata:
            logger.warning(f"Could not fetch metadata for {owner}/{repo}, skipping update")
            return
        
        # Log the metadata that would be written to database
        logger.info(f"Repository metadata for {owner}/{repo}:")
        logger.info(f"  - ID: {metadata.id}")
        logger.info(f"  - Name: {metadata.name}")
        logger.info(f"  - Full Name: {metadata.full_name}")
        logger.info(f"  - Description: {metadata.description}")
        logger.info(f"  - Language: {metadata.language}")
        logger.info(f"  - Stars: {metadata.stars}")
        logger.info(f"  - Forks: {metadata.forks}")
        logger.info(f"  - Watchers: {metadata.watchers}")
        logger.info(f"  - Open Issues: {metadata.open_issues}")
        logger.info(f"  - Default Branch: {metadata.default_branch}")
        logger.info(f"  - Is Private: {metadata.is_private}")
        logger.info(f"  - Is Fork: {metadata.is_fork}")
        logger.info(f"  - Is Archived: {metadata.is_archived}")
        logger.info(f"  - Created At: {metadata.created_at}")
        logger.info(f"  - Updated At: {metadata.updated_at}")
        logger.info(f"  - Pushed At: {metadata.pushed_at}")
        logger.info(f"  - Size: {metadata.size}")
        logger.info(f"  - License: {metadata.license}")
        
        # TODO: Write/update repository metadata in database
        # Example:
        # db.update_repository_metadata(
        #     repository_id=metadata.id,
        #     owner=owner,
        #     repo=repo,
        #     metadata=metadata,
        #     updated_by_event=event_type
        # )
        
        logger.info(f"Successfully processed {event_type} event for {owner}/{repo}")

