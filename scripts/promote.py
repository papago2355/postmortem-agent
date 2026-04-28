#!/usr/bin/env python3
"""
promote.py — Recurrence detection + promotion of postmortem entries.

Reads ~/.hermes/memories/POSTMORTEMS.md, parses §-delimited entries, and:

  1. For each pattern whose recurrence_count >= --threshold (default 3),
     ensures a [PROMOTED-FROM-POSTMORTEM] line exists in MEMORY.md.

  2. (--prune) Archives entries that haven't recurred within the resolution-
     specific TTL (30d for prompt/param/code-fix, 90d for info-fix) into
     POSTMORTEMS.archive.md.

Respects MEMORY.md's 2200-char budget by evicting the oldest non-promoted
entries first when full.

Stdlib only — runs on Python 3.9+. No external deps.

Honest constraints, flagged as assumptions to verify:
  - Hermes' MEMORY.md uses § as entry delimiter (verified from
    /usr/local/lib/hermes-agent/tools/memory_tool.py docstring).
  - MEMORY.md char limit = 2200 (verified from same file:
    `MemoryStore.__init__(memory_char_limit=2200)`).
  - Promotion writes do not invalidate Hermes' frozen-snapshot system prompt
    mid-session — they take effect on the next session start.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
DEFAULT_MEMORY_DIR = DEFAULT_HERMES_HOME / "memories"

POSTMORTEMS_FILENAME = "POSTMORTEMS.md"
ARCHIVE_FILENAME = "POSTMORTEMS.archive.md"
MEMORY_FILENAME = "MEMORY.md"

PROMOTED_PREFIX = "[PROMOTED-FROM-POSTMORTEM]"
ENTRY_DELIM = "§"

MEMORY_CHAR_LIMIT = 2200  # matches Hermes default
DEFAULT_RECURRENCE_THRESHOLD = 3
PRUNE_TTL_DAYS = {
    "prompt-fix": 30,
    "param-fix": 30,
    "code-fix": 30,
    "info-fix": 90,
}


def _today() -> dt.date:
    return dt.date.today()


def _parse_date(s: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_postmortems(text: str) -> List[Dict[str, Any]]:
    """Parse §-delimited postmortem entries. Tolerant — skips malformed."""
    entries: List[Dict[str, Any]] = []
    raw_entries = [chunk.strip() for chunk in text.split(ENTRY_DELIM) if chunk.strip()]
    for raw in raw_entries:
        entry: Dict[str, Any] = {"_raw": raw}
        for line in raw.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "recurrence_count":
                try:
                    entry[key] = int(value)
                except ValueError:
                    entry[key] = 1
            elif key == "sessions":
                # Lazy parse: just keep as string list-ish
                value = value.strip("[]")
                entry[key] = [s.strip() for s in value.split(",") if s.strip()]
            else:
                entry[key] = value
        if entry.get("pattern"):
            entries.append(entry)
    return entries


def render_postmortem(entry: Dict[str, Any]) -> str:
    """Render a postmortem entry back to its §-delimited form."""
    field_order = [
        "pattern",
        "kind",
        "confidence_failure_mode",
        "canonical_correct_path",
        "resolution",
        "first_seen",
        "last_seen",
        "recurrence_count",
        "sessions",
    ]
    lines = []
    for key in field_order:
        if key not in entry:
            continue
        value = entry[key]
        if key == "sessions" and isinstance(value, list):
            value = "[" + ", ".join(value) + "]"
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def serialize_postmortems(entries: List[Dict[str, Any]]) -> str:
    """Render a list of postmortem entries back to §-delimited markdown."""
    if not entries:
        return ""
    rendered = [render_postmortem(e) for e in entries]
    return f"\n{ENTRY_DELIM}\n" + f"\n{ENTRY_DELIM}\n".join(rendered) + "\n"


def parse_memory(text: str) -> List[str]:
    """Parse MEMORY.md into a list of §-delimited entries (raw strings)."""
    return [chunk.strip() for chunk in text.split(ENTRY_DELIM) if chunk.strip()]


def serialize_memory(entries: List[str]) -> str:
    if not entries:
        return ""
    return f"\n{ENTRY_DELIM}\n" + f"\n{ENTRY_DELIM}\n".join(entries) + "\n"


def make_promoted_line(entry: Dict[str, Any]) -> str:
    pattern = entry.get("pattern", "unknown")
    canonical = entry.get("canonical_correct_path", "(no canonical path recorded)")
    count = entry.get("recurrence_count", 1)
    last_seen = entry.get("last_seen", "?")
    return f"{PROMOTED_PREFIX} {pattern}: {canonical} (seen {count}x, last {last_seen})"


def already_promoted(memory_entries: List[str], pattern: str) -> bool:
    needle = f"{PROMOTED_PREFIX} {pattern}:"
    return any(needle in m for m in memory_entries)


def promote(
    memory_dir: Path = DEFAULT_MEMORY_DIR,
    threshold: int = DEFAULT_RECURRENCE_THRESHOLD,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Promote postmortem entries with recurrence_count >= threshold."""
    pm_path = memory_dir / POSTMORTEMS_FILENAME
    mem_path = memory_dir / MEMORY_FILENAME

    pm_entries = parse_postmortems(_read_text(pm_path))
    mem_entries = parse_memory(_read_text(mem_path))

    promoted: List[str] = []
    for e in pm_entries:
        count = e.get("recurrence_count", 1)
        if not isinstance(count, int) or count < threshold:
            continue
        pattern = e.get("pattern")
        if not pattern:
            continue
        if already_promoted(mem_entries, pattern):
            continue
        line = make_promoted_line(e)
        mem_entries.append(line)
        promoted.append(pattern)

    # Enforce char budget
    new_memory = serialize_memory(mem_entries)
    while len(new_memory) > MEMORY_CHAR_LIMIT and len(mem_entries) > 0:
        # Evict oldest non-promoted entry first; if all are promoted, evict oldest
        evict_idx = next(
            (i for i, m in enumerate(mem_entries) if not m.startswith(PROMOTED_PREFIX)),
            0,
        )
        mem_entries.pop(evict_idx)
        new_memory = serialize_memory(mem_entries)

    result = {
        "promoted_patterns": promoted,
        "memory_entries_after": len(mem_entries),
        "memory_chars_after": len(new_memory),
    }

    if not dry_run and promoted:
        _write_text(mem_path, new_memory)

    return result


def prune(
    memory_dir: Path = DEFAULT_MEMORY_DIR,
    today: Optional[dt.date] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Move resolved old entries to POSTMORTEMS.archive.md."""
    today = today or _today()
    pm_path = memory_dir / POSTMORTEMS_FILENAME
    archive_path = memory_dir / ARCHIVE_FILENAME

    pm_entries = parse_postmortems(_read_text(pm_path))
    archive_entries = parse_postmortems(_read_text(archive_path))

    keep: List[Dict[str, Any]] = []
    moved: List[str] = []
    for e in pm_entries:
        last_seen = _parse_date(e.get("last_seen", ""))
        resolution = e.get("resolution", "")
        ttl = PRUNE_TTL_DAYS.get(resolution)
        if last_seen and ttl is not None:
            age_days = (today - last_seen).days
            if age_days > ttl:
                archive_entries.append(e)
                moved.append(e.get("pattern", "unknown"))
                continue
        keep.append(e)

    result = {
        "moved_patterns": moved,
        "active_entries_after": len(keep),
        "archive_entries_after": len(archive_entries),
    }

    if not dry_run and moved:
        _write_text(pm_path, serialize_postmortems(keep))
        _write_text(archive_path, serialize_postmortems(archive_entries))

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote recurring postmortem patterns into MEMORY.md."
    )
    parser.add_argument(
        "--memory-dir",
        default=str(DEFAULT_MEMORY_DIR),
        help=f"Path to memory directory (default: {DEFAULT_MEMORY_DIR}).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_RECURRENCE_THRESHOLD,
        help=f"Recurrence count needed to promote (default: {DEFAULT_RECURRENCE_THRESHOLD}).",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Also prune resolved old entries to POSTMORTEMS.archive.md.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing files.",
    )
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir).expanduser()

    promote_result = promote(
        memory_dir=memory_dir,
        threshold=args.threshold,
        dry_run=args.dry_run,
    )
    print("[promote]", promote_result)

    if args.prune:
        prune_result = prune(memory_dir=memory_dir, dry_run=args.dry_run)
        print("[prune]", prune_result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
