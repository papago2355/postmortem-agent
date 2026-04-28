#!/usr/bin/env python3
"""
detect.py — Parse a session transcript and emit postmortem candidates.

Reads a JSON transcript on --input (or stdin) and emits a JSON list of
failure-signal hits. Each candidate carries enough context that the agent
(or a human reviewer) can decide whether to write a full postmortem entry.

Transcript schema (generic — adapt to your platform):
    {
      "session_id": "abc123",
      "turns": [
        {
          "role": "user" | "agent" | "tool",
          "content": "...",
          "tool_name": "...",          # role=tool only
          "tool_args": {...},          # role=tool only
          "tool_status": "ok"|"error"|"empty",  # role=tool only
        }, ...
      ]
    }

Stdlib only — runs on Python 3.9+. No external deps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

# ---- Signal A: user correction phrases (high precision) -----------------

_CORRECTION_PHRASES = [
    # English
    r"\bno,?\s+that'?s\s+wrong\b",
    r"\bactually\b",
    r"\bundo\b",
    r"\bnot\s+what\s+i\s+asked\b",
    r"\byou\s+should\s+have\b",
    r"\bwait\s*[—-]\b",
    r"\brevert\b",
    r"\bthat'?s\s+not\s+right\b",
    r"\bincorrect\b",
    # Korean
    r"아니",
    r"그게\s*아니",
    r"잘못",
    r"틀려",
    r"틀렸",
]
_CORRECTION_RE = re.compile("|".join(_CORRECTION_PHRASES), re.IGNORECASE)


# ---- Signal D: self-admission phrases (medium precision) ----------------

_SELF_ADMIT_PHRASES = [
    r"\bi\s+was\s+wrong\b",
    r"\blet\s+me\s+check\b",
    r"\bi\s+assumed\b",
    r"\bcorrection:\b",
    r"\bsorry,?\s+that\s+was\s+incorrect\b",
    r"\bon\s+second\s+look\b",
    r"\bmy\s+mistake\b",
]
_SELF_ADMIT_RE = re.compile("|".join(_SELF_ADMIT_PHRASES), re.IGNORECASE)


# ---- Hedge phrases (used to score confidence-mismatch in signal E) ------

_HEDGE_RE = re.compile(
    r"\b(i\s+think|probably|might\s+be|not\s+sure|should\s+be|let\s+me\s+verify)\b",
    re.IGNORECASE,
)


def _slugify(text: str, max_len: int = 64) -> str:
    """Reduce a snippet to a stable lowercase-hyphen slug."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:max_len] or "untitled-pattern"


def detect_user_corrections(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Signal A — user correction phrases at turn N referencing turn N-1."""
    hits = []
    for i, turn in enumerate(turns):
        if turn.get("role") != "user":
            continue
        content = turn.get("content", "") or ""
        if not _CORRECTION_RE.search(content):
            continue
        prior = turns[i - 1] if i > 0 else None
        if prior is None or prior.get("role") not in ("agent", "tool"):
            continue
        hits.append(
            {
                "signal": "A:user-correction",
                "turn_index": i,
                "user_snippet": content[:240],
                "agent_prior_snippet": (prior.get("content") or "")[:240],
                "suggested_pattern": _slugify(content[:80]),
                "precision": "high",
            }
        )
    return hits


def detect_tool_retries(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Signal B — same tool called twice in a 3-turn window after error/empty."""
    hits = []
    for i in range(len(turns) - 1):
        turn = turns[i]
        if turn.get("role") != "tool":
            continue
        if turn.get("tool_status") not in ("error", "empty"):
            continue
        tool_name = turn.get("tool_name")
        if not tool_name:
            continue
        # Look forward for the next same-tool call (window covers intervening
        # agent reasoning + user clarification). 8 turns handles the common
        # "tool fails → agent reflects → user clarifies → agent retries" loop.
        for j in range(i + 1, min(i + 9, len(turns))):
            next_turn = turns[j]
            if next_turn.get("role") != "tool":
                continue
            if next_turn.get("tool_name") != tool_name:
                continue
            if next_turn.get("tool_args") == turn.get("tool_args"):
                continue
            hits.append(
                {
                    "signal": "B:tool-retry",
                    "turn_index": i,
                    "retry_index": j,
                    "tool_name": tool_name,
                    "first_status": turn.get("tool_status"),
                    "first_args": turn.get("tool_args"),
                    "retry_args": next_turn.get("tool_args"),
                    "suggested_pattern": _slugify(f"retry-{tool_name}"),
                    "precision": "high",
                }
            )
            break
    return hits


def detect_self_admissions(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Signal D — agent admits being wrong / uncertain in its own message."""
    hits = []
    for i, turn in enumerate(turns):
        if turn.get("role") != "agent":
            continue
        content = turn.get("content", "") or ""
        if not _SELF_ADMIT_RE.search(content):
            continue
        hits.append(
            {
                "signal": "D:self-admission",
                "turn_index": i,
                "agent_snippet": content[:240],
                "suggested_pattern": _slugify(content[:80]),
                "precision": "medium",
            }
        )
    return hits


def detect_confidence_mismatch(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Signal E — definitive agent claim followed by user correction within 2 turns."""
    hits = []
    for i, turn in enumerate(turns):
        if turn.get("role") != "agent":
            continue
        content = turn.get("content", "") or ""
        if _HEDGE_RE.search(content):
            continue  # hedged — not a confidence mismatch
        # Look forward up to 2 user turns for a correction
        user_turns_seen = 0
        for j in range(i + 1, len(turns)):
            t = turns[j]
            if t.get("role") == "user":
                user_turns_seen += 1
                if _CORRECTION_RE.search(t.get("content") or ""):
                    hits.append(
                        {
                            "signal": "E:confidence-mismatch",
                            "turn_index": i,
                            "correction_index": j,
                            "agent_claim_snippet": content[:240],
                            "user_correction_snippet": (t.get("content") or "")[:240],
                            "suggested_pattern": _slugify(content[:80]),
                            "precision": "low",
                        }
                    )
                    break
                if user_turns_seen >= 2:
                    break
    return hits


def detect_all(transcript: Dict[str, Any], strict: bool = False) -> List[Dict[str, Any]]:
    """Run every signal detector and return combined candidates."""
    turns = transcript.get("turns", [])
    if not isinstance(turns, list):
        return []
    hits: List[Dict[str, Any]] = []
    hits.extend(detect_user_corrections(turns))
    hits.extend(detect_tool_retries(turns))
    hits.extend(detect_self_admissions(turns))
    hits.extend(detect_confidence_mismatch(turns))
    if strict:
        # In strict mode, drop low-precision standalone signals
        hits = [h for h in hits if h.get("precision") != "low"]
    # Stable sort: by turn_index, then signal name
    hits.sort(key=lambda h: (h.get("turn_index", 0), h.get("signal", "")))
    return hits


def _read_input(path: Optional[str]) -> Dict[str, Any]:
    if path and path != "-":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.load(sys.stdin)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect failure signals in a session transcript."
    )
    parser.add_argument(
        "--input",
        "-i",
        default="-",
        help="Path to transcript JSON, or '-' for stdin (default: stdin).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Drop low-precision standalone signals (E without A/B reinforcement).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "human"],
        default="json",
        help="Output format (default: json).",
    )
    args = parser.parse_args()

    transcript = _read_input(args.input)
    candidates = detect_all(transcript, strict=args.strict)

    if args.format == "json":
        json.dump(
            {"session_id": transcript.get("session_id"), "candidates": candidates},
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        if not candidates:
            print("No failure signals detected.")
            return 0
        print(f"{len(candidates)} candidate(s):")
        for c in candidates:
            print(f"  - turn {c.get('turn_index')}: {c.get('signal')} "
                  f"({c.get('precision')}) → pattern: {c.get('suggested_pattern')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
