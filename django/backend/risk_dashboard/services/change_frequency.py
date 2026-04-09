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

    # Step 4: Logarithmic scoring
    # Maps absolute raw score to a 1-10 scale logarithmically, independently of other files
    # We use CHURN_HIGH_CAP_THRESHOLD to determine what raw score maps to a 10.
    high_cap = cfg.get("CHURN_HIGH_CAP_THRESHOLD", 2.0)
    
    for f in files:
        raw = f.change_frequency_raw
        if raw <= 0:
            score = 1.0
        else:
            ratio = math.log(raw + 1) / math.log(high_cap + 1)
            score = 1.0 + 9.0 * ratio
        
        f.change_frequency_score = round(max(1.0, min(10.0, score)), 2)

    # Step 7: Bulk update
    File.objects.bulk_update(files, ['change_frequency_score', 'change_frequency_raw'])
    logger.info(f"Change frequency calculated for repo {repo_id}: {len(files)} files updated")
