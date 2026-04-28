# Why this exists

> *Agents are great, but they make mistakes. What matters most is how you deal with the mistake — and how you make sure it never happens again. This postmortem is designed around one discipline: **remember your mistake, never make the same mistake again.***

## The problem

The current generation of agent frameworks (Hermes, Claude Agent SDK, LangGraph, AutoGen, Cursor, Copilot) all ship some form of "memory." Almost all of those memories are **success-biased**:

- Hermes auto-generates skills from *"repeated patterns and **successful** interactions."*
- Cursor's "rules" capture project conventions and user preferences.
- ChatGPT's memory stores facts the model is told to remember.
- LangGraph's checkpoint state is whatever survived the happy path.

What none of them do well: **learn from the cases where the agent was confidently wrong.**

This is the opposite of how engineers actually grow. We don't grow by filing away our successes — we grow by writing postmortems for our failures. The five-whys document, the incident retrospective, the "I won't do that again" memo. These are the artifacts that make experienced engineers experienced. Agents currently lack the equivalent.

## The intuition

When you run an agent in production for any length of time, you watch it make the **same kind of mistake repeatedly across sessions**. The model is the same. Its "context" is the same. Its tools are the same. And yet, week after week, it walks into the same trap.

That's not a model-quality problem. It's a memory-discipline problem.

You — the human operator — eventually learn to add a guardrail: a rule in CLAUDE.md, a sentence in the system prompt, a new tool parameter. The agent, with that guardrail in place, stops walking into the trap. But the guardrail came from *you* noticing the pattern and writing it down. The agent had no path to do that for itself.

This skill gives the agent that path.

## The discipline

Three things had to come together to make a failure memory actually useful:

### 1. A failure-triggered write loop

Successes file themselves. Failures don't — they evaporate when the conversation ends. So the skill ships explicit signal detection:

- User correction phrases (`"no, that's wrong"`, `"actually..."`, `"undo"`)
- Tool retries with modified args after error/empty result
- Rollback signals (`git reset`, file restored, edit reverted)
- Self-admissions (`"I was wrong"`, `"let me check that"`, `"I assumed"`)
- Confidence-mismatch (definitive claim followed by user correction within 2 turns)

When any signal fires, an entry gets written. No reliance on the agent voluntarily filing its own mistakes — those rarely get filed.

### 2. A schema that forces actionable entries

A freeform "I got X wrong" diary line is worse than nothing — it's noise that accumulates. So entries are typed:

- `pattern` — a stable, lowercase-hyphen identifier (lets future entries deduplicate against past ones)
- `confidence_failure_mode` — *why you were sure you were right* (the metacognitive payload)
- `canonical_correct_path` — the verified right action
- `resolution` — one of `prompt-fix | param-fix | info-fix | code-fix`

The `resolution` field is load-bearing. It enforces an iron law: **no entry whose resolution is "the model is bad at X."** Every entry must route to a fixable thing — a prompt edit, a tool-schema tweak, an observation-shape change, or (last resort) code.

### 3. Cross-session promotion when a pattern recurs

A postmortem entry by itself doesn't change behavior — it sits in a corpus the agent reads sometimes. Behavior change happens when a rule lands in the **system prompt itself**, where the model can't ignore it.

So when a pattern's `recurrence_count` hits 3, a one-line `[PROMOTED-FROM-POSTMORTEM]` rule gets written into MEMORY.md, which Hermes auto-injects into the next session's system prompt. The next session starts with the rule active. The trap is closed.

This is what makes the skill a *learning loop* rather than a *filing cabinet*: failure → record → recur → promote → behavior change.

## The evidence

The cleanest proof of usefulness is a behavioral A/B with a fabricated rule (so the model can't have learned it from training data).

A fictional CLI tool — `gizmo-cli sync` — was given a fictional gotcha: it silently overwrites newer files with older ones unless `--clobber-mode=keep-newest` is passed. This rule was injected into POSTMORTEMS.md with `recurrence_count=4`, then promoted into MEMORY.md.

**Before the rule was in MEMORY.md**, asked to write the command, the agent produced: `gizmo-cli sync .`

**After the rule was in MEMORY.md**, asked the same question in a fresh session, the agent produced: `gizmo-cli sync --clobber-mode=keep-newest .`

Identical model. Identical prompt. Identical tools. The only difference: the postmortem-promoted rule was in the system prompt for the second call. Behavior changed.

That's the loop closing.

## What this is *not*

- **Not a substitute for `systematic-debugging`** — that skill is for debugging *user code*. This skill is for debugging *the agent's own behavior*.
- **Not a venting log** — entries that don't route to a prompt/param/info/code fix get rejected by `detect.py --strict`.
- **Not a replacement for MEMORY.md** — postmortems live separately. Only promoted rules cross the bridge.
- **Not opinionated about the rest of your stack** — works with any LLM backend Hermes supports (tested on a local 26B model; should work on anything that follows system-prompt rules).

## The bigger frame

The interesting thing about agent reliability isn't that models hallucinate. We've known that for years. The interesting thing is that **the operational discipline around an agent matters more than the model's raw capability**. A 26B parameter model with good memory discipline beats a 405B model with no postmortem loop on the failure modes you've already encountered.

This skill is a small, specific bet on that intuition: that giving an agent the same postmortem discipline a senior engineer practices would close more failure modes than upgrading the model.

We can be wrong about that. The discipline of being willing to find out is what this skill is, in the end, about.
