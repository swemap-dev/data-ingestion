import json
import os
from datetime import datetime, timezone

from .profiler import ProfileCollector


def _fmt_bytes(b):
    """Format bytes as human-readable string."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 ** 2):.1f} MB"


def _fmt_duration(s):
    """Format seconds as human-readable string."""
    if s < 0.001:
        return f"{s * 1_000_000:.0f}us"
    elif s < 1:
        return f"{s * 1000:.1f}ms"
    elif s < 60:
        return f"{s:.1f}s"
    else:
        return f"{s / 60:.1f}m"


def _fmt_throughput(t):
    if t is None:
        return "-"
    return f"{t:.0f}/s"


class ConsoleReporter:
    """Prints formatted benchmark results to stdout."""

    def report(self, config_dict, collector=None):
        collector = collector or ProfileCollector()
        summary = collector.get_summary_by_phase()
        records = collector.get_records()

        file_count = config_dict.get("file_count", "?")
        pr_count = config_dict.get("pr_count", "?")
        name = config_dict.get("name", "benchmark")

        print(f"\n=== Benchmark: {name} ({file_count} files, {pr_count} PRs) ===\n")

        # Phase summary table
        phase_order = ["extraction", "blame_processing", "finalization"]
        total_duration = 0.0
        global_peak = 0

        print(f"{'Phase':<22} {'Duration':>10} {'Throughput':>14} {'Memory Peak':>12}")
        print("-" * 60)

        for phase in phase_order:
            if phase not in summary:
                continue
            s = summary[phase]
            dur = s["duration_s"]
            total_duration += dur
            peak = s["peak_memory_bytes"]
            global_peak = max(global_peak, peak)
            tp = s["item_count"] / dur if dur > 0 and s["item_count"] > 0 else None
            label = phase.replace("_", " ").title()
            print(f"{label:<22} {_fmt_duration(dur):>10} {_fmt_throughput(tp):>14} {_fmt_bytes(peak):>12}")

        print("-" * 60)
        print(f"{'Total':<22} {_fmt_duration(total_duration):>10} {'':>14} {_fmt_bytes(global_peak):>12}")

        # Bottleneck
        if summary:
            bottleneck = max(summary.items(), key=lambda x: x[1]["duration_s"])
            pct = (bottleneck[1]["duration_s"] / total_duration * 100) if total_duration > 0 else 0
            label = bottleneck[0].replace("_", " ").title()
            print(f"\nBOTTLENECK: {label} ({pct:.1f}% of total)")

        # Top slowest functions (exclude wrapper/entry-point records)
        real_records = [r for r in records if not r.is_wrapper]
        sorted_records = sorted(real_records, key=lambda r: r.duration_seconds, reverse=True)
        top_n = min(10, len(sorted_records))
        if top_n > 0:
            print(f"\nTop {top_n} slowest functions:")
            for i, r in enumerate(sorted_records[:top_n], 1):
                print(f"  {i:>2}. {r.name:<40} {_fmt_duration(r.duration_seconds):>8}  ({r.category})")

        print()


class JSONReporter:
    """Writes machine-readable JSON benchmark results."""

    def report(self, config_dict, collector=None, output_dir="profiling_results"):
        collector = collector or ProfileCollector()
        summary = collector.get_summary_by_phase()
        records = collector.get_records()

        total_duration = sum(s["duration_s"] for s in summary.values())
        global_peak = max((s["peak_memory_bytes"] for s in summary.values()), default=0)

        bottleneck = None
        if summary:
            bottleneck = max(summary.items(), key=lambda x: x[1]["duration_s"])[0]

        phases = {}
        for phase, s in summary.items():
            phases[phase] = {
                "duration_s": round(s["duration_s"], 4),
                "peak_memory_bytes": s["peak_memory_bytes"],
                "peak_memory_human": _fmt_bytes(s["peak_memory_bytes"]),
                "item_count": s["item_count"],
            }

        # Separate wrapper records from real function records
        real_records = [r for r in records if not r.is_wrapper]
        wrapper_records = [r for r in records if r.is_wrapper]

        functions = []
        for r in sorted(real_records, key=lambda r: r.duration_seconds, reverse=True):
            functions.append({
                "name": r.name,
                "phase": r.phase,
                "category": r.category,
                "duration_s": round(r.duration_seconds, 6),
                "peak_memory_bytes": r.peak_memory_bytes,
                "item_count": r.item_count,
                "throughput": round(r.throughput, 2) if r.throughput else None,
            })

        wrappers = []
        for r in wrapper_records:
            wrappers.append({
                "name": r.name,
                "phase": r.phase,
                "category": r.category,
                "duration_s": round(r.duration_seconds, 6),
                "peak_memory_bytes": r.peak_memory_bytes,
                "item_count": r.item_count,
            })

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": config_dict,
            "total_duration_s": round(total_duration, 4),
            "total_peak_memory_bytes": global_peak,
            "phases": phases,
            "functions": functions,
            "wrappers": wrappers,
            "bottleneck": bottleneck,
        }

        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_{config_dict.get('name', 'run')}_{ts}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)

        print(f"JSON report written to: {filepath}")
        return filepath
