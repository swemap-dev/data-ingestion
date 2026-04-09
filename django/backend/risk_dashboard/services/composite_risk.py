import logging
import math
from datetime import timedelta
from typing import Dict

from django.conf import settings
from django.db.models import Max, Subquery, OuterRef
from django.utils import timezone

from git_blame_ingestion_app.models import (
    Engineer, File, FileOwnershipMetric, HubType, InteractionType, Module,
)

logger = logging.getLogger(__name__)


# ── Hub score helpers ───────────────────────────────────────────────────

def _hub_score(file, max_coupling: int, max_ext: int) -> float:
    """Return a 0-10 coupling-weighted hub score for a file."""
    if file.hub_type == HubType.GLOBAL:
        if max_coupling > 0:
            return min(10.0, 7 + 3 * file.inbound_coupling / max_coupling)
        return 7.0
    if file.hub_type == HubType.BOUNDARY:
        if max_ext > 0:
            return min(7.0, 4 + 3 * file.external_imports / max_ext)
        return 4.0
    if file.hub_type == HubType.LOCAL:
        return min(4.0, 1 + 3 * file.module_density)
    return 0.0


# ── Knowledge score helpers ─────────────────────────────────────────────

def _knowledge_score(top_pct: float, owner_is_abandoned: bool) -> float:
    """Map top-owner percentage to a 0-10 knowledge-concentration score."""
    config = settings.RISK_CONFIG

    if top_pct >= config["KNOWLEDGE_TOXIC_THRESHOLD"]:
        score = 10.0
    elif top_pct >= config["KNOWLEDGE_CONCENTRATED_THRESHOLD"]:
        score = 7.0
    elif top_pct >= config["KNOWLEDGE_MODERATE_THRESHOLD"]:
        score = 4.0
    else:
        score = config["KNOWLEDGE_DISTRIBUTED_SCORE"]

    if owner_is_abandoned:
        score = min(10.0, score * config["KNOWLEDGE_ABANDONED_MULTIPLIER"])

    return score


# ── Main calculation ────────────────────────────────────────────────────

def calculate_composite_risk(repo_id: int) -> None:
    """
    Calculate the three-pillar composite risk score for every file in a repo
    and aggregate to module level (P90).

    Pillars:
        1. Churn  (change_frequency_score, already 1-10)
        2. Hub    (coupling-weighted, 0-10)
        3. Knowledge (ownership concentration, 0-10)

    Formula:  risk = w_churn * churn + w_hub * hub + w_knowledge * knowledge
    """
    config = settings.RISK_CONFIG
    w_churn = config["RISK_WEIGHT_CHURN"]
    w_hub = config["RISK_WEIGHT_HUB"]
    w_knowledge = config["RISK_WEIGHT_KNOWLEDGE"]

    files = list(
        File.objects.filter(module_id__repo_id=repo_id)
        .select_related('module_id')
    )
    if not files:
        logger.info(f"No files found for repo {repo_id}, skipping composite risk.")
        return

    # ── 1. Hub normalisation constants ──────────────────────────────
    max_coupling = max((f.inbound_coupling for f in files), default=0)
    max_ext = max((f.external_imports for f in files), default=0)

    # ── 2. Pre-fetch file-level ownership (top WROTE owner per file) ─
    # Single query: for each file, get the max lines_owned_percentage and
    # the engineer_id of the top writer.
    file_ids = [f.id for f in files]

    top_pct_map: Dict[int, float] = {}      # file_id -> top owner %
    top_engineer_map: Dict[int, int] = {}   # file_id -> top owner engineer_id

    ownership_qs = (
        FileOwnershipMetric.objects
        .filter(file_id__in=file_ids, type=InteractionType.WROTE)
        .order_by('file_id', '-lines_owned_percentage')
    )
    seen_files = set()
    for metric in ownership_qs:
        if metric.file_id not in seen_files:
            seen_files.add(metric.file_id)
            top_pct_map[metric.file_id] = metric.lines_owned_percentage or 0.0
            top_engineer_map[metric.file_id] = metric.engineer_id

    # ── 3. Pre-fetch engineer last_active for abandoned check ───────
    abandoned_threshold = timezone.now() - timedelta(
        days=config["ABANDONED_INACTIVE_DAYS"]
    )
    engineer_ids = set(top_engineer_map.values())
    abandoned_engineers = set()
    if engineer_ids:
        abandoned_engineers = set(
            Engineer.objects.filter(
                id__in=engineer_ids,
                last_active__lt=abandoned_threshold,
            ).values_list('id', flat=True)
        )

    # ── 4. Compute per-file scores ──────────────────────────────────
    for f in files:
        f.hub_score = round(_hub_score(f, max_coupling, max_ext), 2)

        top_pct = top_pct_map.get(f.id, 0.0)
        eng_id = top_engineer_map.get(f.id)
        is_abandoned = eng_id in abandoned_engineers if eng_id else False
        f.knowledge_score = round(_knowledge_score(top_pct, is_abandoned), 2)

        f.risk_score = round(
            w_churn * f.change_frequency_score
            + w_hub * f.hub_score
            + w_knowledge * f.knowledge_score,
            2,
        )

    # ── 5. Persist file scores ──────────────────────────────────────
    File.objects.bulk_update(files, ['hub_score', 'knowledge_score', 'risk_score'])

    # ── 6. Aggregate to module level (P90) ──────────────────────────
    modules = Module.objects.filter(repo_id=repo_id)
    module_files: Dict[int, list] = {}
    for f in files:
        module_files.setdefault(f.module_id_id, []).append(f.risk_score)

    for module in modules:
        scores = sorted(module_files.get(module.id, []))
        if scores:
            idx = math.ceil(0.9 * len(scores)) - 1
            module.risk_score = scores[max(idx, 0)]
        else:
            module.risk_score = None

    Module.objects.bulk_update(modules, ['risk_score'])

    file_count = len(files)
    high_risk = sum(1 for f in files if f.risk_score >= 7)
    logger.info(
        f"Composite risk complete for repo {repo_id}: "
        f"{file_count} files scored, {high_risk} high-risk (>=7)"
    )
