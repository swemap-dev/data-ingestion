import hashlib
import logging
import re

from .blame_generator import generate_blame_ranges
from .pr_generator import generate_pr_graphql_response, generate_pr_files_response

logger = logging.getLogger(__name__)


class SyntheticGraphQLBackend:
    """
    Replaces GitHubClient._request() during benchmarks.
    Routes queries to generators based on query content detection.

    All real pipeline code executes (blame parsing, reviewer injection,
    batch tree walking, static analysis) -- only network I/O is eliminated.
    """

    def __init__(self, synthetic_repo):
        self.repo = synthetic_repo
        self.config = synthetic_repo.config

    def mock_request(self, query, variables):
        """
        Drop-in replacement for GitHubClient._request().
        Returns what _request() would return: the data["data"] value.
        """
        # Route based on query content.
        # Order matters: more specific patterns first.
        if "blame" in query.lower() and "path" in variables:
            return self._handle_blame_query(query, variables)
        elif "expression" in variables:
            # File content query uses $expression variable
            return self._handle_file_content_query(query, variables)
        elif "pullRequest" in query and "files" in query and "number" in variables:
            return self._handle_pr_files_query(query, variables)
        elif "pullRequests" in query:
            return self._handle_merged_prs_query(query, variables)
        elif "ids" in variables:
            return self._handle_reviewers_query(query, variables)
        elif self._ALIAS_PATTERN.search(query):
            # Batch tree query with inline d0: object(expression: "...") aliases
            return self._handle_tree_query(query, variables)
        elif "tree" in query and "oid" in query:
            return self._handle_ref_commit_query(query, variables)
        elif "defaultBranchRef" in query or "stargazerCount" in query:
            return self._handle_repo_metadata_query(query, variables)
        else:
            # Default: repository metadata
            if "repository" in query:
                return self._handle_repo_metadata_query(query, variables)
            logger.warning(f"Unrecognized query pattern, returning empty: {query[:100]}")
            return {}

    _ALIAS_PATTERN = re.compile(r'd\d+:\s*object\(expression:')

    def _handle_tree_query(self, query, variables):
        """Handle batch tree entry queries from _batch_tree_entries."""
        # Parse aliases from the query: d0: object(expression: "ref:path") { ... }
        result = {"repository": {}}

        alias_pattern = re.compile(r'(d\d+):\s*object\(expression:\s*"([^"]+)"\)')
        for match in alias_pattern.finditer(query):
            alias = match.group(1)
            expression = match.group(2)

            # expression is like "main:path" or "main:"
            parts = expression.split(":", 1)
            dir_path = parts[1] if len(parts) > 1 else ""

            entries = self.repo.get_tree_entries_for_dir(dir_path)
            result["repository"][alias] = {"entries": entries}

        return result

    def _handle_blame_query(self, query, variables):
        """Handle blame queries from get_raw_blame."""
        file_path = variables.get("path", "")
        ranges = generate_blame_ranges(self.repo, file_path)

        return {
            "repository": {
                "repo_name": self.config.name,
                "file_name": file_path,
                "ref": {
                    "target": {
                        "blame": {
                            "ranges": ranges,
                        }
                    }
                }
            }
        }

    def _handle_file_content_query(self, query, variables):
        """Handle file content queries from get_file_content."""
        expression = variables.get("expression", "")
        # expression is like "ref:path"
        parts = expression.split(":", 1)
        file_path = parts[1] if len(parts) > 1 else ""

        content_bytes = self.repo.get_source_code_for_file(file_path)
        text = content_bytes.decode("utf-8") if content_bytes else ""

        return {
            "repository": {
                "object": {
                    "text": text,
                }
            }
        }

    def _handle_merged_prs_query(self, query, variables):
        """Handle merged PR queries from get_merged_pulls."""
        cursor = variables.get("after")
        page_size = variables.get("first", 100)
        return generate_pr_graphql_response(self.repo, page_size=page_size, cursor=cursor)

    def _handle_pr_files_query(self, query, variables):
        """Handle PR files queries from get_pull_request_files."""
        pr_number = variables.get("number")
        cursor = variables.get("after")
        page_size = variables.get("first", 100)
        return generate_pr_files_response(self.repo, pr_number, page_size=page_size, cursor=cursor)

    def _handle_ref_commit_query(self, query, variables):
        """Handle ref/commit queries from _get_tree_sha."""
        commit_oid = hashlib.sha1(f"{self.config.owner}/{self.config.name}".encode()).hexdigest()
        tree_oid = hashlib.sha1(f"{self.config.name}-tree".encode()).hexdigest()

        return {
            "repository": {
                "ref": {
                    "target": {
                        "oid": commit_oid,
                        "tree": {
                            "oid": tree_oid,
                        },
                    }
                }
            }
        }

    def _handle_repo_metadata_query(self, query, variables):
        """Handle repository metadata queries."""
        return {
            "repository": {
                "databaseId": 12345,
                "name": self.config.name,
                "nameWithOwner": f"{self.config.owner}/{self.config.name}",
                "description": "Synthetic repository for benchmarking",
                "url": f"https://github.com/{self.config.owner}/{self.config.name}",
                "primaryLanguage": {"name": "Python"},
                "stargazerCount": 0,
                "forkCount": 0,
                "watchers": {"totalCount": 0},
                "issues": {"totalCount": 0},
                "defaultBranchRef": {"name": "main"},
                "isPrivate": False,
                "isFork": False,
                "isArchived": False,
                "createdAt": "2025-01-01T00:00:00Z",
                "updatedAt": "2025-06-01T00:00:00Z",
                "pushedAt": "2025-06-01T00:00:00Z",
                "licenseInfo": {"name": "MIT"},
            }
        }

    def _handle_reviewers_query(self, query, variables):
        """Handle commit reviewer queries from _get_reviewers_for_commits."""
        ids = variables.get("ids", [])
        nodes = []
        for cid in ids:
            nodes.append({
                "id": cid,
                "associatedPullRequests": {
                    "nodes": []  # Simplified: no PR associations for speed
                },
            })
        return {"nodes": nodes}
