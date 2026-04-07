---
name: Risk Dashboard Context Brief
description: Architecture and scoring logic for the three risk dashboard components plus structural hubs — use this to onboard agents quickly
type: project
---

# Risk Dashboard Context Brief

The risk dashboard analyzes codebases across three risk dimensions plus a structural hub classification. All scores are pre-computed during ingestion and persisted to the `File` model.

---

## Component 1: Knowledge Distribution Risk

**Service**: `risk_dashboard/services/risk_analytics.py`
**Endpoint**: `GET /api/risk/modules/{module_id}/knowledge-distribution`

Identifies ownership concentration and team-change risks using `ModuleOwnershipMetric` and `Engineer.last_active`.

| Metric | Definition | Threshold |
|--------|-----------|-----------|
| Bus Factor | Top owner holds >90% of module | `BUS_FACTOR_THRESHOLD = 90.0` |
| Abandoned Code | Owner with >30% share inactive >90 days | `ABANDONED_INACTIVE_DAYS = 90` |
| Silo Classification | Categorizes knowledge spread | See below |

**Silo types**:
- `TOXIC_SILO` — top owner >90%
- `HEALTHY_SILO` — top owner 50-70%, second owner 10-20%
- `DISTRIBUTED` — everything else

---

## Component 2: Structural Complexity Risk

**Service**: `risk_dashboard/services/structural_complexity.py`
**Endpoint**: `GET /api/risk/modules/{module_id}/structural-complexity`

Flags files with deep nesting or deep inheritance hierarchies.

| Metric | Threshold | Penalty |
|--------|-----------|---------|
| Max nesting depth | >= 4 levels | +4 points |
| Max inheritance depth | >= 3 levels | +4 points |

**Structural risk score** = nesting_penalty + inheritance_penalty (possible values: 0, 4, 8 per file).

---

## Component 3: Change Frequency / File Churn Risk

**Service**: `risk_dashboard/services/change_frequency.py`
**Endpoint**: `GET /api/risk/modules/{module_id}/change-frequency`

Identifies volatile files using PR merge history over a 180-day lookback window.

**Scoring pipeline**:
1. **Decay weight** per PR merge: sigmoid `W(t) = L + (H-L) / (1 + e^(k*(t - x0)))` where H=1.0, L=0.1, x0=21 days, k=0.5
2. **Raw score** = sum of decay-weighted PR counts per file (reverts excluded)
3. **Quiet repo guard** — if variance < 0.01, all files default to score 3
4. **Percentile ranking** converts raw scores to 0-1 scale
5. **Capped normalization** maps to 1-10 scale:
   - If max_raw >= 2.0: effective_max = 10, else 7
   - If min_raw <= 0.1: effective_min = 1, else 3
6. **Hotspot** = score >= 8.0

---

## Structural Hubs ("Brain Files")

**Service**: `risk_dashboard/services/brain_file_analysis.py`

Classifies files by import coupling (not one of the "three components" but a key supplementary dimension):

| Hub Type | Criteria |
|----------|----------|
| **Global Hub** | >= 30 unique importers OR >= 15% of all files |
| **Boundary Hub** | >= 5 external importers AND external/total >= 80% |
| **Local Hub** | Module has >= 3 files, internal_imports/siblings >= 50%, internal dominance >= 50% |

Global hubs are identified first; remaining files are then checked for boundary/local classification.

---

## Key Models

- **`File`** — holds all computed metrics: `hub_type`, `max_nesting_depth`, `max_inheritance_depth`, `structural_risk_score`, `change_frequency_score`, `change_frequency_raw`, `inbound_coupling`, `internal_imports`, `external_imports`, `module_density`, `ast_summary`
- **`ModuleOwnershipMetric`** — per-engineer ownership percentages per module (type: WROTE / REVIEWED / DESIGNED)
- **`Engineer`** — includes `last_active` for abandoned-code detection

## Calculation Pipeline

```
initialize(repo_url)
  -> Create modules/repo in DB
  -> Ingest PR data
  -> Queue blame tasks per file
  -> finalize_repo_ingestion(repo_id) [callback]
       Per module:
         - calculate_module_metrics(module_id)
         - calculate_structural_complexity(module_id)
       Repo-wide:
         - calculate_structural_hubs(repo_id)
         - calculate_change_frequency(repo_id)
```

## Config

All thresholds live in `settings.py` (lines ~150-179) and are adjustable.
