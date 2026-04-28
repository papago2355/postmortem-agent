#!/usr/bin/env python3
"""
selftest.py — Self-test for detect.py and promote.py.

Runs against synthetic data under a temp dir. Does NOT touch the user's
~/.hermes/memories/. Exits 0 on pass, non-zero on fail.

Stdlib only — runs on Python 3.9+.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

# Make sibling modules importable when invoked as `python selftest.py`
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import detect  # noqa: E402
import promote  # noqa: E402


def _ok(label: str) -> None:
    print(f"  PASS — {label}")


def _fail(label: str, got: object) -> None:
    print(f"  FAIL — {label}: got {got!r}", file=sys.stderr)
    sys.exit(1)


def test_detect_against_sample_session() -> None:
    print("[detect] against examples/sample_session.json")
    sample_path = _HERE.parent / "examples" / "sample_session.json"
    with sample_path.open("r", encoding="utf-8") as f:
        transcript = json.load(f)

    candidates = detect.detect_all(transcript, strict=False)
    signals = sorted({c["signal"] for c in candidates})

    expected_signals = {
        "A:user-correction",
        "B:tool-retry",
        "D:self-admission",
        "E:confidence-mismatch",
    }

    if not expected_signals.issubset(set(signals)):
        _fail(
            "all four signal types present",
            f"expected superset of {expected_signals}, got {signals}",
        )
    _ok(f"all four signal types fired: {signals}")

    if len(candidates) < 4:
        _fail("at least 4 candidates", len(candidates))
    _ok(f"{len(candidates)} candidates total")

    # Strict mode should drop low-precision E
    strict_candidates = detect.detect_all(transcript, strict=True)
    strict_signals = {c["signal"] for c in strict_candidates}
    if "E:confidence-mismatch" in strict_signals:
        _fail("strict drops E:confidence-mismatch", strict_signals)
    _ok("strict mode drops low-precision E signal")

    # B should detect TWO tool retries (rotation + regression test)
    b_hits = [c for c in candidates if c["signal"] == "B:tool-retry"]
    if len(b_hits) < 2:
        _fail("two tool-retry pairs detected", len(b_hits))
    _ok(f"{len(b_hits)} tool-retry pair(s) detected")


def test_promote_with_recurring_pattern() -> None:
    print("[promote] with one pattern at recurrence=3")
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_dir = Path(tmpdir) / "memories"
        memory_dir.mkdir(parents=True)

        postmortems = textwrap.dedent("""
            §
            pattern: host-vs-docker-env-silent-empty-results
            kind: env-config
            confidence_failure_mode: Silent empty results looked like missing data; was a connection issue.
            canonical_correct_path: Prefix host-side Python with MILVUS_HOST=localhost.
            resolution: param-fix
            first_seen: 2026-04-10
            last_seen: 2026-04-22
            recurrence_count: 3
            sessions: [s1, s2, s3]

            §
            pattern: gpu-module-needs-docker-exec
            kind: env-config
            confidence_failure_mode: Agent ran torch script on host that lacks CUDA.
            canonical_correct_path: Run via docker exec rag-api python3.
            resolution: prompt-fix
            first_seen: 2026-04-15
            last_seen: 2026-04-22
            recurrence_count: 1
            sessions: [s4]
        """).strip()

        (memory_dir / "POSTMORTEMS.md").write_text(postmortems, encoding="utf-8")
        (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

        result = promote.promote(memory_dir=memory_dir, threshold=3, dry_run=False)

        if "host-vs-docker-env-silent-empty-results" not in result["promoted_patterns"]:
            _fail("recurring pattern promoted", result)
        if "gpu-module-needs-docker-exec" in result["promoted_patterns"]:
            _fail("non-recurring pattern NOT promoted", result)
        _ok("only recurring pattern promoted")

        memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
        if "[PROMOTED-FROM-POSTMORTEM]" not in memory_text:
            _fail("promoted line written to MEMORY.md", memory_text)
        if "host-vs-docker-env-silent-empty-results" not in memory_text:
            _fail("pattern name in promoted line", memory_text)
        if "MILVUS_HOST=localhost" not in memory_text:
            _fail("canonical path in promoted line", memory_text)
        _ok("MEMORY.md contains the promoted rule")

        # Idempotency: a second run should not double-promote
        result2 = promote.promote(memory_dir=memory_dir, threshold=3, dry_run=False)
        if result2["promoted_patterns"]:
            _fail("idempotent on re-run", result2)
        _ok("re-run is a no-op (idempotent)")


def test_promote_respects_char_budget() -> None:
    print("[promote] respects MEMORY.md 2200-char budget")
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_dir = Path(tmpdir) / "memories"
        memory_dir.mkdir(parents=True)

        # Pre-fill MEMORY.md with non-promoted entries near the limit
        existing = "\n§\n" + "\n§\n".join(["x" * 400 for _ in range(5)]) + "\n"
        (memory_dir / "MEMORY.md").write_text(existing, encoding="utf-8")

        # Add a recurring postmortem to promote
        pm = textwrap.dedent("""
            §
            pattern: budget-test-pattern
            kind: env-config
            confidence_failure_mode: x
            canonical_correct_path: y
            resolution: param-fix
            first_seen: 2026-04-01
            last_seen: 2026-04-22
            recurrence_count: 5
            sessions: [s1]
        """).strip()
        (memory_dir / "POSTMORTEMS.md").write_text(pm, encoding="utf-8")

        result = promote.promote(memory_dir=memory_dir, threshold=3, dry_run=False)
        memory_text = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")

        if len(memory_text) > promote.MEMORY_CHAR_LIMIT:
            _fail("memory char limit respected", len(memory_text))
        if "budget-test-pattern" not in memory_text:
            _fail("promoted entry survived eviction", memory_text)
        _ok(f"MEMORY.md is {len(memory_text)}/{promote.MEMORY_CHAR_LIMIT} chars after promotion")


def test_promote_pruning() -> None:
    print("[promote] prunes resolved old entries")
    import datetime as dt
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_dir = Path(tmpdir) / "memories"
        memory_dir.mkdir(parents=True)

        pm = textwrap.dedent("""
            §
            pattern: ancient-resolved-pattern
            kind: env-config
            confidence_failure_mode: x
            canonical_correct_path: y
            resolution: param-fix
            first_seen: 2026-01-01
            last_seen: 2026-01-15
            recurrence_count: 4
            sessions: [s1]

            §
            pattern: recent-active-pattern
            kind: env-config
            confidence_failure_mode: x
            canonical_correct_path: y
            resolution: param-fix
            first_seen: 2026-04-15
            last_seen: 2026-04-22
            recurrence_count: 2
            sessions: [s2]
        """).strip()
        (memory_dir / "POSTMORTEMS.md").write_text(pm, encoding="utf-8")

        result = promote.prune(
            memory_dir=memory_dir,
            today=dt.date(2026, 4, 28),
            dry_run=False,
        )
        if "ancient-resolved-pattern" not in result["moved_patterns"]:
            _fail("ancient entry archived", result)
        if "recent-active-pattern" in result["moved_patterns"]:
            _fail("recent entry NOT archived", result)
        _ok("pruning moves only old resolved entries")


def main() -> int:
    print("postmortem-evolve self-test\n" + "=" * 32)
    test_detect_against_sample_session()
    print()
    test_promote_with_recurring_pattern()
    print()
    test_promote_respects_char_budget()
    print()
    test_promote_pruning()
    print()
    print("ALL TESTS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
