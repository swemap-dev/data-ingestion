import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from .client import GitHubClient


class FileContentsService:
    def __init__(self, client: GitHubClient):
        self.client = client
        self.session = client.session
        self.base_url = client.base_url
        self.graphql_url = 'https://api.github.com/graphql'
    
    def get_recursive_file_contents(
        self, 
        owner: str, 
        repo: str, 
        ref: Optional[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not ref:
            repo_meta = self.client.get_repository(owner, repo)
            ref = repo_meta.default_branch
        
        commit_sha, tree_sha, commit_data = self._get_tree_sha(owner, repo, ref)
        files_with_shas = self._get_all_files(owner, repo, tree_sha)
        
        result = {}
        for file_path, blob_sha in files_with_shas.items():
            file_data = self._get_file_blame(owner, repo, file_path, blob_sha)
            if file_data:
                result[file_path] = file_data
        
        return result
    
    def _get_tree_sha(self, owner: str, repo: str, ref: str) -> tuple[str, str, Dict[str, Any]]:
        url = f'{self.base_url}/repos/{owner}/{repo}/git/ref/heads/{ref}'
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        commit_sha = response.json()['object']['sha']
        
        url = f'{self.base_url}/repos/{owner}/{repo}/git/commits/{commit_sha}'
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        commit_data = response.json()
        tree_sha = commit_data['tree']['sha']
        return commit_sha, tree_sha, commit_data
    
    def _get_all_files(self, owner: str, repo: str, tree_sha: str) -> Dict[str, str]:
        url = f'{self.base_url}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1'
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        
        tree_data = response.json()
        files = {}
        for item in tree_data.get('tree', []):
            if item['type'] == 'blob':
                files[item['path']] = item['sha']
        
        return files
    
    def _get_file_blame(
        self, 
        owner: str, 
        repo: str, 
        file_path: str, 
        blob_sha: str
    ) -> Optional[List[Dict[str, Any]]]:
        blob_url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{blob_sha}"
        print(f"GET {blob_url}")

        try:
            blob_response = self.session.get(blob_url)
            blob_response.raise_for_status()
            
            blob_data = blob_response.json()
            if blob_data.get('encoding') != 'base64':
                return None
            
            import base64
            file_content = base64.b64decode(blob_data['content']).decode('utf-8', errors='ignore')
            lines = file_content.split('\n')
            
            results = []
            for i, line_content in enumerate(lines, start=1):
                results.append({
                    'line': i,
                    'content': line_content
                })
            
            return results

        except requests.exceptions.RequestException as e:
            print(f"Error fetching blame for {file_path}: {e}")
            return None


