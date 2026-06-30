# Project Rules

## Project-Local PlanDB

This project uses a project-local PlanDB task graph for Codex coordination.
It must stay independent from other projects and from global Codex state.

### Required First Step

When starting non-trivial project work, inspect PlanDB status from the project root:

```bash
./tools/plandb status --detail
```

If the user asks for work that has more than three meaningful steps, may span
sessions, or benefits from task handoff, claim a ready task before doing the work:

```bash
PLANDB_AGENT=codex-main ./tools/plandb go
```

Use a more specific agent name when appropriate:

```bash
PLANDB_AGENT=codex-research ./tools/plandb go
PLANDB_AGENT=codex-builder ./tools/plandb go
PLANDB_AGENT=codex-reviewer ./tools/plandb go
PLANDB_AGENT=codex-debugger ./tools/plandb go
```

Only work on the task you claimed.

### Shared Project Memory

Write durable project coordination information to PlanDB context:

```bash
./tools/plandb context "Decision or discovery." --kind decision
./tools/plandb context "Important constraint." --kind constraint
./tools/plandb context "Unresolved blocker." --kind blocker
./tools/plandb context "Reusable pattern." --kind pattern
```

Use these kinds by default:

- `decision`
- `constraint`
- `blocker`
- `discovery`
- `risk`
- `pattern`
- `handoff`

### Completing Work

Complete claimed tasks with a structured result:

```bash
PLANDB_AGENT=codex-main ./tools/plandb done --result '{"summary":"...", "verification":"...", "risks":[]}'
```

If verification was not run, say so in the result:

```bash
PLANDB_AGENT=codex-main ./tools/plandb done --result '{"summary":"...", "verification":"not run", "risks":["..."]}'
```

### Priority Inspection

Use these commands when deciding what to do next:

```bash
./tools/plandb list --status ready
./tools/plandb critical-path
./tools/plandb bottlenecks
./tools/plandb search "keyword"
```

PlanDB search is keyword/BM25 search, not semantic search. Use concrete terms.

### Trial Boundaries

- Use only `./tools/plandb`.
- Use only this project's `.plandb.db`.
- Do not copy, attach, or reuse another project's `.plandb.db`.
- Do not run the official PlanDB install script.
- Do not modify `~/.codex` for PlanDB.
- Do not enable PlanDB MCP or HTTP server.
- Do not commit `.plandb.db` or `.plandb.db-*`.

Detailed protocol: `docs/plandb-codex-protocol.md`.

## Stock Review Continuity

- For any stock review, paper-trading, daily report, or trading-journal task, continue from the existing documents and ledgers by default.
- Do not create a parallel/new review document, table, or ledger unless the user explicitly asks for a new artifact.
- Before answering or editing, read the continuity memory first when available:
  `/Users/hanlinye/.codex/memories/extensions/ad_hoc/notes/2026-06-09-paper-trading-continuity.md`
- Then read the existing project records:
  `trading-journal/ledger/orders.csv`,
  `trading-journal/ledger/positions.csv`,
  `trading-journal/ledger/equity_curve.csv`,
  and relevant files under `trading-journal/daily/` and `trading-journal/reviews/`.
- Treat carried positions as continuous across days unless a strategy explicitly triggers an exit or the user confirms a sell/close.
