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

    def get_raw_blame(self, owner: str, repo: str, file_path: str, ref: str = "main") -> Dict[str, Any]:
        """
        Get rich blame data for a specific file using custom GraphQL query.
        Returns blame data dictionary with commit author info and age.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            file_path (str): Path to the file.
            ref (str): Branch or commit reference (default: "main").

        Returns:
            Dict[str, Any]: A dictionary containing blame ranges and metadata.
        """
        query = """
        query GetRichBlame($owner: String!, $repo: String!, $ref: String!, $path: String!) {
          repository(owner: $owner, name: $repo) {
            ref(qualifiedName: $ref) {
              target {
                ... on Commit {
                  blame(path: $path) {
                    ranges {
                      commit { id oid author { name email } }
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
        
        # No broad try/except block, let requests exceptions propagate to the caller (Task)
        response = self.session.post(
            self.graphql_url, headers=headers, json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        
        data = response.json()
        
        if "errors" in data:
            print(f"GraphQL errors: {data['errors']}")
            # Ideally raise an exception here too if it's a fatal error
            return {}

        # ---------------------------------------------------------
        # Batch fetch reviewers for all unique commits found
        # ---------------------------------------------------------
        try:
            # 1. Extract unique commit IDs
            commit_ids = set()
            
            # Safer extraction
            repo_data = data.get('data', {}).get('repository')
            if repo_data:
                ref_data = repo_data.get('ref')
                if ref_data:
                    target = ref_data.get('target')
                    if target:
                        blame = target.get('blame')
                        if blame:
                            ranges = blame.get('ranges', [])
                            for r in ranges:
                                c_id = r.get('commit', {}).get('id')
                                if c_id:
                                    commit_ids.add(c_id)
            
                            # 2. Fetch reviewers if we have any commits
                            reviewers_map = {}
                            if commit_ids:
                                # Fetch valid reviewers for all commits
                                # Parallelized inside _get_reviewers_for_commits to handle large sets efficiently
                                reviewers_map = self._get_reviewers_for_commits(list(commit_ids))

                            # 3. Inject reviewers back into the response data structure
                            for r in ranges:
                                c = r.get('commit', {})
                                c_id = c.get('id')
                                if c_id and c_id in reviewers_map:
                                    c['reviewers'] = reviewers_map[c_id]
                    
        except Exception as e:
            print(f"Error fetching/injecting reviewers: {e}")

        # Inject metadata requested by user
        try:
            if 'data' in data and 'repository' in data['data']:
                data['data']['repository']['repo_name'] = repo
                data['data']['repository']['file_name'] = file_path
        except Exception as e:
            print(f"Error injecting metadata: {e}")

        return data

    def _get_reviewers_for_commits(self, commit_ids: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """
        Fetch associated Pull Request reviews for a list of commit Node IDs.
        Returns a map: commit_id -> list of reviewer dicts ({name, email}).
        Uses parallel execution for batches to handle large datasets efficiently.

        Parameters:
            commit_ids (List[str]): List of commit IDs (GraphQL Node IDs).

        Returns:
            Dict[str, List[Dict[str, str]]]: A mapping of commit_id to a list of reviewer details.
        """
        if not commit_ids:
            return {}

        # Chunk the IDs
        CHUNK_SIZE = 50
        chunks = [commit_ids[i : i + CHUNK_SIZE] for i in range(0, len(commit_ids), CHUNK_SIZE)]
        
        results = {}
        
        # Max workers for parallel batch requests
        MAX_WORKERS = 10
        
        def fetch_chunk(chunk_ids):
            chunk_results = {}
            query = """
            query GetCommitReviewers($ids: [ID!]!) {
              nodes(ids: $ids) {
                ... on Commit {
                  id
                  associatedPullRequests(first: 1) {
                # LIMITATION: Only fetching the first associated PR.
                # A commit can belong to multiple PRs (e.g. if a branch is merged into multiple target branches,
                # or if a PR is closed and a new one opened with the same branch).
                # We assume the first one returned is sufficiently representative for finding the reviewer.
                    nodes {
                      reviews(first: 10) {
                        nodes {
                          author {
                            ... on User { name email login }
                            ... on Bot { login }
                          }
                          state
                          submittedAt
                        }
                      }
                    }
                  }
                }
              }
            }
            """
            
            # Create a new local variable for headers just in case
            headers = {"Content-Type": "application/json"}
            variables = {"ids": chunk_ids}
            
            retries = 3
            backoff = 2
            
            for attempt in range(retries + 1):
                try:
                    # self.session's connection pool is thread-safe for concurrent API calls
                    response = self.session.post(
                        self.graphql_url, headers=headers, json={"query": query, "variables": variables}
                    )
                    
                    if response.status_code == 429:
                        if attempt < retries:
                            import time
                            sleep_time = backoff ** attempt
                            print(f"Rate limited (429). Retrying in {sleep_time}s...")
                            time.sleep(sleep_time)
                            continue
                        else:
                            print("Rate limited (429) - Max retries reached for chunk.")
                            return {}

                    response.raise_for_status()
                    data = response.json()

                    if "errors" in data:
                        print(f"GraphQL errors in _get_reviewers_for_commits chunk: {data['errors']}")
                        return {}

                    nodes = data.get("data", {}).get("nodes", [])
                    for node in nodes:
                        if not node: 
                            continue
                            
                        c_id = node.get("id")
                        reviewers = []
                        
                        prs = node.get("associatedPullRequests", {}).get("nodes", [])
                        if prs:
                            pr = prs[0]
                            reviews = pr.get("reviews", {}).get("nodes", [])
                            
                            seen_authors = set()
                            for review in reviews:
                                author = review.get("author")
                                if not author:
                                    continue
                                    
                                login = author.get("login")
                                if login and login not in seen_authors:
                                    seen_authors.add(login)
                                    reviewer_info = {
                                        "name": author.get("name"),
                                        "email": author.get("email"),
                                        "login": login,
                                        "submittedAt": review.get("submittedAt"),
                                        "state": review.get("state")
                                    }
                                    reviewers.append(reviewer_info)
                        
                        chunk_results[c_id] = reviewers
                    
                    return chunk_results # Success

                except Exception as e:
                    print(f"Error fetching reviewers chunk (Attempt {attempt+1}/{retries+1}): {e}")
                    if attempt < retries:
                         import time
                         time.sleep(1) # Simple short sleep for non-429 errors
            
            return {}

        # Execute chunks in parallel
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_chunk = {executor.submit(fetch_chunk, chunk): chunk for chunk in chunks}
            
            for future in as_completed(future_to_chunk):
                try:
                    chunk_data = future.result()
                    results.update(chunk_data)
                except Exception as e:
                    print(f"Chunk processing failed: {e}")

        return results

    def get_all_file_paths(self, owner: str, repo: str, ref: str = "main") -> List[str]:
        """
        Get a list of all file paths in the repository.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            ref (str): Reference name (e.g., "main").

        Returns:
            List[str]: A list of file paths.
        """
        try:
            commit_sha, tree_sha, _ = self._get_tree_sha(owner, repo, ref)
            files = self._get_all_files(owner, repo, tree_sha)
            return list(files.keys())
        except Exception as e:
            print(f"Error getting file paths for {owner}/{repo}: {e}")
            return []

    def get_recursive_file_contents(
        self, owner: str, repo: str, ref: Optional[str] = None, max_workers: Optional[int] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Recursively get file contents for a whole repository.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            ref (Optional[str]): Branch or commit reference. If None, uses default branch.
            max_workers (Optional[int]): Max threads for parallel processing.

        Returns:
             Dict[str, List[Dict[str, Any]]]: Dictionary mapping file paths to their content and blame info.
        """
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
        """
        Get the tree SHA for a given reference.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            ref (str): Reference name (e.g., "main").

        Returns:
            tuple[str, str, Dict[str, Any]]: A tuple containing (commit_sha, tree_sha, commit_data).
        """
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
        """
        Get all files in a tree recursively.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            tree_sha (str): The SHA of the tree to traverse.

        Returns:
            Dict[str, str]: A dictionary mapping file paths to their blob SHAs.
        """
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
        """
        Get blame data via GraphQL API and return a mapping of line number to commit SHA.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            file_path (str): Path to the file.
            ref (str): Reference name.

        Returns:
            Optional[Dict[int, str]]: A dictionary mapping line numbers to commit SHAs, or None if failed.
        """
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
        """
        Fetch file content and blame data for a single file.

        Parameters:
            owner (str): Repository owner.
            repo (str): Repository name.
            file_path (str): Path to the file.
            blob_sha (str): SHA of the file blob.
            ref (str): Reference name.

        Returns:
            Optional[List[Dict[str, Any]]]: List of lines with content and commit SHA, or None if failed.
        """
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
