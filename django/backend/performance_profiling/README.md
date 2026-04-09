# Performance Profiling System

Identifies where time is spent across the three pipeline phases (Extraction, Blame Processing, Finalization) using synthetic data at configurable scale. No production code is modified — profiling hooks are injected via monkey-patching at runtime.

## Quick Start

```bash
# Smoke test (500 files, 200 PRs) — takes ~1-2 minutes
python manage.py run_benchmarks --scale small

# Medium scale (5k files, 2k PRs)
python manage.py run_benchmarks --scale medium

# Phase 3 only (skip extraction + blame, test finalization bottlenecks)
python manage.py run_benchmarks --scale medium --mode phase3-only

# Microbenchmarks (individual function scaling)
python manage.py run_benchmarks --mode microbenchmark

# Stability analysis (score sensitivity to small changes)
python manage.py run_stability_test --scale small
```

## Benchmark Modes

### Full Pipeline (`--mode full`, default)

Runs the complete `initialize()` flow with a synthetic GraphQL backend replacing `GitHubClient._request()`. All real pipeline code executes — blame parsing, reviewer injection, batch tree walking, static analysis, DB writes, finalization metrics — only network I/O is eliminated.

### Phase 3 Only (`--mode phase3-only`)

Pre-populates the database with synthetic Repo, Module, File, Engineer, LineOwnership, FileOwnershipMetric, PullRequest, and PullRequestFile records, then calls `finalize_repo_ingestion()` directly. Isolates the computation-heavy finalization: sigmoid decay, percentile ranking, brain file import matching, structural complexity.

### Microbenchmark (`--mode microbenchmark`)

Calls individual functions with realistic data to profile algorithmic scaling:
- `calculate_change_frequency()` on the full file set
- `calculate_module_brain_files()` on the largest module
- `calculate_structural_complexity()` on the largest module
- `decay_weight()` at N = 1k, 5k, 20k, 50k iterations

## Preset Scales

| Scale   | Files  | PRs     | Engineers | Modules |
|---------|--------|---------|-----------|---------|
| small   | 500    | 200     | 10        | 5       |
| medium  | 5,000  | 2,000   | 30        | 20      |
| large   | 20,000 | 10,000  | 50        | 50      |
| stress  | 50,000 | 100,000 | 100       | 100     |

## Command Reference

### `run_benchmarks`

```bash
python manage.py run_benchmarks [OPTIONS]
```

| Option         | Values                              | Default  | Description                          |
|----------------|-------------------------------------|----------|--------------------------------------|
| `--scale`      | small, medium, large, stress        | —        | Preset configuration                 |
| `--files`      | int                                 | —        | Override file count                  |
| `--prs`        | int                                 | —        | Override PR count                    |
| `--engineers`  | int                                 | —        | Override engineer count              |
| `--modules`    | int                                 | —        | Override module count                |
| `--mode`       | full, phase3-only, microbenchmark   | full     | Benchmark mode                       |
| `--output`     | console, json, both                 | both     | Output format                        |
| `--output-dir` | path                                | profiling_results/ | Directory for JSON reports  |
| `--repeat`     | int                                 | 1        | Runs for mean + stddev               |

Custom configuration example:

```bash
python manage.py run_benchmarks --files 5000 --prs 2000 --engineers 25 --mode full --repeat 3
```

### `run_stability_test`

```bash
python manage.py run_stability_test [OPTIONS]
```

| Option                | Default | Description                                    |
|-----------------------|---------|------------------------------------------------|
| `--scale`             | —       | Preset configuration                           |
| `--files`             | —       | Override file count                             |
| `--perturbation-size` | 5       | Number of files modified in the perturbation    |
| `--threshold`         | 0.001   | Absolute score delta threshold for "stable"     |

Workflow: runs the full pipeline twice (baseline, then with small perturbation: +1 file, N modified blame ranges, +1 PR), and compares all score fields.

## Output

### Console

```
=== Benchmark: synthetic-small (500 files, 200 PRs) ===

Phase                    Duration     Throughput  Memory Peak
------------------------------------------------------------
Extraction                  53.3s            9/s      29.3 MB
Blame Processing            48.3s              -      26.3 MB
Finalization                 5.2s              -      29.3 MB
------------------------------------------------------------
Total                        1.8m                     29.3 MB

BOTTLENECK: Extraction (49.9% of total)

Top 5 slowest functions:
   1. full_pipeline                               52.3s  (io)
   2. ingest_merged_prs                         995.7ms  (io)
   3. calculate_module_brain_files              832.4ms  (computation)
   ...
```

### JSON

Written to `profiling_results/benchmark_<name>_<timestamp>.json`:

```json
{
  "timestamp": "2026-03-15T01:26:05Z",
  "config": {"file_count": 500, "pr_count": 200, ...},
  "total_duration_s": 81.3,
  "phases": {
    "extraction": {"duration_s": 53.3, "peak_memory_bytes": 30720000},
    "blame_processing": {"duration_s": 48.3, ...},
    "finalization": {"duration_s": 5.2, ...}
  },
  "functions": [{"name": "...", "duration_s": ..., "category": "...", ...}],
  "bottleneck": "extraction"
}
```

## Architecture

The profiling system has no dependencies on production code at import time. During benchmark runs:

1. **Synthetic data generation** — `SyntheticRepo` creates an in-memory repository (file tree, engineers, PRs, blame ranges) from a `SyntheticRepoConfig`.

2. **Mock injection** — `SyntheticGraphQLBackend` replaces `GitHubClient._request()` via `unittest.mock.patch`. It routes GraphQL queries by content to the appropriate generator (tree, blame, file content, PRs, metadata).

3. **Profiling injection** — Target functions are monkey-patched with wrappers that record timing and memory via `ProfileCollector`. Class methods use `patch.object(cls, method, new=wrapper)` for correct `self` binding; module-level functions use `patch(path, side_effect=wrapper)`.

4. **Celery bypass** — Uses `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` with a synchronous fake chord (same pattern as `BrainFileE2ETests`).

5. **DB cleanup** — Calls `clear_app_data` management command between runs.
