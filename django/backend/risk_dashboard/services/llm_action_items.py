import logging
import time
from typing import List, Dict, Any, Optional

from django.conf import settings
from django.db.models import Sum, Q
from django.utils import timezone
from openai import OpenAI

from git_blame_ingestion_app.models import (
    ActionItem, File, FileOwnershipMetric, InteractionType, Module,
    ModuleOwnershipMetric,
)
from .prompts import (
    SYSTEM_PROMPT, BUS_FACTOR_PROMPT, VOLATILE_HUB_PROMPT,
    COMPLEXITY_HOTSPOT_PROMPT, ABANDONED_CONCENTRATED_PROMPT,
)

logger = logging.getLogger(__name__)


# ── Context builders ───────────────────────────────────────────────────
# Each returns a text section (or empty string if no data).
# They can be composed freely via CONTEXT_BUILDERS or called directly.

def build_top_risk_files_context(repo_id: int, top_k: int = 15) -> str:
    files = list(
        File.objects.filter(module_id__repo_id=repo_id)
        .order_by('-risk_score')[:top_k]
    )
    logger.info(f"[LLM] Gathered {len(files)} top risk files (k={top_k})")
    if not files:
        return ""
    lines = [f"## Top {top_k} Riskiest Files (composite score 0-10)"]
    for f in files:
        lines.append(
            f"- {f.file_path}  score={f.risk_score}  "
            f"churn={f.change_frequency_score}  hub={f.hub_score}  "
            f"knowledge={f.knowledge_score}  hub_type={f.hub_type or 'none'}"
        )
    return "\n".join(lines)


def build_cascade_risk_context(repo_id: int, min_churn: float = 8.0, top_k: int = 10) -> str:
    files = list(
        File.objects.filter(
            module_id__repo_id=repo_id,
            hub_type__in=['GLOBAL', 'BOUNDARY'],
            change_frequency_score__gte=min_churn,
        )
    )
    for f in files:
        f._cascade_score = f.inbound_coupling * f.change_frequency_score
    files.sort(key=lambda f: f._cascade_score, reverse=True)
    files = files[:top_k]
    logger.info(f"[LLM] Gathered {len(files)} cascade-risk hub files (min_churn={min_churn})")
    if not files:
        return ""
    lines = ["## Cascade-Risk Hubs (high-churn files with many dependents)"]
    for f in files:
        lines.append(
            f"- {f.file_path}  churn={f.change_frequency_score}  "
            f"coupling={f.inbound_coupling}  hub_type={f.hub_type}  "
            f"cascade_score={f._cascade_score:.1f}"
        )
    return "\n".join(lines)


def build_bus_factor_context(repo_id: int, top_k: int = 10) -> str:
    dominant = list(
        ModuleOwnershipMetric.objects.filter(
            module__repo_id=repo_id,
            lines_owned_percentage__gt=80,
            type=InteractionType.WROTE,
        )
        .select_related('module', 'engineer')
        .order_by('-lines_owned_percentage')[:top_k]
    )
    logger.info(f"[LLM] Gathered {len(dominant)} bus-factor entries")
    if not dominant:
        return ""
    lines = ["## Bus-Factor Risk (single owner >80% of a module)"]
    for m in dominant:
        mod_name = m.module.name or m.module.dir_path or "ROOT"
        lines.append(
            f"- Module '{mod_name}': {m.engineer.name} owns "
            f"{m.lines_owned_percentage:.1f}%  "
            f"last_active={m.engineer.last_active}"
        )
    return "\n".join(lines)


def build_structural_complexity_context(repo_id: int, top_k: int = 10) -> str:
    complex_files = list(
        File.objects.filter(
            module_id__repo_id=repo_id,
            structural_risk_score__gte=4,
        ).order_by('-structural_risk_score')[:top_k]
    )
    logger.info(f"[LLM] Gathered {len(complex_files)} structurally complex files")
    if not complex_files:
        return ""
    lines = ["## Structurally Complex Files (deep nesting or inheritance)"]
    for f in complex_files:
        lines.append(
            f"- {f.file_path}  nesting={f.max_nesting_depth}  "
            f"inheritance={f.max_inheritance_depth}  "
            f"structural_risk={f.structural_risk_score}"
        )
    return "\n".join(lines)


def build_complexity_hotspot_context(
    repo_id: int, min_churn: float = 7.0, top_k: int = 10,
) -> str:
    files = list(
        File.objects.filter(
            module_id__repo_id=repo_id,
            structural_risk_score__gte=4,
            change_frequency_score__gte=min_churn,
        ).order_by('-structural_risk_score', '-change_frequency_score')[:top_k]
    )
    logger.info(
        f"[LLM] Gathered {len(files)} complexity hotspots "
        f"(structural_risk>=4, churn>={min_churn})"
    )
    if not files:
        return ""
    lines = ["## Complexity Hotspots (structurally complex + high churn)"]
    for f in files:
        lines.append(
            f"- {f.file_path}  nesting={f.max_nesting_depth}  "
            f"inheritance={f.max_inheritance_depth}  "
            f"structural_risk={f.structural_risk_score}  "
            f"churn={f.change_frequency_score}"
        )
    return "\n".join(lines)


def build_module_risk_context(repo_id: int, top_k: int = 10) -> str:
    modules = list(
        Module.objects.filter(repo_id=repo_id, risk_score__isnull=False)
        .order_by('-risk_score')[:top_k]
    )
    logger.info(f"[LLM] Gathered {len(modules)} risky modules")
    if not modules:
        return ""
    lines = [f"## Top {top_k} Riskiest Modules"]
    for mod in modules:
        file_count = File.objects.filter(module_id_id=mod.id).count()
        high_risk_count = File.objects.filter(
            module_id_id=mod.id, risk_score__gte=7,
        ).count()
        lines.append(
            f"- {mod.name or 'ROOT'}  risk={mod.risk_score}  "
            f"files={file_count}  high_risk_files={high_risk_count}"
        )
    return "\n".join(lines)


def build_under_reviewed_context(
    repo_id: int, min_risk: float = 7.0, max_review_coverage: float = 0.3, top_k: int = 10,
) -> str:
    modules = Module.objects.filter(repo_id=repo_id, risk_score__gte=min_risk)
    results = []
    for mod in modules:
        aggregates = FileOwnershipMetric.objects.filter(
            file__module_id=mod,
        ).aggregate(
            wrote=Sum('lines_owned', filter=Q(type=InteractionType.WROTE)),
            reviewed=Sum('lines_owned', filter=Q(type=InteractionType.REVIEWED)),
        )
        wrote = aggregates['wrote'] or 0
        reviewed = aggregates['reviewed'] or 0
        coverage = reviewed / wrote if wrote > 0 else 0.0
        if coverage < max_review_coverage:
            results.append((mod.name or mod.dir_path or "ROOT", mod.risk_score, wrote, reviewed, coverage))

    results.sort(key=lambda r: r[4])
    results = results[:top_k]
    logger.info(f"[LLM] Gathered {len(results)} under-reviewed modules (min_risk={min_risk}, max_coverage={max_review_coverage})")
    if not results:
        return ""
    lines = ["## Under-Reviewed High-Risk Modules (low peer-review coverage)"]
    for name, risk, wrote, reviewed, coverage in results:
        lines.append(
            f"- {name}  risk={risk}  wrote={wrote}  reviewed={reviewed}  "
            f"review_coverage={coverage:.1%}"
        )
    return "\n".join(lines)


def build_abandoned_concentrated_files_context(
    repo_id: int, min_ownership: float = 80.0, inactive_months: int = 6, top_k: int = 10,
) -> str:
    from dateutil.relativedelta import relativedelta
    cutoff = timezone.now() - relativedelta(months=inactive_months)

    metrics = list(
        FileOwnershipMetric.objects.filter(
            file__module_id__repo_id=repo_id,
            type=InteractionType.WROTE,
            lines_owned_percentage__gte=min_ownership,
            engineer__last_active__lt=cutoff,
        )
        .select_related('file', 'engineer')
        .order_by('-lines_owned_percentage')[:top_k]
    )
    logger.info(
        f"[LLM] Gathered {len(metrics)} abandoned concentrated files "
        f"(ownership>={min_ownership}%, inactive>={inactive_months}mo)"
    )
    if not metrics:
        return ""
    lines = [
        f"## Abandoned Concentrated Files "
        f"(>={min_ownership}% single-owner, inactive >={inactive_months} months)"
    ]
    for m in metrics:
        lines.append(
            f"- {m.file.file_path}  engineer={m.engineer.name}  "
            f"ownership={m.lines_owned_percentage:.1f}%  "
            f"last_active={m.engineer.last_active.isoformat() if m.engineer.last_active else 'unknown'}"
        )
    return "\n".join(lines)


# ── Registry of named context builders ─────────────────────────────────
# Each entry maps a context type to its data builder and a specific prompt.
# When a single context type is requested, its prompt is used as the system
# prompt. When multiple are combined, we fall back to the generic SYSTEM_PROMPT.

CONTEXT_BUILDERS = {
    "top_risk_files":         {"builder": build_top_risk_files_context,         "prompt": SYSTEM_PROMPT},
    "cascade_risk":           {"builder": build_cascade_risk_context,           "prompt": VOLATILE_HUB_PROMPT},
    "bus_factor":             {"builder": build_bus_factor_context,             "prompt": BUS_FACTOR_PROMPT},
    "structural_complexity":  {"builder": build_structural_complexity_context,  "prompt": SYSTEM_PROMPT},
    "complexity_hotspot":     {"builder": build_complexity_hotspot_context,     "prompt": COMPLEXITY_HOTSPOT_PROMPT},
    "module_risk":            {"builder": build_module_risk_context,            "prompt": SYSTEM_PROMPT},
    "under_reviewed":         {"builder": build_under_reviewed_context,         "prompt": SYSTEM_PROMPT},
    "abandoned_concentrated_files": {"builder": build_abandoned_concentrated_files_context, "prompt": ABANDONED_CONCENTRATED_PROMPT},
}

# The default set used when no context_types are specified
DEFAULT_CONTEXT_TYPES = [
    "top_risk_files", "cascade_risk", "bus_factor",
    "structural_complexity", "module_risk",
]


def build_context(
    repo_id: int, context_types: List[str] = None, top_k: int = 15,
) -> tuple[str, str]:
    """
    Build a combined context string and resolve the system prompt.

    Returns (context_str, system_prompt):
      - If a single context type is requested, uses that type's specific prompt.
      - If multiple types are combined, falls back to the generic SYSTEM_PROMPT.
    """
    if context_types is None:
        context_types = DEFAULT_CONTEXT_TYPES

    sections = []
    prompts_seen = []
    for ctx_type in context_types:
        entry = CONTEXT_BUILDERS.get(ctx_type)
        if entry is None:
            logger.warning(f"[LLM] Unknown context type '{ctx_type}', skipping")
            continue
        section = entry["builder"](repo_id, top_k=top_k)
        if section:
            sections.append(section)
            prompts_seen.append(entry["prompt"])

    # Single context type → use its specific prompt; multiple → generic
    if len(prompts_seen) == 1:
        prompt = prompts_seen[0]
    else:
        prompt = SYSTEM_PROMPT

    logger.info(f"[LLM] Resolved prompt: {'specific' if len(prompts_seen) == 1 else 'generic'} ({len(prompts_seen)} context types)")

    return "\n\n".join(sections), prompt


# ── Main generation function ───────────────────────────────────────────

def generate_action_items(
    repo_id: int,
    context: Optional[str] = None,
    context_types: List[str] = None,
    top_k: int = 15,
) -> Dict[str, Any]:
    """
    Send context to the local Ollama LLM for action item generation.

    Context resolution:
      1. If `context` is provided, use it directly with the generic SYSTEM_PROMPT.
      2. Otherwise, build from `context_types` — a single type uses its specific
         prompt; multiple types fall back to the generic prompt.
    """
    logger.info(f"[LLM] ── Starting action item generation for repo {repo_id} ──")

    # ── 1. Resolve context + prompt ───────────────────────────────────
    t0 = time.time()
    if context is not None:
        system_prompt = SYSTEM_PROMPT
    else:
        context, system_prompt = build_context(repo_id, context_types=context_types, top_k=top_k)
    context_time = time.time() - t0
    logger.info(f"[LLM] Context ready in {context_time:.2f}s  ({len(context)} chars, ~{len(context)//4} tokens)")

    if not context.strip():
        return {
            "status": "no_data",
            "message": "No risk data found for this repo. Run ingestion first.",
            "action_items_raw": None,
            "context_sent": "",
        }

    logger.info(f"[LLM] Context sent to LLM:\n{context[:1000]}{'...' if len(context) > 1000 else ''}")

    # ── 2. Call Ollama ────────────────────────────────────────────────
    client = OpenAI(
        base_url=settings.OLLAMA_BASE_URL,
        api_key="ollama",
        timeout=300.0,
    )

    user_message = (
        f"Here is the risk analysis for the repository:\n\n{context}\n\n"
        "Based on this data, generate a prioritised list of action items."
    )

    logger.info(f"[LLM] Sending request to Ollama  model={settings.OLLAMA_MODEL}  temp={settings.OLLAMA_TEMPERATURE}")
    logger.info(f"[LLM] System prompt: {system_prompt[:80]}...")
    logger.info(f"[LLM] Waiting for response (this may take 1-2 minutes)...")

    t1 = time.time()
    response = client.chat.completions.create(
        model=settings.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=settings.OLLAMA_TEMPERATURE,
    )
    llm_time = time.time() - t1

    content = response.choices[0].message.content
    usage = response.usage
    logger.info(
        f"[LLM] Response received in {llm_time:.1f}s  "
        f"prompt_tokens={usage.prompt_tokens}  completion_tokens={usage.completion_tokens}  "
        f"response_chars={len(content)}"
    )

    # ── 3. Save to ActionItem table ───────────────────────────────────
    action_item = ActionItem.objects.create(
        repo_id=repo_id,
        content=content,
    )
    logger.info(f"[LLM] Action item saved as ActionItem(id={action_item.id})")
    logger.info(f"[LLM] ── Done. Total time: {context_time + llm_time:.1f}s ──")

    return {
        "status": "ok",
        "model": settings.OLLAMA_MODEL,
        "action_item_id": action_item.id,
        "action_items_raw": content,
        "context_sent": context,
    }
