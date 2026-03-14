import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional

from .client import GitHubClient

logger = logging.getLogger(__name__)


class FileContentsServiceGQL:
    """
    Pure-GraphQL replacement for FileContentsService.
    All GitHub API calls go through GitHubClient._request().
    Queries are loaded from .graphql files via GitHubClient._load_query().
    """

    _TREE_BATCH_SIZE = 80

    def __init__(self, client: GitHubClient):
        self.client = client

    # ------------------------------------------------------------------
    # Public API (matches FileContentsService)
    # ------------------------------------------------------------------

    def get_file_content(self, owner: str, repo: str, file_path: str, ref: str = "main") -> Optional[bytes]:
        """Fetch raw file content bytes from GitHub via GraphQL."""
        query = self.client._load_query("file_content")
        expression = f"{ref}:{file_path}"
        try:
            data = self.client._request(query, {
                "owner": owner, "repo": repo, "expression": expression,
            })
            blob = data["repository"]["object"]
            if blob is None:
                return None
            text = blob.get("text")
            if text is None:  # binary file
                return None
            return text.encode("utf-8")
        except Exception as e:
            logger.warning(f"Error fetching file content for {file_path}: {e}")
            return None

    def get_raw_blame(self, owner: str, repo: str, file_path: str, ref: str = "main") -> Dict[str, Any]:
        """
        Get rich blame data for a specific file using GraphQL.
        Returns blame data dictionary with commit author info and age.
        Return shape mirrors FileContentsService: {"data": {"repository": {…}}}
        """
        query = self.client._load_query("rich_blame")
        variables = {"owner": owner, "repo": repo, "ref": ref, "path": file_path}

        try:
            result = self.client._request(query, variables)
        except RuntimeError as e:
            logger.warning(f"GraphQL errors for blame on {file_path}: {e}")
            return {}

        # Wrap in {"data": ...} to match the return shape expected by callers
        data = {"data": result}

        # Batch-fetch reviewers for all unique commits
        try:
            commit_ids = set()
            repo_data = result.get("repository")
            if repo_data:
                ref_data = repo_data.get("ref")
                if ref_data:
                    target = ref_data.get("target")
                    if target:
                        blame = target.get("blame")
                        if blame:
                            ranges = blame.get("ranges", [])
                            for r in ranges:
                                c_id = r.get("commit", {}).get("id")
                                if c_id:
                                    commit_ids.add(c_id)

                            reviewers_map = {}
                            if commit_ids:
                                reviewers_map = self._get_reviewers_for_commits(list(commit_ids))

                            for r in ranges:
                                c = r.get("commit", {})
                                c_id = c.get("id")
                                if c_id and c_id in reviewers_map:
                                    c["reviewers"] = reviewers_map[c_id]
        except Exception as e:
            logger.warning(f"Error fetching/injecting reviewers: {e}")

        # Inject metadata
        try:
            if "repository" in result:
                result["repository"]["repo_name"] = repo
                result["repository"]["file_name"] = file_path
        except Exception as e:
            logger.warning(f"Error injecting metadata: {e}")

        return data

    def get_all_file_paths(self, owner: str, repo: str, ref: str = "main") -> List[str]:
        """Get a list of all file paths in the repository."""
        try:
            files = self._get_all_files(owner, repo, ref)
            return list(files.keys())
        except Exception as e:
            logger.warning(f"Error getting file paths for {owner}/{repo}: {e}")
            return []

    def get_recursive_file_contents(
        self, owner: str, repo: str, ref: Optional[str] = None, max_workers: Optional[int] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Recursively get file contents and blame for every file in a repo."""
        if not ref:
            repo_meta = self.client.get_repository(owner, repo)
            ref = repo_meta.default_branch

        files_with_oids = self._get_all_files(owner, repo, ref)

        result = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(self._get_file_blame, owner, repo, file_path, ref): file_path
                for file_path in files_with_oids
            }
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    file_data = future.result()
                    if file_data:
                        result[file_path] = file_data
                except Exception as e:
                    logger.warning(f"Error processing file {file_path}: {e}")

        return result

    def _get_tree_sha(
        self, owner: str, repo: str, ref: str
    ) -> tuple[str, str, Dict[str, Any]]:
        """Get commit SHA and tree SHA for a ref via GraphQL."""
        query = self.client._load_query("ref_commit")
        data = self.client._request(query, {"owner": owner, "repo": repo, "ref": ref})
        target = data["repository"]["ref"]["target"]
        commit_sha = target["oid"]
        tree_sha = target["tree"]["oid"]
        return commit_sha, tree_sha, target

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_all_files(self, owner: str, repo: str, ref: str) -> Dict[str, str]:
        """Walk the repository tree via GraphQL and return {path: oid} for all blobs."""
        files: Dict[str, str] = {}
        dirs_to_visit: List[str] = [""]  # start at root

        while dirs_to_visit:
            batch = dirs_to_visit[: self._TREE_BATCH_SIZE]
            dirs_to_visit = dirs_to_visit[self._TREE_BATCH_SIZE:]

            entries_by_dir = self._batch_tree_entries(owner, repo, ref, batch)

            for dir_path, entries in entries_by_dir.items():
                for entry in entries:
                    child_path = f"{dir_path}/{entry['name']}" if dir_path else entry["name"]
                    if entry["type"] == "blob":
                        files[child_path] = entry["oid"]
                    elif entry["type"] == "tree":
                        dirs_to_visit.append(child_path)

        return files

    def _batch_tree_entries(
        self, owner: str, repo: str, ref: str, dir_paths: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch tree entries for multiple directories in a single GraphQL query using aliases."""
        fragments = []
        alias_to_dir: Dict[str, str] = {}

        for i, dir_path in enumerate(dir_paths):
            alias = f"d{i}"
            alias_to_dir[alias] = dir_path
            expression = f"{ref}:{dir_path}" if dir_path else f"{ref}:"
            safe_expr = expression.replace("\\", "\\\\").replace('"', '\\"')
            fragments.append(
                f'{alias}: object(expression: "{safe_expr}") '
                f"{{ ... on Tree {{ entries {{ name type oid }} }} }}"
            )

        safe_owner = owner.replace("\\", "\\\\").replace('"', '\\"')
        safe_repo = repo.replace("\\", "\\\\").replace('"', '\\"')

        query = (
            "{\n"
            f'  repository(owner: "{safe_owner}", name: "{safe_repo}") {{\n    '
            + "\n    ".join(fragments)
            + "\n  }\n}"
        )

        data = self.client._request(query, {})
        repo_data = data["repository"]

        results: Dict[str, List[Dict[str, Any]]] = {}
        for alias, dir_path in alias_to_dir.items():
            obj = repo_data.get(alias)
            if obj and "entries" in obj:
                results[dir_path] = obj["entries"]
            else:
                results[dir_path] = []

        return results

    def _get_file_blame(
        self, owner: str, repo: str, file_path: str, ref: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch file content + blame in a single GraphQL call."""
        query = self.client._load_query("file_content_and_blame")
        expression = f"{ref}:{file_path}"

        try:
            data = self.client._request(query, {
                "owner": owner,
                "repo": repo,
                "expression": expression,
                "ref": ref,
                "path": file_path,
            })
        except RuntimeError as e:
            logger.warning(f"GraphQL error for {file_path}: {e}")
            return None

        repo_data = data["repository"]

        # --- content ---
        blob = repo_data.get("content")
        if not blob:
            return None
        text = blob.get("text")
        if text is None:  # binary
            return None

        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]

        # --- blame ---
        line_to_commit: Dict[int, str] = {}
        ref_data = repo_data.get("ref")
        if ref_data:
            target = ref_data.get("target")
            if target:
                blame_ranges = target.get("blame", {}).get("ranges", [])
                for r in blame_ranges:
                    sha = r["commit"]["oid"]
                    for ln in range(r["startingLine"], r["endingLine"] + 1):
                        line_to_commit[ln] = sha

        results = []
        for i, line_content in enumerate(lines, start=1):
            entry: Dict[str, Any] = {"line": i, "content": line_content}
            if i in line_to_commit:
                entry["commit_sha"] = line_to_commit[i]
            results.append(entry)

        return results

    def _get_reviewers_for_commits(self, commit_ids: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """Fetch PR reviewers for commit Node IDs, batched and parallelised."""
        if not commit_ids:
            return {}

        CHUNK_SIZE = 50
        MAX_WORKERS = 10
        chunks = [commit_ids[i : i + CHUNK_SIZE] for i in range(0, len(commit_ids), CHUNK_SIZE)]

        query = self.client._load_query("commit_reviewers")
        results: Dict[str, List[Dict[str, str]]] = {}

        def fetch_chunk(chunk_ids: List[str]) -> Dict[str, List[Dict[str, str]]]:
            chunk_results: Dict[str, List[Dict[str, str]]] = {}
            retries = 3
            backoff = 2

            for attempt in range(retries + 1):
                try:
                    data = self.client._request(query, {"ids": chunk_ids})
                    nodes = data.get("nodes", [])

                    for node in nodes:
                        if not node:
                            continue
                        c_id = node.get("id")
                        reviewers = []

                        prs = node.get("associatedPullRequests", {}).get("nodes", [])
                        if prs:
                            reviews = prs[0].get("reviews", {}).get("nodes", [])
                            seen = set()
                            for review in reviews:
                                author = review.get("author")
                                if not author:
                                    continue
                                login = author.get("login")
                                if login and login not in seen:
                                    seen.add(login)
                                    reviewers.append({
                                        "name": author.get("name"),
                                        "email": author.get("email"),
                                        "login": login,
                                        "submittedAt": review.get("submittedAt"),
                                        "state": review.get("state"),
                                    })

                        chunk_results[c_id] = reviewers

                    return chunk_results

                except RuntimeError as e:
                    if "429" in str(e) and attempt < retries:
                        time.sleep(backoff ** attempt)
                        continue
                    logger.warning(f"Reviewer fetch failed (attempt {attempt + 1}): {e}")
                    if attempt < retries:
                        time.sleep(1)

            return {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_chunk = {executor.submit(fetch_chunk, chunk): chunk for chunk in chunks}

            for future in as_completed(future_to_chunk):
                try:
                    results.update(future.result())
                except Exception as e:
                    logger.warning(f"Chunk processing failed: {e}")

        return results
