import time
import tracemalloc
import threading
import functools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimingRecord:
    name: str
    phase: str  # extraction, blame_processing, finalization
    category: str  # io, computation, db
    start_time: float = 0.0
    end_time: float = 0.0
    peak_memory_bytes: int = 0
    item_count: int = 0
    is_wrapper: bool = False

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time

    @property
    def throughput(self) -> Optional[float]:
        if self.item_count > 0 and self.duration_seconds > 0:
            return self.item_count / self.duration_seconds
        return None


class ProfileCollector:
    """Thread-safe singleton that accumulates TimingRecords from across the pipeline."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._records = []
                cls._instance._records_lock = threading.Lock()
            return cls._instance

    def reset(self):
        with self._records_lock:
            self._records = []

    def add_record(self, record: TimingRecord):
        with self._records_lock:
            self._records.append(record)

    def get_records(self) -> list:
        with self._records_lock:
            return list(self._records)

    def get_summary_by_phase(self) -> dict:
        records = self.get_records()
        summary = {}
        for r in records:
            if r.phase not in summary:
                summary[r.phase] = {
                    "duration_s": 0.0,
                    "peak_memory_bytes": 0,
                    "item_count": 0,
                    "functions": [],
                }
            s = summary[r.phase]
            # Exclude wrapper records from duration sum to avoid double-counting
            if not r.is_wrapper:
                s["duration_s"] += r.duration_seconds
            s["peak_memory_bytes"] = max(s["peak_memory_bytes"], r.peak_memory_bytes)
            if not r.is_wrapper:
                s["item_count"] += r.item_count
            s["functions"].append({
                "name": r.name,
                "duration_s": r.duration_seconds,
                "category": r.category,
                "item_count": r.item_count,
                "throughput": r.throughput,
                "is_wrapper": r.is_wrapper,
            })
        return summary


@contextmanager
def profile_section(name, phase="unknown", category="unknown", item_count=0,
                    is_wrapper=False):
    """Context manager that records timing + memory for a code block."""
    collector = ProfileCollector()

    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()

    # Reset peak to measure only this section
    tracemalloc.reset_peak()
    start = time.perf_counter()

    try:
        yield
    finally:
        end = time.perf_counter()
        _, peak = tracemalloc.get_traced_memory()

        record = TimingRecord(
            name=name,
            phase=phase,
            category=category,
            start_time=start,
            end_time=end,
            peak_memory_bytes=peak,
            item_count=item_count,
            is_wrapper=is_wrapper,
        )
        collector.add_record(record)

        if not was_tracing:
            tracemalloc.stop()


def profile_task(name, phase="unknown", category="unknown"):
    """Decorator that profiles a function call."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with profile_section(name, phase=phase, category=category):
                return func(*args, **kwargs)
        return wrapper
    return decorator
