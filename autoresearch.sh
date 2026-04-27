#!/usr/bin/env python3
"""Benchmark find_all_match_locations performance."""
import time
import sys

# Ensure sigil is importable
sys.path.insert(0, ".")

from sigil.core.utils import find_all_match_locations


def bench() -> float:
    # Large file with many repeated matches — worst case for O(n²) newline counting
    lines = ["x = 1 # dup"] * 50_000
    content = "\n".join(lines)

    start = time.perf_counter()
    find_all_match_locations(content, "dup")
    end = time.perf_counter()

    return (end - start) * 1000.0


if __name__ == "__main__":
    # Warm-up
    find_all_match_locations("a\nb\nc", "b")

    # Run benchmark
    elapsed_ms = bench()
    print(f"METRIC total_ms={elapsed_ms:.2f}")
