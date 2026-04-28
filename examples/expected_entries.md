# Expected Detection Output for `sample_session.json`

When `scripts/detect.py --input examples/sample_session.json` runs, it should produce these candidates (order may vary on ties; `selftest.py` sorts before comparing).

## Candidates

1. **Signal A: user correction** at turn 4
   - User said `"No, that's wrong — rotation is definitely documented."`
   - Prior agent claim: `"The collection has no chunks about rotation."`
   - High precision.

2. **Signal D: self-admission** at turn 5
   - Agent said `"Let me check that — I may have hit a connection issue."`
   - Medium precision.

3. **Signal B: tool retry** at turn 2 → turn 6
   - First call: `search(query=rotation, collection=docs_v7)` → empty
   - Retry: `search(query=rotation, collection=docs_v7, host=localhost)` → ok
   - High precision.

4. **Signal E: confidence-mismatch** at turn 3 → turn 4
   - Agent claim with no hedge: `"There's no documented procedure."`
   - User correction within 1 user turn.
   - Low precision (in `--strict` mode this is dropped).

5. **Signal D: self-admission** at turn 11
   - Agent said `"I assumed the host had torch installed."`
   - Medium precision.

6. **Signal B: tool retry** at turn 10 → turn 12
   - First call: `run_terminal_cmd(cmd=python tests/test_suite.py)` → error
   - Retry: `run_terminal_cmd(cmd=docker exec app-api python3 tests/test_suite.py)` → ok
   - High precision.

## Suggested Postmortem Entries (what the agent should write)

### Entry 1 — host vs container env
```
§
pattern: host-vs-docker-env-silent-empty-results
kind: env-config
confidence_failure_mode: Search returned 0 results from a host-side call; agent assumed the data was missing rather than the connection was wrong because no error was raised.
canonical_correct_path: For host-side scripts that talk to containerized infra, prefix with the localhost-overriding env vars (e.g. MILVUS_HOST=localhost). Tool descriptions should mention this pre-flight requirement.
resolution: param-fix
first_seen: 2026-04-28
last_seen: 2026-04-28
recurrence_count: 1
sessions: [sample-session-001]
```

### Entry 2 — GPU module on host
```
§
pattern: gpu-module-needs-docker-exec
kind: env-config
confidence_failure_mode: Agent ran a Python script directly on the host that imported torch; the host has no CUDA libs so the import failed at runtime, not at scan time.
canonical_correct_path: Any script importing torch / triggering GPU code must run via `docker exec app-api python3 <script>`. Tool description for run_terminal_cmd should document this for repos with containerized GPU services.
resolution: prompt-fix
first_seen: 2026-04-28
last_seen: 2026-04-28
recurrence_count: 1
sessions: [sample-session-001]
```

Both entries resolve via prompt-fix or param-fix — neither needs new code. This is the test that the investigation-order discipline is working.
