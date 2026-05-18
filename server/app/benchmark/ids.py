"""Monotonic task_id counter — shared by REST and agent capture paths.

task_id is uint32_t in firmware (firmware/Core/Src/main.c). Counter starts
at 1 and grows monotonically per-process. No wrap risk for thesis workload.
"""
import itertools

_counter = itertools.count(1)


def next_task_id() -> int:
    """Return the next task_id (monotonic from 1, never repeats in-process)."""
    return next(_counter)
