from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationBatchRunStats:
    pending_items: int
    total_batches: int
    effective_batch_size: int
    flush_interval: int
    effective_workers: int
    batched_fast_batches: int
    single_fast_batches: int
    single_slow_batches: int

    def as_dict(self) -> dict[str, int]:
        return {
            "pending_items": self.pending_items,
            "total_batches": self.total_batches,
            "effective_batch_size": self.effective_batch_size,
            "flush_interval": self.flush_interval,
            "effective_workers": self.effective_workers,
            "fast_queue_batches": self.batched_fast_batches + self.single_fast_batches,
            "slow_queue_batches": self.single_slow_batches,
            "batched_fast_batches": self.batched_fast_batches,
            "single_fast_batches": self.single_fast_batches,
            "single_slow_batches": self.single_slow_batches,
        }


def _empty_worker_allocation() -> dict[str, int]:
    return {
        "batched_fast": 0,
        "single_fast": 0,
        "single_slow": 0,
    }


def _single_worker_allocation(*, batched_fast_count: int, single_fast_count: int, single_slow_count: int) -> dict[str, int]:
    allocation = _empty_worker_allocation()
    first_queue = next(
        (
            name
            for name, count in (
                ("batched_fast", batched_fast_count),
                ("single_fast", single_fast_count),
                ("single_slow", single_slow_count),
            )
            if count > 0
        ),
        "",
    )
    if first_queue:
        allocation[first_queue] = 1
    return allocation


def _slow_worker_cap(workers: int) -> int:
    if workers <= 8:
        return 1
    if workers <= 24:
        return 2
    return min(4, max(2, workers // 8))


def _fast_queue_targets(*, batched_fast_count: int, single_fast_count: int) -> list[tuple[str, int]]:
    return [
        (name, count)
        for name, count in (
            ("batched_fast", batched_fast_count),
            ("single_fast", single_fast_count),
        )
        if count > 0
    ]


def _distribute_extra_workers(remaining_after_floor: int, fast_targets: list[tuple[str, int]]) -> dict[str, int]:
    total_fast_batches = sum(count for _, count in fast_targets)
    if remaining_after_floor <= 0 or total_fast_batches <= 0:
        return {name: 0 for name, _count in fast_targets}
    extras: dict[str, int] = {}
    assigned = 0
    for index, (name, count) in enumerate(fast_targets):
        extra = (
            remaining_after_floor - assigned
            if index == len(fast_targets) - 1
            else (remaining_after_floor * count) // total_fast_batches
        )
        assigned += extra
        extras[name] = extra
    return extras


def _allocate_translation_queue_workers(
    total_workers: int,
    *,
    batched_fast_count: int,
    single_fast_count: int,
    single_slow_count: int,
) -> dict[str, int]:
    workers = max(1, total_workers)
    allocation = _empty_worker_allocation()
    if workers == 1:
        return _single_worker_allocation(
            batched_fast_count=batched_fast_count,
            single_fast_count=single_fast_count,
            single_slow_count=single_slow_count,
        )

    if single_slow_count > 0:
        allocation["single_slow"] = min(single_slow_count, _slow_worker_cap(workers), max(1, workers - 1))

    remaining = workers - allocation["single_slow"]
    fast_targets = _fast_queue_targets(
        batched_fast_count=batched_fast_count,
        single_fast_count=single_fast_count,
    )

    if not fast_targets:
        allocation["single_slow"] = workers
        return allocation
    if len(fast_targets) == 1:
        allocation[fast_targets[0][0]] = remaining
        return allocation

    remaining_after_floor = remaining - len(fast_targets)
    for name, _count in fast_targets:
        allocation[name] = 1
    for name, extra in _distribute_extra_workers(remaining_after_floor, fast_targets).items():
        allocation[name] += extra
    return allocation


__all__ = [
    "TranslationBatchRunStats",
    "_allocate_translation_queue_workers",
    "_distribute_extra_workers",
    "_empty_worker_allocation",
    "_fast_queue_targets",
    "_single_worker_allocation",
    "_slow_worker_cap",
]
