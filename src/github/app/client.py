import requests
from typing import Optional, Dict, Any
from .auth import GitHubApp
from ..models import RepositoryMetadata


class GitHubAppClient:
    """GitHub API client using App authentication instead of personal access tokens."""
    
    def __init__(self, app: Optional[GitHubApp] = None, installation_id: Optional[int] = None):
        """
        Initialize GitHub App client.
        
        Args:
            app: GitHubApp instance (creates one if not provided)
            installation_id: Installation ID (optional, will be fetched if needed)
        """
        self.app = app or GitHubApp()
        self.installation_id = installation_id
        self.base_url = 'https://api.github.com'
        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
    
    def _get_token(self) -> str:
        """Get a valid installation token, refreshing if necessary."""
        import time
        
        # Check if we have a valid token (with 5 minute buffer)
        if self._token and self._token_expires_at and time.time() < (self._token_expires_at - 300):
            return self._token
        
        # Get new token
        self._token = self.app.get_installation_token(self.installation_id)
        
        # Tokens expire in 1 hour, but we'll refresh after 55 minutes
        self._token_expires_at = time.time() + (55 * 60)
        
        # Update session headers
        self.session.headers.update({
            'Authorization': f'token {self._token}',
            'Accept': 'application/vnd.github.v3+json'
        })
        
        return self._token
    
    def get_repository_metadata(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Get repository metadata from GitHub API.
        
        Args:
            owner: Repository owner
            repo: Repository name
        
        Returns:
            Repository metadata dictionary
        """
        self._get_token()  # Ensure we have a valid token
        
        url = f'{self.base_url}/repos/{owner}/{repo}'
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_repository(self, owner: str, repo: str) -> RepositoryMetadata:
        """
        Get repository metadata as RepositoryMetadata object.
        
        Args:
            owner: Repository owner
            repo: Repository name
        
        Returns:
            RepositoryMetadata instance
        """
        data = self.get_repository_metadata(owner, repo)
        return RepositoryMetadata.from_api_response(data)

