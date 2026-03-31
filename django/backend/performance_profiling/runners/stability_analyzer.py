import copy
import logging
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from unittest.mock import patch

from django.core.management import call_command
from django.test.utils import override_settings

from ..generators.synthetic_repo import SyntheticRepo, SyntheticRepoConfig
from ..generators.graphql_backend import SyntheticGraphQLBackend

logger = logging.getLogger(__name__)


@dataclass
class StabilityReport:
    total_files: int = 0
    pct_stable: float = 0.0  # |delta| < 0.001
    pct_within_threshold: float = 0.0  # |delta| < threshold
    max_change: float = 0.0
    outliers: List[dict] = field(default_factory=list)
    score_fields: Dict[str, dict] = field(default_factory=dict)  # per-field breakdown

    def print_report(self):
        print(f"\n=== Stability Test Report ===")
        print(f"Total files scored: {self.total_files}")
        print(f"Perfectly stable (|delta| < 0.001): {self.pct_stable:.1f}%")
        print(f"Within threshold: {self.pct_within_threshold:.1f}%")
        print(f"Max absolute change: {self.max_change:.6f}")

        if self.score_fields:
            print(f"\nPer-field breakdown:")
            for field_name, stats in self.score_fields.items():
                print(f"  {field_name}: "
                      f"stable={stats['pct_stable']:.1f}%, "
                      f"max_delta={stats['max_change']:.6f}")

        if self.outliers:
            print(f"\nOutliers ({len(self.outliers)}):")
            for o in self.outliers[:20]:
                print(f"  {o['file_path']}: {o['field']} "
                      f"({o['before']:.4f} -> {o['after']:.4f}, "
                      f"delta={o['delta']:.6f})")

        # Known sensitivity callout
        print(f"\nNOTE: percentile_rank() in change_frequency.py uses a linear scan")
        print(f"  (sum(1 for v in sorted_raws if v < value) / (n-1)),")
        print(f"  so adding a single file shifts all ranks.")
        if self.score_fields.get("change_frequency_score", {}).get("max_change", 0) > 0.001:
            print(f"  -> Change frequency shifts detected. This is EXPECTED behavior.")
        else:
            print(f"  -> No significant change frequency shifts. Scores are stable.")
        print()


def _cleanup_db():
    try:
        call_command("clear_app_data", verbosity=0)
    except Exception:
        from git_blame_ingestion_app.models import (
            LineOwnership, FileOwnershipMetric, ModuleOwnershipMetric,
            File, Module, Repo, Engineer, PullRequest, PullRequestFile,
        )
        PullRequestFile.objects.all().delete()
        PullRequest.objects.all().delete()
        LineOwnership.objects.all().delete()
        FileOwnershipMetric.objects.all().delete()
        ModuleOwnershipMetric.objects.all().delete()
        File.objects.all().delete()
        Module.objects.all().delete()
        Repo.objects.all().delete()
        Engineer.objects.all().delete()


def _fake_chord(tasks):
    for task in tasks:
        task.apply()
    def callback_runner(callback):
        callback.apply()
    return callback_runner


def _snapshot_scores(repo_id):
    """Take a snapshot of all file scores."""
    from git_blame_ingestion_app.models import File
    files = File.objects.filter(module_id__repo_id=repo_id)
    snapshot = {}
    for f in files:
        snapshot[f.file_path] = {
            "change_frequency_score": f.change_frequency_score,
            "change_frequency_raw": f.change_frequency_raw,
            "is_brain_file": float(f.is_brain_file),
            "inbound_coupling": float(f.inbound_coupling),
            "structural_risk_score": float(f.structural_risk_score),
        }
    return snapshot


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def _run_pipeline(config, synthetic_repo):
    """Run full pipeline with mock backend."""
    backend = SyntheticGraphQLBackend(synthetic_repo)

    from git_blame_ingestion_app.services.client import GitHubClient
    from git_blame_ingestion_app.tasks import initialize

    with patch.object(GitHubClient, '_request', side_effect=backend.mock_request):
        with patch('git_blame_ingestion_app.tasks.chord') as mock_chord:
            mock_chord.side_effect = _fake_chord
            initialize(f"https://github.com/{config.owner}/{config.name}")


def _apply_perturbation(synthetic_repo, perturbation_size):
    """
    Apply small perturbation to synthetic repo:
    - Add 1 new file
    - Modify blame for perturbation_size files
    - Add 1 new PR touching perturbation_size files
    """
    rng = random.Random(99)
    config = synthetic_repo.config

    # 1. Add 1 new file
    ext = rng.choice(list(config.language_weights.keys()))
    new_file = f"src/new_perturbation_file{ext}"
    synthetic_repo.file_paths.append(new_file)
    if synthetic_repo.module_dirs:
        synthetic_repo.file_to_module[new_file] = synthetic_repo.module_dirs[1] if len(synthetic_repo.module_dirs) > 1 else ""
    else:
        synthetic_repo.file_to_module[new_file] = ""
    synthetic_repo.file_lines[new_file] = 100
    config.file_count += 1

    # 2. Modify line counts for perturbation_size files (simulates blame change)
    source_files = [f for f in synthetic_repo.file_paths
                    if not any(f.endswith(m) for m in synthetic_repo.MODULE_MARKERS)]
    modified_files = rng.sample(source_files, min(perturbation_size, len(source_files)))
    for fp in modified_files:
        old_lines = synthetic_repo.file_lines.get(fp, 100)
        # Small change: +/- 5 lines
        synthetic_repo.file_lines[fp] = max(10, old_lines + rng.randint(-5, 5))

    # 3. Add 1 new PR touching perturbation_size files
    from ..generators.synthetic_repo import SyntheticPR
    now = datetime.now(timezone.utc)
    pr_files = rng.sample(source_files, min(perturbation_size, len(source_files)))
    new_pr = SyntheticPR(
        number=len(synthetic_repo.prs) + 1,
        title="Perturbation PR",
        merged_at=now - timedelta(days=1),
        author_login="perturbation-bot",
        is_revert=False,
        is_bot=False,
        file_paths=pr_files,
    )
    synthetic_repo.prs.append(new_pr)
    config.pr_count += 1


def run_stability_test(config, perturbation_size=5, threshold=0.001):
    """
    Run stability analysis:
    1. Generate synthetic repo and run full pipeline
    2. Snapshot scores
    3. Apply small perturbation
    4. Re-run pipeline
    5. Compare snapshots
    """
    logger.info(f"Starting stability test: {config.name}")

    # Run 1: baseline
    _cleanup_db()
    synthetic_repo = SyntheticRepo(config)
    _run_pipeline(config, synthetic_repo)

    from git_blame_ingestion_app.models import Repo
    repo_obj = Repo.objects.get(owner=config.owner, name=config.name)
    snapshot_before = _snapshot_scores(repo_obj.id)
    logger.info(f"Baseline snapshot: {len(snapshot_before)} files")

    # Apply perturbation
    _apply_perturbation(synthetic_repo, perturbation_size)

    # Run 2: perturbed
    _cleanup_db()
    _run_pipeline(config, synthetic_repo)

    repo_obj = Repo.objects.get(owner=config.owner, name=config.name)
    snapshot_after = _snapshot_scores(repo_obj.id)
    logger.info(f"Perturbed snapshot: {len(snapshot_after)} files")

    # Compare
    score_fields = [
        "change_frequency_score", "change_frequency_raw",
        "is_brain_file", "inbound_coupling", "structural_risk_score",
    ]

    report = StabilityReport(total_files=len(snapshot_before))
    total_stable = 0
    total_within = 0
    total_comparisons = 0
    max_change = 0.0
    outliers = []

    per_field = {f: {"stable": 0, "within": 0, "total": 0, "max_change": 0.0} for f in score_fields}

    # Only compare files present in both snapshots
    common_files = set(snapshot_before.keys()) & set(snapshot_after.keys())

    for fp in common_files:
        before = snapshot_before[fp]
        after = snapshot_after[fp]

        for field_name in score_fields:
            val_before = before.get(field_name, 0.0)
            val_after = after.get(field_name, 0.0)
            delta = abs(val_after - val_before)

            per_field[field_name]["total"] += 1
            total_comparisons += 1

            if delta < 0.001:
                total_stable += 1
                per_field[field_name]["stable"] += 1

            if delta < threshold:
                total_within += 1
                per_field[field_name]["within"] += 1

            if delta > max_change:
                max_change = delta

            if delta > per_field[field_name]["max_change"]:
                per_field[field_name]["max_change"] = delta

            if delta >= threshold:
                outliers.append({
                    "file_path": fp,
                    "field": field_name,
                    "before": val_before,
                    "after": val_after,
                    "delta": delta,
                })

    report.pct_stable = (total_stable / total_comparisons * 100) if total_comparisons > 0 else 100
    report.pct_within_threshold = (total_within / total_comparisons * 100) if total_comparisons > 0 else 100
    report.max_change = max_change
    report.outliers = sorted(outliers, key=lambda x: -x["delta"])

    for f in score_fields:
        pf = per_field[f]
        report.score_fields[f] = {
            "pct_stable": (pf["stable"] / pf["total"] * 100) if pf["total"] > 0 else 100,
            "pct_within_threshold": (pf["within"] / pf["total"] * 100) if pf["total"] > 0 else 100,
            "max_change": pf["max_change"],
        }

    report.print_report()
    return report
