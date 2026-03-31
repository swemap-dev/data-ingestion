import os
import sys
import requests
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

if __name__ == "__main__":
    # Allow running directly for testing
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', '.env'))
    from git_blame_ingestion_app.services.repository import RepositoryMetadata

    class _FakeSettings:
        GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
    settings = _FakeSettings()
else:
    from django.conf import settings
    from .repository import RepositoryMetadata


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or getattr(settings, 'GITHUB_TOKEN', None) or os.getenv('GITHUB_TOKEN')

        self.base_url = 'https://api.github.com/graphql'
        self.queries_dir = Path(__file__).parent / "queries"
        self.session = requests.Session()
        
        if self.token:
            self.session.headers.update({
                'Authorization': f'bearer {self.token}',
                'Content-Type': 'application/json',
                'Accept': 'application/vnd.github.v3+json',
            })
        else:
            self.session.headers.update({
                'Content-Type': 'application/json',
                'Accept': 'application/vnd.github.v3+json',
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

    
    def _load_query(self, name: str) -> str:
        """Load a GraphQL query from the queries/ directory by filename (without extension)."""
        path = self.queries_dir / f"{name}.graphql"
        if not path.exists():
            raise FileNotFoundError(f"Query file not found: {path}")
        return path.read_text()
    
    
    def _request(self, query: str, variables: dict) -> dict:
        """Send a GraphQL request and return the parsed JSON response."""
        payload = {"query": query, "variables": variables}

        try:
            response = self.session.post(self.base_url, json=payload)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"GitHub API error {e.response.status_code}: {e.response.text}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"GitHub API request failed: {e}")

        if "errors" in data:
            messages = [err["message"] for err in data["errors"]]
            raise RuntimeError(f"GraphQL errors: {'; '.join(messages)}")

        return data["data"]


        
    def get_repository_metadata(self, owner: str, repo: str) -> Dict[str, Any]:
        """Fetch repository metadata (name, description, stars, languages, etc.)."""
        query = self._load_query("repository_metadata")
        data = self._request(query, {"owner": owner, "repo": repo})
        return data["repository"]
    

    def get_repository(self, owner: str, repo: str) -> RepositoryMetadata:
        """Fetch repository metadata and return it as a RepositoryMetadata object."""
        data = self.get_repository_metadata(owner, repo)
        return RepositoryMetadata.from_graphql_response(data)
    

    def get_merged_pulls(self, owner: str, repo: str, since: datetime) -> list:
        """Fetch merged PRs updated since the given datetime.

        The query orders by UPDATED_AT DESC and stops paginating once all PRs
        on a page were updated before `since`, matching the original REST logic.
        Files for each PR (up to 100) are included inline.
        """
        query = self._load_query("merged_prs")
        merged_pulls = []
        cursor = None

        while True:
            data = self._request(query, {
                "owner": owner,
                "repo": repo,
                "first": 100,
                "after": cursor,
            })

            pr_connection = data["repository"]["pullRequests"]
            nodes = pr_connection["nodes"]

            all_before_since = True
            for pr in nodes:
                updated_at = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
                if updated_at < since:
                    continue

                all_before_since = False
                merged_at = datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
                if merged_at >= since:
                    # Extract inline file paths from the files subfield
                    files_conn = pr.get("files", {})
                    file_nodes = files_conn.get("nodes", [])
                    pr["_file_paths"] = [f["path"] for f in file_nodes]
                    pr["_files_truncated"] = files_conn.get("pageInfo", {}).get("hasNextPage", False)
                    merged_pulls.append(pr)

            if all_before_since or not pr_connection["pageInfo"]["hasNextPage"]:
                break

            cursor = pr_connection["pageInfo"]["endCursor"]

        return merged_pulls
    



if __name__ == "__main__":
    from datetime import timedelta, timezone

    TOKEN = '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'
    OWNER = "swemap-dev"
    REPO = "data-ingestion"

    client = GitHubClient(TOKEN)

    # Fetch PRs merged in the last 30 days
    since = datetime.now(timezone.utc) - timedelta(days=30)
    prs = client.get_merged_pulls(OWNER, REPO, since)

    print(f"Found {len(prs)} merged PRs since {since.date()}\n")
    print(f"{'#':<6} {'Merged At':<22} {'Author':<16} {'Title'}")
    print("-" * 80)
    for pr in prs:
        author = pr["author"]["login"] if pr["author"] else "unknown"
        print(f"#{pr['number']:<5} {pr['mergedAt']:<22} {author:<16} {pr['title']}")

    # Show inline files for the first PR as a demo
    if prs:
        pr_num = prs[0]["number"]
        files = prs[0].get("_file_paths", [])
        truncated = prs[0].get("_files_truncated", False)
        print(f"\nFiles changed in PR #{pr_num} ({len(files)} inline):")
        for f in files:
            print(f"  {f}")
        if truncated:
            print(f"  ... (PR has >100 files, list truncated)")