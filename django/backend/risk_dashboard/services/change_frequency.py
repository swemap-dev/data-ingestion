import logging
import math
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from git_blame_ingestion_app.models import File, PullRequest, PullRequestFile

logger = logging.getLogger(__name__)

def decay_weight(t, H=None, L=None, x0=None, k=None):
    """Sigmoid decay: W(t) = L + (H - L) / (1 + e^(k*(t - x0)))"""
    cfg = settings.RISK_CONFIG
    H = H if H is not None else cfg["CHURN_DECAY_H"]
    L = L if L is not None else cfg["CHURN_DECAY_L"]
    x0 = x0 if x0 is not None else cfg["CHURN_DECAY_X0"]
    k = k if k is not None else cfg["CHURN_DECAY_K"]
    return L + (H - L) / (1 + math.exp(k * (t - x0)))

def calculate_change_frequency(repo_id):
    """Calculate change frequency scores for all files in a repo."""
    cfg = settings.RISK_CONFIG
    lookback_days = cfg["CHURN_LOOKBACK_DAYS"]
    cutoff = timezone.now() - timedelta(days=lookback_days)

    # Step 1: Get all non-revert PRs in lookback window
    pr_files = PullRequestFile.objects.filter(
        pull_request__repo_id=repo_id,
        pull_request__is_revert=False,
        pull_request__merged_at__gte=cutoff,
    ).select_related('pull_request')

    # Step 2: Compute raw scores per file_path
    now = timezone.now()
    raw_scores = {}  # file_path -> S_raw
    for prf in pr_files:
        days_ago = (now - prf.pull_request.merged_at).total_seconds() / 86400
        w = decay_weight(days_ago)
        raw_scores[prf.file_path] = raw_scores.get(prf.file_path, 0.0) + w

    # Step 3: Get all File objects in the repo
    files = list(File.objects.filter(module_id__repo_id=repo_id))
    if not files:
        logger.info(f"No files found for repo {repo_id}, skipping change frequency")
        return

    # Assign raw scores (files not in any PR get 0)
    for f in files:
        f.change_frequency_raw = raw_scores.get(f.file_path, 0.0)

    all_raws = [f.change_frequency_raw for f in files]

    # Step 4: Quiet repo check
    if len(all_raws) <= 1:
        variance = 0.0
    else:
        mean_raw = sum(all_raws) / len(all_raws)
        variance = sum((x - mean_raw) ** 2 for x in all_raws) / len(all_raws)

    if variance < cfg["CHURN_QUIET_VARIANCE"]:
        for f in files:
            f.change_frequency_score = cfg["CHURN_QUIET_DEFAULT"]
        File.objects.bulk_update(files, ['change_frequency_score', 'change_frequency_raw'])
        logger.info(f"Quiet repo {repo_id}: all files set to default score {cfg['CHURN_QUIET_DEFAULT']}")
        return

    # Step 5: Percentile ranking
    sorted_raws = sorted(all_raws)
    n = len(sorted_raws)

    def percentile_rank(value):
        # Count how many values are strictly less than this value
        count_below = sum(1 for v in sorted_raws if v < value)
        return count_below / (n - 1) if n > 1 else 0.0

    # Step 6: Capped normalization
    max_raw = max(all_raws)
    min_raw = min(all_raws)
    effective_max = 10 if max_raw >= cfg["CHURN_HIGH_CAP_THRESHOLD"] else cfg["CHURN_HIGH_CAP_FALLBACK"]
    effective_min = 1 if min_raw <= cfg["CHURN_LOW_CAP_THRESHOLD"] else cfg["CHURN_LOW_CAP_FALLBACK"]

    for f in files:
        pct = percentile_rank(f.change_frequency_raw)
        f.change_frequency_score = round(effective_min + pct * (effective_max - effective_min), 2)

    # Step 7: Bulk update
    File.objects.bulk_update(files, ['change_frequency_score', 'change_frequency_raw'])
    logger.info(f"Change frequency calculated for repo {repo_id}: {len(files)} files updated")
