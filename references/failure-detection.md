# Failure Detection Signals

Hermes skills are **LLM-invoked**, not event-fired. So failure detection happens in two surfaces:

1. **In-session, agent-driven** — the agent itself notices a failure pattern and invokes this skill via its tools.
2. **Post-session, hook-driven** — `hooks/post_session.sh` runs `scripts/detect.py` against the transcript at session end (no agent reasoning required).

Both surfaces look for the same signal types.

## Signal Types

### A. User-correction signals (high precision)

The user explicitly flags the agent's previous output as wrong. These are the highest-confidence failure events.

**Trigger phrases (any language, normalized):**
- English: `no, that's wrong`, `actually`, `undo`, `not what I asked`, `you should have`, `wait —`, `revert`
- Korean: `아니`, `그게 아니라`, `잘못`, `다시`, `그건 틀려`
- Universal: any message starting with negation + reference to prior turn

**Detector heuristic:** if the user message at turn N (a) contains a correction-class verb/phrase AND (b) refers to actions in turn N-1, mark it.

### B. Tool-retry signals (high precision)

The agent called a tool, got an error or empty result, then called the same tool with modified arguments within the same turn or the next.

**Detector heuristic:** group tool-call events by tool name within a sliding window of 3 calls. If the first call had `error` or `empty_result` AND a subsequent call has different args, flag the pair.

**Edge cases:**
- Pagination retries with `next_cursor`-style args do NOT count (legitimate flow).
- Read-then-write patterns (read fails → write succeeds) do NOT count (different semantics).

### C. Rollback signals (medium precision)

Destructive-undo actions ran. Strong signal that something went wrong, weaker signal about *what*.

**Triggers:**
- `git reset`, `git checkout --`, `git stash`, `git revert`
- File restored from a backup (`cp foo.bak foo`)
- `rm` followed by `Read` of the same path that errors
- A previously-launched background process killed (`kill`, `pkill`)
- Edit reverted (Edit tool with old_string/new_string that exactly inverts a recent edit)

### D. Self-admission signals (medium precision)

The agent admits in a message that it was wrong, uncertain, or assumed.

**Trigger phrases (in agent output):**
- `I was wrong`, `let me check that`, `I assumed`, `actually,` (mid-paragraph), `correction:`, `sorry, that was incorrect`, `on second look`

**Caveat:** these are noisier than A/B/C — agents often use these phrases as conversational filler. Combine with another signal (e.g. self-admission + tool retry within 3 turns) for higher precision.

### E. Confidence-mismatch signals (low precision, high information value when matched)

The agent produced a high-confidence answer that was disputed within 2 turns. Hard to detect without a confidence score, but pattern-match:

**Trigger pattern:**
- Agent message contains a definitive claim (no hedge phrases like "I think", "should be", "probably")
- Followed within 2 user turns by a correction signal (type A)

**Detector heuristic:** count hedges in the agent message (regex over the small set: `I think`, `probably`, `might be`, `not sure`, `should be`, `let me verify`). If count == 0 AND a type-A correction follows within 2 turns, flag.

### F. Pre-tool guardrail violations (high precision when instrumented)

The agent attempted an operation against a known guardrail and was caught.

**Triggers (require Hermes hooks instrumentation):**
- Permission deny from a hook
- Pre-tool-use validator rejection
- A `system-reminder` flagged the agent for an out-of-spec action

These are the cleanest signals — only fire when there's hard guardrail enforcement.

## Precision/Recall Tradeoffs

| Signal | Precision | Recall | Notes |
|---|---|---|---|
| A. User correction | High | High | Best signal — use as primary |
| B. Tool retry | High | Medium | Misses logic errors with no tool retry |
| C. Rollback | Medium | Low | Strong WHEN it fires, but rare |
| D. Self-admission | Medium | High | Combine with another signal |
| E. Confidence mismatch | Low | Medium | Useful as a tie-breaker, not standalone |
| F. Guardrail violations | High | Low | Only when instrumented |

## What NOT to Flag

False positives are worse than false negatives — a bad postmortem corpus is worse than no corpus.

- **Pagination retries** (B-shaped but not failures)
- **Iterative refinement loops** (`grep` → `grep` → `grep` searching for the right pattern is normal)
- **Exploratory tool use** (`ls`, `find`, `cat` to understand state)
- **Test-then-fix patterns** (run test → see failure → fix → re-run)
- **User reformulating** ("actually, can you also...") — this is request expansion, not correction

`scripts/detect.py` implements these exclusions.

## Per-Skill Notes for In-Session Use

When invoking this skill mid-session, use the trigger list in `SKILL.md` as your decision criterion. You're allowed to be more aggressive than the automated detector — better to write a postmortem and reject it than to miss a real failure mode.
