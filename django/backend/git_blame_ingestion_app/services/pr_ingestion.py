import re
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

from ..models import Repo, PullRequest, PullRequestFile
from .client import GitHubClient

logger = logging.getLogger(__name__)


def ingest_merged_prs(repo_id, owner, name, lookback_days=None):
    """Fetch merged PRs from GitHub and store them with their changed files."""
    if lookback_days is None:
        lookback_days = settings.RISK_CONFIG["CHURN_LOOKBACK_DAYS"]

    since = timezone.now() - timedelta(days=lookback_days)

    client = GitHubClient()
    merged_pulls = client.get_merged_pulls(owner, name, since)
    logger.info(f"Fetched {len(merged_pulls)} merged PRs for {owner}/{name} since {since.date()}")

    for pr_data in merged_pulls:
        from datetime import datetime
        merged_at = datetime.fromisoformat(pr_data['mergedAt'].replace('Z', '+00:00'))
        title = pr_data.get('title', '') or ''
        author = pr_data.get('author', {}) or {}
        author_login = author.get('login', '')

        is_revert = bool(re.match(r'^Revert\b', title, re.IGNORECASE))
        is_bot = author_login.endswith('[bot]')

        pr_obj, created = PullRequest.objects.get_or_create(
            repo_id=repo_id,
            github_pr_number=pr_data['number'],
            defaults={
                'title': title[:512],
                'merged_at': merged_at,
                'author_login': author_login[:255] if author_login else None,
                'is_revert': is_revert,
                'is_bot': is_bot,
            }
        )

        if created:
            file_paths = client.get_pull_request_files(owner, name, pr_data['number'])
            pr_files = [
                PullRequestFile(pull_request=pr_obj, file_path=fp[:512])
                for fp in file_paths
            ]
            PullRequestFile.objects.bulk_create(pr_files, ignore_conflicts=True)
            logger.info(f"PR #{pr_data['number']}: ingested {len(pr_files)} files")

    logger.info(f"PR ingestion complete for {owner}/{name}: {len(merged_pulls)} PRs processed")
