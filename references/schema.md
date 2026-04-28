# Postmortem Entry Schema

Entries live in `~/.hermes/memories/POSTMORTEMS.md`, separated by `§` (section sign — same delimiter as Hermes' `MEMORY.md`).

## Required Fields

```
§
pattern: <≤80 chars; lowercase-hyphen recommended>
kind: <one of the enum below>
confidence_failure_mode: <one sentence: WHY you were sure you were right>
canonical_correct_path: <one sentence: the verified correct action>
resolution: <one of: prompt-fix | param-fix | info-fix | code-fix>
first_seen: <YYYY-MM-DD>
last_seen: <YYYY-MM-DD>
recurrence_count: <int ≥ 1>
sessions: [<session-id>, ...]
```

All fields are required. Missing fields cause `scripts/detect.py --strict` to reject the entry.

## Field Reference

### `pattern` (string, ≤80 chars)
A short, stable, lowercase-hyphen identifier for the failure class. **Stable across recurrences** — if you write a similar entry next month, it should re-use the same pattern. Stability is what makes recurrence detection work.

Good: `host-vs-docker-env-silent-empty-results`, `regex-bypass-instead-of-prompt-fix`
Bad: `error in tools/foo.py line 142 on Tuesday` (specific, not a class)

### `kind` (enum)
The failure category. Used for filtering and analysis. Pick from:

- `env-config` — env vars, paths, credentials, host/container mismatches
- `api-drift` — method names, params, return types changed between sessions
- `silent-crash` — process exited 0 but produced wrong/empty output
- `fixed-pipeline` — hardcoded if/else, regex, or routing table that should be LLM
- `context-overflow` — prompt + chunks + history exceeded model context
- `unsafe-shortcut` — destructive op (rm, force-push, db-drop) without confirm
- `hallucinated-api` — agent invented a method/param/file that doesn't exist
- `other` — when none of the above fit (use sparingly; consider extending the enum)

### `confidence_failure_mode` (string, one sentence)
**Why** you were sure you were right. This is the metacognitive payload — it's what makes the entry useful for future-you.

Good: `"Silent empty results from a containerized vector store looked like 'no matching docs' but actually meant 'connection failed because the agent used the Docker hostname from the host shell'."`
Bad: `"I was wrong."` (no information about the confidence failure)

### `canonical_correct_path` (string, one sentence)
The verified correct action. Should be specific enough that a future invocation can copy-paste the fix.

Good: `"For host-side scripts that talk to a containerized service, prefix with the localhost-overriding env var (e.g. DB_HOST=localhost). Document this in the tool description so the agent doesn't have to rediscover it."`
Bad: `"Use the right env vars."`

### `resolution` (enum)
Where the fix actually lives. One of:

- `prompt-fix` — system prompt or skill description gained a rule / few-shot
- `param-fix` — tool schema gained a parameter or refined a description
- `info-fix` — observation now exposes data the agent needs
- `code-fix` — actual control-flow code changed

Order of preference: `prompt-fix` > `param-fix` > `info-fix` > `code-fix`. See `investigation-order.md`.

### `first_seen` / `last_seen` (date, YYYY-MM-DD)
When the failure pattern first occurred and most recently recurred. Used for pruning.

### `recurrence_count` (int)
Bumped by `scripts/promote.py` when it detects a re-occurrence. Starts at 1.

When `recurrence_count >= 3`, the entry is **promoted**: a terse rule is appended to `~/.hermes/memories/MEMORY.md` so the system prompt enforces it on every future session.

### `sessions` (list of session IDs)
Hermes session IDs in which this failure occurred. Used by recurrence detection to prove the failure is across sessions, not within one.

## Example Entry (filled)

```
§
pattern: host-vs-docker-env-silent-empty-results
kind: env-config
confidence_failure_mode: Silent empty results from a containerized service looked identical to "no matching records" — agent assumed the data was missing rather than the connection was broken because the host shell was using the Docker-internal hostname.
canonical_correct_path: For host-side Python that talks to containerized infra, prefix the command with the localhost-overriding env vars (e.g. DB_HOST=localhost). Document this in the tool description and add a fail-fast check inside the tool.
resolution: param-fix
first_seen: 2026-04-10
last_seen: 2026-04-22
recurrence_count: 4
sessions: [a1b2c3, d4e5f6, g7h8i9, j0k1l2]
```

This entry resolved at `recurrence_count=3` by adding a `verify_connection` step to the tool's pre-flight check (param-fix) and a system-prompt note (prompt-fix). At count 4 it should be archived; the promoted rule in `MEMORY.md` is doing the work.

## Promoted-Rule Format (in MEMORY.md)

When a postmortem entry hits `recurrence_count >= 3`, this terse line lands in `~/.hermes/memories/MEMORY.md`:

```
[PROMOTED-FROM-POSTMORTEM] <pattern>: <canonical_correct_path>. (seen Nx, last YYYY-MM-DD)
```

Stays under the 2200-char `MEMORY.md` budget. Older non-promoted entries are evicted first when budget is tight.
