import os
import random
from datetime import timedelta

from django.utils import timezone
from psycopg.types.range import Range as NumericRange

from git_blame_ingestion_app.models import (
    Repo, Module, File, Engineer, LineOwnership,
    FileOwnershipMetric, InteractionType,
    PullRequest, PullRequestFile,
)


def populate_db_fixtures(synthetic_repo):
    """
    Populate the DB directly for Phase 3-only benchmarks.
    Skips extraction + blame processing and creates records matching
    what the full pipeline would produce.

    Returns (repo_obj, module_map) where module_map is {dir_path: module_obj}.
    """
    config = synthetic_repo.config
    rng = random.Random(42)

    # 1. Create Repo
    repo_obj, _ = Repo.objects.get_or_create(
        owner=config.owner,
        name=config.name,
        defaults={"url": f"https://github.com/{config.owner}/{config.name}"}
    )

    # 2. Create Engineers
    engineer_objs = {}
    for eng in synthetic_repo.engineers:
        obj, _ = Engineer.objects.get_or_create(
            email=eng.email,
            defaults={"name": eng.name}
        )
        engineer_objs[eng.email] = obj

    # 3. Create Modules
    module_map = {}
    for dir_path in synthetic_repo.module_dirs:
        mod_name = dir_path if dir_path else "ROOT"
        mod_obj, _ = Module.objects.get_or_create(
            repo=repo_obj,
            name=mod_name,
            defaults={"dir_path": dir_path}
        )
        module_map[dir_path] = mod_obj

    # 4. Create Files with ast_summary
    file_objs = []
    file_batch = []
    file_path_to_module = {}

    for file_path in synthetic_repo.file_paths:
        module_dir = synthetic_repo.file_to_module.get(file_path, "")
        module_obj = module_map.get(module_dir) or module_map.get("")
        if module_obj is None:
            continue

        lines = synthetic_repo.file_lines.get(file_path, 100)
        ext = os.path.splitext(file_path)[1]

        # Generate realistic ast_summary (needed for brain file analysis)
        same_module_files = [
            f for f in synthetic_repo.file_paths
            if synthetic_repo.file_to_module.get(f) == module_dir
            and f != file_path
            and not any(f.endswith(m) for m in synthetic_repo.MODULE_MARKERS)
        ]
        num_imports = rng.randint(2, min(10, max(2, len(same_module_files))))
        import_targets = rng.sample(same_module_files, min(num_imports, len(same_module_files)))
        import_paths = [os.path.splitext(t)[0].replace("/", ".") for t in import_targets]

        # Nesting depth
        nesting = rng.randint(5, 7) if rng.random() < 0.12 else rng.randint(1, 3)

        # Classes
        num_classes = rng.randint(0, 3)
        classes = []
        for c in range(num_classes):
            cname = f"Class{c}_{os.path.basename(file_path).split('.')[0]}"
            bases = [classes[-1]["name"]] if classes and rng.random() < 0.3 else []
            classes.append({"name": cname, "bases": bases})

        ast_summary = {
            "loc": lines,
            "imports": import_paths,
            "max_nesting_depth": nesting,
            "classes": classes,
        }

        file_batch.append(File(
            module_id_id=module_obj.id,
            file_path=file_path,
            line_count=lines,
            ast_summary=ast_summary,
            loc_count=lines,
        ))
        file_path_to_module[file_path] = module_dir

    # Bulk create files
    File.objects.bulk_create(file_batch, batch_size=1000, ignore_conflicts=True)

    # Reload to get IDs
    file_objs = list(File.objects.filter(module_id__repo=repo_obj))
    file_map = {f.file_path: f for f in file_objs}

    # 5. Create LineOwnership records
    engineer_list = list(engineer_objs.values())
    lo_batch = []

    for f in file_objs:
        total_lines = f.line_count or 100
        avg_ranges = synthetic_repo.config.avg_blame_ranges_per_file
        num_ranges = max(1, min(int(rng.gauss(avg_ranges, avg_ranges * 0.3)), total_lines))

        if total_lines > 1 and num_ranges > 1:
            split_points = sorted(rng.sample(range(2, total_lines + 1), min(num_ranges - 1, total_lines - 1)))
        else:
            split_points = []
        boundaries = [1] + split_points + [total_lines + 1]

        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1] - 1
            # Zipf pick
            weights = [1.0 / (j + 1) for j in range(len(engineer_list))]
            eng = rng.choices(engineer_list, weights=weights, k=1)[0]

            lo_batch.append(LineOwnership(
                file_id=f.id,
                engineer=eng,
                line_range=NumericRange(start, end + 1),
            ))

        # Flush in batches to avoid memory pressure
        if len(lo_batch) >= 10000:
            LineOwnership.objects.bulk_create(lo_batch, batch_size=5000)
            lo_batch = []

    if lo_batch:
        LineOwnership.objects.bulk_create(lo_batch, batch_size=5000)

    # 6. Create FileOwnershipMetric records
    fom_batch = []
    for f in file_objs:
        total_lines = f.line_count or 100
        los = LineOwnership.objects.filter(file_id=f.id).values('engineer_id')

        from django.db.models import Sum
        from django.db.models.functions import Coalesce
        from django.db.models import F, ExpressionWrapper, IntegerField

        # Simplified: just create a WROTE metric for each engineer with proportional ownership
        eng_lines = {}
        for lo in LineOwnership.objects.filter(file_id=f.id):
            r = lo.line_range
            lines_owned = (r.upper or 0) - (r.lower or 0)
            eng_lines[lo.engineer_id] = eng_lines.get(lo.engineer_id, 0) + lines_owned

        for eng_id, lines_owned in eng_lines.items():
            pct = (float(lines_owned) / total_lines) * 100 if total_lines > 0 else 0
            fom_batch.append(FileOwnershipMetric(
                file_id=f.id,
                engineer_id=eng_id,
                lines_owned=lines_owned,
                lines_owned_percentage=pct,
                type=InteractionType.WROTE,
            ))

        if len(fom_batch) >= 5000:
            FileOwnershipMetric.objects.bulk_create(fom_batch, batch_size=5000, ignore_conflicts=True)
            fom_batch = []

    if fom_batch:
        FileOwnershipMetric.objects.bulk_create(fom_batch, batch_size=5000, ignore_conflicts=True)

    # 7. Create PullRequest and PullRequestFile records
    pr_batch = []
    for pr in synthetic_repo.prs:
        pr_batch.append(PullRequest(
            repo=repo_obj,
            github_pr_number=pr.number,
            title=pr.title[:512],
            merged_at=pr.merged_at,
            author_login=pr.author_login[:255],
            is_revert=pr.is_revert,
            is_bot=pr.is_bot,
        ))

    PullRequest.objects.bulk_create(pr_batch, batch_size=5000, ignore_conflicts=True)

    # Reload PRs
    pr_objs = {
        pr.github_pr_number: pr
        for pr in PullRequest.objects.filter(repo=repo_obj)
    }

    prf_batch = []
    for pr in synthetic_repo.prs:
        pr_obj = pr_objs.get(pr.number)
        if not pr_obj:
            continue
        for fp in pr.file_paths:
            prf_batch.append(PullRequestFile(
                pull_request=pr_obj,
                file_path=fp[:512],
            ))

        if len(prf_batch) >= 10000:
            PullRequestFile.objects.bulk_create(prf_batch, batch_size=5000, ignore_conflicts=True)
            prf_batch = []

    if prf_batch:
        PullRequestFile.objects.bulk_create(prf_batch, batch_size=5000, ignore_conflicts=True)

    return repo_obj, module_map
