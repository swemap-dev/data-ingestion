import logging
import statistics
import time
from unittest.mock import patch

from django.core.management import call_command
from django.test.utils import override_settings

from ..profiler import ProfileCollector, profile_section
from ..reporters import ConsoleReporter, JSONReporter
from ..generators.synthetic_repo import SyntheticRepo, SyntheticRepoConfig
from ..generators.graphql_backend import SyntheticGraphQLBackend
from ..generators.db_fixtures import populate_db_fixtures

logger = logging.getLogger(__name__)

# Profiling targets: (import_path, function_name, phase, category)
PROFILE_TARGETS = [
    ("git_blame_ingestion_app.services.file_contents_gql.FileContentsServiceGQL",
     "get_blame_with_content", "blame_processing", "io"),
    ("git_blame_ingestion_app.services.file_contents_gql.FileContentsServiceGQL",
     "get_all_file_paths", "extraction", "io"),
    ("git_blame_ingestion_app.services.static_analysis",
     "analyze_code_file", "blame_processing", "computation"),
    ("git_blame_ingestion_app.services.ingestion",
     "process_blame_response", "blame_processing", "db"),
    ("git_blame_ingestion_app.services.ingestion",
     "recalculate_metrics", "blame_processing", "computation"),
    ("git_blame_ingestion_app.services.ingestion",
     "calculate_module_metrics", "finalization", "db"),
    ("risk_dashboard.services.change_frequency",
     "calculate_change_frequency", "finalization", "computation"),
    ("risk_dashboard.services.brain_file_analysis",
     "calculate_module_brain_files", "finalization", "computation"),
    ("risk_dashboard.services.structural_complexity",
     "calculate_structural_complexity", "finalization", "computation"),
    ("git_blame_ingestion_app.services.pr_ingestion",
     "ingest_merged_prs", "extraction", "io"),
]


def _build_patches(targets):
    """Build list of mock.patch objects for profiling targets.

    For class methods, use ``new=wrapper`` so the wrapper is installed as a real
    function on the class and Python's descriptor protocol binds ``self``
    correctly.  For module-level functions, ``side_effect`` is fine because
    there is no ``self`` binding step.
    """
    import importlib
    patches = []
    for module_path, func_name, phase, category in targets:
        parts = module_path.rsplit(".", 1)
        if len(parts) != 2:
            continue

        try:
            mod = importlib.import_module(parts[0])
            attr = getattr(mod, parts[1], None)
        except ImportError:
            continue

        if attr is not None and isinstance(attr, type) and hasattr(attr, func_name):
            # Class method: wrap with ``new=`` so self binding works
            original = getattr(attr, func_name)

            def _make_method_wrapper(orig, n, ph, cat):
                def wrapper(self_arg, *args, **kwargs):
                    with profile_section(n, phase=ph, category=cat):
                        return orig(self_arg, *args, **kwargs)
                return wrapper

            wrapper = _make_method_wrapper(original, func_name, phase, category)
            p = patch.object(attr, func_name, new=wrapper)
            patches.append(p)
        else:
            # Module-level function
            target = f"{module_path}.{func_name}"
            try:
                mod2 = importlib.import_module(module_path)
                original = getattr(mod2, func_name)
            except (ImportError, AttributeError) as e:
                logger.warning(f"Cannot patch {target}: {e}")
                continue

            def _make_func_wrapper(orig, n, ph, cat):
                def wrapper(*args, **kwargs):
                    with profile_section(n, phase=ph, category=cat):
                        return orig(*args, **kwargs)
                return wrapper

            wrapper = _make_func_wrapper(original, func_name, phase, category)
            p = patch(target, side_effect=wrapper)
            patches.append(p)

    return patches


def _cleanup_db():
    """Clean up benchmark data between runs."""
    try:
        call_command("clear_app_data", verbosity=0)
    except Exception as e:
        logger.warning(f"clear_app_data failed, doing manual cleanup: {e}")
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
    """Synchronous chord replacement (from BrainFileE2ETests pattern)."""
    for task in tasks:
        task.apply()

    def callback_runner(callback):
        callback.apply()
    return callback_runner


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def run_full_pipeline(config, collector):
    """Run the full pipeline with mock GraphQL backend."""
    logger.info(f"Starting full pipeline benchmark: {config.name}")

    _cleanup_db()
    synthetic_repo = SyntheticRepo(config)
    backend = SyntheticGraphQLBackend(synthetic_repo)

    # Build profiling patches
    profiling_patches = _build_patches(PROFILE_TARGETS)

    from git_blame_ingestion_app.services.client import GitHubClient
    from git_blame_ingestion_app.tasks import initialize

    with profile_section("full_pipeline", phase="extraction", category="io",
                         item_count=config.file_count, is_wrapper=True):
        # Apply profiling patches
        active_patches = [p.start() for p in profiling_patches]

        try:
            with patch.object(GitHubClient, '_request', side_effect=backend.mock_request):
                with patch('git_blame_ingestion_app.tasks.chord') as mock_chord:
                    mock_chord.side_effect = _fake_chord
                    initialize(f"https://github.com/{config.owner}/{config.name}")
        finally:
            for p in profiling_patches:
                try:
                    p.stop()
                except RuntimeError:
                    pass


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def run_phase3_only(config, collector):
    """Run Phase 3 (finalization) only with pre-populated DB."""
    logger.info(f"Starting Phase 3-only benchmark: {config.name}")

    _cleanup_db()
    synthetic_repo = SyntheticRepo(config)

    with profile_section("db_fixture_setup", phase="extraction", category="db",
                         item_count=config.file_count):
        repo_obj, module_map = populate_db_fixtures(synthetic_repo)

    # Profile Phase 3 functions
    finalization_targets = [t for t in PROFILE_TARGETS if t[2] == "finalization"]
    profiling_patches = _build_patches(finalization_targets)
    active_patches = [p.start() for p in profiling_patches]

    try:
        from git_blame_ingestion_app.tasks import finalize_repo_ingestion

        with profile_section("finalize_repo_ingestion", phase="finalization",
                             category="computation", item_count=config.file_count,
                             is_wrapper=True):
            finalize_repo_ingestion(repo_obj.id)
    finally:
        for p in profiling_patches:
            try:
                p.stop()
            except RuntimeError:
                pass


def run_microbenchmark(config, collector):
    """Run microbenchmarks on individual functions at increasing data sizes."""
    logger.info("Starting microbenchmark suite")

    _cleanup_db()
    synthetic_repo = SyntheticRepo(config)
    repo_obj, module_map = populate_db_fixtures(synthetic_repo)

    # Microbenchmark 1: calculate_change_frequency at various scales
    from risk_dashboard.services.change_frequency import calculate_change_frequency
    with profile_section("calculate_change_frequency", phase="finalization",
                         category="computation", item_count=config.file_count):
        calculate_change_frequency(repo_obj.id)

    # Microbenchmark 2: calculate_module_brain_files per module
    from risk_dashboard.services.brain_file_analysis import calculate_module_brain_files
    for dir_path, mod_obj in module_map.items():
        file_count = File.objects.filter(module_id=mod_obj.id).count()
        if file_count > 0:
            with profile_section(f"brain_files_{mod_obj.name}", phase="finalization",
                                 category="computation", item_count=file_count):
                calculate_module_brain_files(mod_obj.id)
            break  # Just benchmark the largest module

    # Microbenchmark 3: calculate_structural_complexity
    from risk_dashboard.services.structural_complexity import calculate_structural_complexity
    for dir_path, mod_obj in module_map.items():
        file_count = File.objects.filter(module_id=mod_obj.id).count()
        if file_count > 0:
            with profile_section(f"structural_complexity_{mod_obj.name}", phase="finalization",
                                 category="computation", item_count=file_count):
                calculate_structural_complexity(mod_obj.id)
            break

    # Microbenchmark 4: decay_weight scaling
    from risk_dashboard.services.change_frequency import decay_weight
    for n in [1000, 5000, 20000, 50000]:
        with profile_section(f"decay_weight_x{n}", phase="finalization",
                             category="computation", item_count=n):
            for i in range(n):
                decay_weight(i % 180)


# Import File here to avoid import at module level issues
from git_blame_ingestion_app.models import File


def run_benchmark(config, mode="full", output="both", output_dir="profiling_results",
                  repeat=1):
    """Main entry point for running benchmarks."""
    collector = ProfileCollector()

    if repeat > 1:
        all_durations = []

        for i in range(repeat):
            collector.reset()
            logger.info(f"Run {i + 1}/{repeat}")

            _run_single(config, mode, collector)

            total = sum(r.duration_seconds for r in collector.get_records())
            all_durations.append(total)

        # Report stats
        mean_dur = statistics.mean(all_durations)
        stddev = statistics.stdev(all_durations) if len(all_durations) > 1 else 0
        print(f"\n=== Repeat Summary ({repeat} runs) ===")
        print(f"Mean: {mean_dur:.2f}s, Stddev: {stddev:.2f}s")
        print(f"Runs: {[f'{d:.2f}s' for d in all_durations]}")
    else:
        collector.reset()
        _run_single(config, mode, collector)

    # Report
    config_dict = config.to_dict()

    if output in ("console", "both"):
        ConsoleReporter().report(config_dict, collector)

    if output in ("json", "both"):
        JSONReporter().report(config_dict, collector, output_dir=output_dir)


def _run_single(config, mode, collector):
    """Execute a single benchmark run."""
    if mode == "full":
        run_full_pipeline(config, collector)
    elif mode == "phase3-only":
        run_phase3_only(config, collector)
    elif mode == "microbenchmark":
        run_microbenchmark(config, collector)
    else:
        raise ValueError(f"Unknown mode: {mode}")
