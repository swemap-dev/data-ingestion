def generate_pr_graphql_response(synthetic_repo, page_size=100, cursor=None):
    """
    Generate a GraphQL response for merged PRs matching the shape consumed
    by GitHubClient.get_merged_pulls():
        data["repository"]["pullRequests"]["nodes"] + pageInfo

    Each PR node matches the shape consumed by ingest_merged_prs (pr_ingestion.py:24-43):
        {"number": int, "mergedAt": str, "updatedAt": str,
         "title": str, "author": {"login": str}}
    """
    prs = synthetic_repo.prs

    # Simple cursor-based pagination
    start_idx = 0
    if cursor is not None:
        start_idx = int(cursor)

    end_idx = min(start_idx + page_size, len(prs))
    page = prs[start_idx:end_idx]
    has_next = end_idx < len(prs)

    nodes = []
    for pr in page:
        nodes.append({
            "number": pr.number,
            "title": pr.title,
            "mergedAt": pr.merged_at.isoformat().replace("+00:00", "Z"),
            "updatedAt": pr.merged_at.isoformat().replace("+00:00", "Z"),
            "author": {"login": pr.author_login},
        })

    return {
        "repository": {
            "pullRequests": {
                "nodes": nodes,
                "pageInfo": {
                    "hasNextPage": has_next,
                    "endCursor": str(end_idx) if has_next else None,
                },
            }
        }
    }


def generate_pr_files_response(synthetic_repo, pr_number, page_size=100, cursor=None):
    """
    Generate a GraphQL response for PR files matching the shape consumed by
    GitHubClient.get_pull_request_files():
        data["repository"]["pullRequest"]["files"]["nodes"] + pageInfo
    """
    pr = None
    for p in synthetic_repo.prs:
        if p.number == pr_number:
            pr = p
            break

    if pr is None:
        return {
            "repository": {
                "pullRequest": {
                    "files": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

    start_idx = int(cursor) if cursor else 0
    end_idx = min(start_idx + page_size, len(pr.file_paths))
    page = pr.file_paths[start_idx:end_idx]
    has_next = end_idx < len(pr.file_paths)

    nodes = [{"path": fp} for fp in page]

    return {
        "repository": {
            "pullRequest": {
                "files": {
                    "nodes": nodes,
                    "pageInfo": {
                        "hasNextPage": has_next,
                        "endCursor": str(end_idx) if has_next else None,
                    },
                }
            }
        }
    }
