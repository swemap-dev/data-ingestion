import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional
from datetime import datetime
from .client import GitHubClient


class FileContentsService:
    def __init__(self, client: GitHubClient):
        self.client = client
        self.session = client.session
        self.base_url = client.base_url
        self.graphql_url = "https://api.github.com/graphql"

    def get_raw_blame(self, owner: str, repo: str, file_path: str, ref: str = "main") -> List[Dict[str, Any]]:
        """
        Get rich blame data for a specific file using custom GraphQL query.
        Returns a list of blame ranges with commit author info and age.
        """
        query = """
        query GetRichBlame($owner: String!, $repo: String!, $ref: String!, $path: String!) {
          repository(owner: $owner, name: $repo) {
            ref(qualifiedName: $ref) {
              target {
                ... on Commit {
                  blame(path: $path) {
                    ranges {
                      commit {
                        oid
                        author {
                          name
                          email
                        }
                      }
                      startingLine
                      endingLine
                      age
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        variables = {"owner": owner, "repo": repo, "ref": ref, "path": file_path}

        # Use session's existing headers including Authorization
        headers = {"Content-Type": "application/json"}
        
        try:
            response = self.session.post(
                self.graphql_url, headers=headers, json={"query": query, "variables": variables}
            )
            response.raise_for_status()
            
            data = response.json()
            
            if "errors" in data:
                print(f"GraphQL errors: {data['errors']}")
                return []

            # Inject metadata requested by user
            try:
                if 'data' in data and 'repository' in data['data']:
                    data['data']['repository']['repo_name'] = repo
                    data['data']['repository']['file_name'] = file_path
            except Exception as e:
                print(f"Error injecting metadata: {e}")

            return data
            
        except Exception as e:
            print(f"Error fetching blame: {e}")
            return []

    def get_recursive_file_contents(
        self, owner: str, repo: str, ref: Optional[str] = None, max_workers: Optional[int] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not ref:
            repo_meta = self.client.get_repository(owner, repo)
            ref = repo_meta.default_branch

        commit_sha, tree_sha, commit_data = self._get_tree_sha(owner, repo, ref)
        files_with_shas = self._get_all_files(owner, repo, tree_sha)

        result = {}
        
        # Process files in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all file processing tasks
            future_to_file = {
                executor.submit(self._get_file_blame, owner, repo, file_path, blob_sha, ref): file_path
                for file_path, blob_sha in files_with_shas.items()
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    file_data = future.result()
                    if file_data:
                        result[file_path] = file_data
                except Exception as e:
                    print(f"Error processing file {file_path}: {e}")

        return result

    def _get_tree_sha(
        self, owner: str, repo: str, ref: str
    ) -> tuple[str, str, Dict[str, Any]]:
        url = f"{self.base_url}/repos/{owner}/{repo}/git/ref/heads/{ref}"
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        commit_sha = response.json()["object"]["sha"]

        url = f"{self.base_url}/repos/{owner}/{repo}/git/commits/{commit_sha}"
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()
        commit_data = response.json()
        tree_sha = commit_data["tree"]["sha"]
        return commit_sha, tree_sha, commit_data

    def _get_all_files(self, owner: str, repo: str, tree_sha: str) -> Dict[str, str]:
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1"
        print(f"GET {url}")
        response = self.session.get(url)
        response.raise_for_status()

        tree_data = response.json()
        files = {}
        for item in tree_data.get("tree", []):
            if item["type"] == "blob":
                files[item["path"]] = item["sha"]

        return files

    def _get_blame_via_graphql(
        self, owner: str, repo: str, file_path: str, ref: str
    ) -> Optional[Dict[int, str]]:
        """Get blame data via GraphQL API and return a mapping of line number to commit SHA."""
        query = """
        query GetBlameData($owner: String!, $repo: String!, $ref: String!, $path: String!) {
          repository(owner: $owner, name: $repo) {
            ref(qualifiedName: $ref) {
              target {
                ... on Commit {
                  blame(path: $path) {
                    ranges {
                      startingLine
                      endingLine
                      commit {
                        oid
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        variables = {"owner": owner, "repo": repo, "ref": ref, "path": file_path}

        payload = {"query": query, "variables": variables}

        # Just add Content-Type, use session's existing Authorization header
        headers = {"Content-Type": "application/json"}

        thread_id = threading.get_ident()
        print(f"[Thread {thread_id}] POST {self.graphql_url} (GraphQL blame for {file_path})")

        try:
            # Use session's existing headers (including Authorization)
            response = self.session.post(
                self.graphql_url, headers=headers, json=payload
            )
            response.raise_for_status()

            data = response.json()

            # Check for GraphQL errors
            if "errors" in data:
                print(f"GraphQL errors for {file_path}: {data['errors']}")
                return None

            # Extract blame ranges from GraphQL response
            blame_data = (
                data.get("data", {})
                .get("repository", {})
                .get("ref", {})
                .get("target", {})
            )
            if not blame_data:
                return None

            blame_ranges = blame_data.get("blame", {}).get("ranges", [])
            if not blame_ranges:
                return None

            # Create a mapping of line number to commit SHA
            line_to_commit = {}
            for range_data in blame_ranges:
                commit_sha = range_data["commit"]["oid"]
                starting_line = range_data["startingLine"]
                ending_line = range_data["endingLine"]

                # startingLine and endingLine are 1-indexed and inclusive
                for line_num in range(starting_line, ending_line + 1):
                    line_to_commit[line_num] = commit_sha

            return line_to_commit

        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch blame via GraphQL for {file_path}: {e}")
            return None

    def _get_file_blame(
        self, owner: str, repo: str, file_path: str, blob_sha: str, ref: str
    ) -> Optional[List[Dict[str, Any]]]:
        blob_url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{blob_sha}"
        thread_id = threading.get_ident()
        print(f"[Thread {thread_id}] GET {blob_url} (file: {file_path})")

        try:
            # Get file contents
            blob_response = self.session.get(blob_url)
            blob_response.raise_for_status()

            blob_data = blob_response.json()
            if blob_data.get("encoding") != "base64":
                return None

            import base64

            file_content = base64.b64decode(blob_data["content"]).decode(
                "utf-8", errors="ignore"
            )
            lines = file_content.split("\n")
            # Remove empty last line if file ends with newline
            if lines and lines[-1] == "":
                lines = lines[:-1]

            # Get blame information via GraphQL
            line_to_commit = self._get_blame_via_graphql(owner, repo, file_path, ref)
            if line_to_commit is None:
                line_to_commit = {}

            results = []
            for i, line_content in enumerate(lines, start=1):
                result_line = {"line": i, "content": line_content}
                # Add commit SHA if available from blame data
                if i in line_to_commit:
                    result_line["commit_sha"] = line_to_commit[i]

                results.append(result_line)

            return results

        except requests.exceptions.RequestException as e:
            print(f"Error fetching file for {file_path}: {e}")
            return None
