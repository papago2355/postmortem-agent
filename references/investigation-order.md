# Investigation Order: prompt → param → info → code

The default reflex when an agent fails is "write code to scaffold around the model." This is a trap. It rots the moment the model is upgraded, and it loses the LLM's ability to handle adjacent cases.

This rule inverts the reflex. **Code patches are hypothesis 4 of 4, not hypothesis 1.**

## The Four Hypotheses

### 1. Missing tool param

> "Could a new param on an existing tool let the agent express what's being asked?"

**Symptom:** the agent passed the wrong field, or used a workaround like concatenating values into a `query` string when a structured field would have been cleaner.

**Fix shape:** add a parameter to a tool, document it in the tool description, give the agent one example. **No regex inside the tool.**

**Example:**
- Bad: agent searches for "고형제" (oral solid form) → no results → gets clever and adds `if "고형제" in query: filter_by_dosage_form_codes(...)` to the search code.
- Good: tool gains a `title_contains` param. Agent now expresses the constraint structurally.

### 2. Missing prompt instruction

> "Does the agent know this case exists?"

**Symptom:** the agent is technically capable of the right behavior but doesn't think to do it. It picks the wrong tool, or stops short, or misses an obvious verification step.

**Fix shape:** one sentence in the system prompt, ideally with one few-shot example. The system prompt is documentation FOR THE AGENT — treat it as such.

**Example:**
- Bad: agent answers a multi-turn followup by re-running the original search instead of filtering the prior result. Engineer adds 30 lines of session-state inheritance code.
- Good: prompt gains "When the user says `X만` (only X), filter the most recent results by X — do not re-search." with one example. Three lines.

### 3. Missing observation info

> "Does the LLM see what it needs to make the call?"

**Symptom:** the agent's reasoning is correct **given what it saw**, but what it saw was incomplete. Counts hidden, distributions hidden, schema fields not exposed, prior-turn context dropped.

**Fix shape:** surface the missing info in the observation — tool result, agent observation summary, or prior-turn metadata. The agent already wants to do the right thing; it just needs the data.

**Example:**
- Bad: agent says "no records found" when there are 200 records but only 5 matched the filter. Engineer adds a fallback in the answer-generation step to detect "0 results" and re-search.
- Good: tool observation now includes `total_records: 200, matched: 5, filter: {...}`. Agent now answers correctly with the same code.

### 4. Code fix (last resort)

> "Is this a real engineering constraint that no prompt or schema change can address?"

**When code is genuinely the answer:**
- vLLM context overflow (real GPU/memory limit)
- Streaming SSE event the frontend depends on (UI contract)
- Schema mismatch where the data field literally doesn't exist
- Budget enforcement against runaway tool-call loops
- A hallucination the verifier catches that no prompt edit will eliminate

If your symptom **isn't** on this short list, the fix probably belongs in 1, 2, or 3.

## The Three-Question Test

Before writing code, answer all three. If you cannot answer "yes / yes / yes", the fix belongs upstream.

1. **Reproducibility**: does the same model, with a better prompt or one extra param, get this case right? *(If yes → prompt-fix or param-fix.)*
2. **Generality**: does my proposed code patch help just this one case, or a real class of inputs? *(Single-case patches are almost always prompt issues in disguise.)*
3. **Reversibility**: would the patch survive a model upgrade or a recipe refactor? *(Hardcoded routing tables and fixed if-else chains rot the moment the agent's behavior shifts. Prompt/param fixes don't.)*

## Symptoms → Where the Fix Lives

| Symptom | Hypothesis |
|---|---|
| "The agent doesn't know about X" | prompt |
| "The agent passes the wrong field" | tool schema description |
| "The agent picks the wrong tool" | system prompt rule + few-shot |
| "The agent miscounts" | observation summary |
| "The agent ignores prior context" | observation metadata |
| "The user said X but the agent searched Y" | few-shot example |
| "Same mistake every session" | promotion to `MEMORY.md` |
| "vLLM ran out of context" | code |
| "Streaming dropped a field" | code |
| "Loop ran 50 iterations" | code (budget) |

## Why This Order Matters

**Prompt/param/info fixes survive model upgrades.** Code patches that scaffold the LLM's behavior break when the model changes — sometimes silently. Every "if/else for semantic routing" is one regression away from a confidently wrong production answer.

**Prompt/param/info fixes generalize.** A new system-prompt rule helps with the failing case AND adjacent cases the user hasn't even hit yet. A code patch helps with one case.

**Prompt/param/info fixes are reversible.** Edit a prompt → revert with one commit. Add a hardcoded routing table → debug it for six months.

This order is the operational discipline that makes the failure-memo actually useful. Without it, you fill `POSTMORTEMS.md` with "the model is bad at X" entries and nothing changes.
