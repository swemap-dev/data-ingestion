import os
import requests
from typing import Optional, Dict, Any
from django.conf import settings
from .repository import RepositoryMetadata

class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or getattr(settings, 'GITHUB_TOKEN', None) or os.getenv('GITHUB_TOKEN')

        self.base_url = 'https://api.github.com'
        self.session = requests.Session()
        
        if self.token:
            self.session.headers.update({
                'Authorization': f'token {self.token}',
                'Accept': 'application/vnd.github.v3+json'
            })
        else:
            self.session.headers.update({
                'Accept': 'application/vnd.github.v3+json'
            })

        # Add Retry Logic
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[403, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
    
    def get_repository_metadata(self, owner: str, repo: str) -> Dict[str, Any]:
        url = f'{self.base_url}/repos/{owner}/{repo}'
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_repository(self, owner: str, repo: str) -> RepositoryMetadata:
        data = self.get_repository_metadata(owner, repo)
        return RepositoryMetadata.from_api_response(data)
