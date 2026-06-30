# PlanDB Codex Protocol

This project uses PlanDB as a local task graph for Codex coordination.

Scope for this trial:

- Use only the project-local binary at `tools/plandb`.
- Use only the project-local database at `.plandb.db`.
- Keep this project independent from other projects' PlanDB databases.
- Do not run the official PlanDB install script.
- Do not modify `~/.codex` or any global Codex configuration for PlanDB.
- Do not enable PlanDB MCP or HTTP server during the trial.
- Do not commit `.plandb.db` or SQLite sidecar files.

## When To Use PlanDB

Use PlanDB by default for work in this project when the task has any of these properties:

- More than three meaningful steps.
- Multiple Codex threads or agents may work in parallel.
- Clear dependency order exists.
- Work may continue across days or sessions.
- Important decisions, blockers, or constraints must be preserved.
- The work affects architecture, trading-journal continuity, automation, deployment, or rollback.

Do not use PlanDB for:

- One-off questions.
- Simple command lookup.
- Typo fixes.
- Small single-file edits.
- Disposable terminal checks.

## Command Prefix

Run PlanDB from the project root:

```bash
./tools/plandb status --detail
```

Use explicit agent names when claiming or completing tasks:

```bash
PLANDB_AGENT=codex-main ./tools/plandb go
PLANDB_AGENT=codex-research ./tools/plandb go
PLANDB_AGENT=codex-builder ./tools/plandb go
PLANDB_AGENT=codex-reviewer ./tools/plandb go
PLANDB_AGENT=codex-debugger ./tools/plandb go
```

Default roles:

- `codex-main`: primary thread and task owner.
- `codex-research`: research and source review.
- `codex-builder`: implementation.
- `codex-reviewer`: review, verification, risk checks.
- `codex-debugger`: focused debugging.

## Task Rules

Every task should have:

- A clear title.
- A stable `--as` id in short kebab-case.
- A self-contained `--description`.
- A `--kind`: `research`, `code`, `test`, `review`, `shell`, or `generic`.
- Dependencies via `--dep` when order matters.
- A `--pre` condition when task readiness is not obvious.
- A `--post` condition that defines completion.

Example:

```bash
./tools/plandb add "Draft current project roadmap" \
  --as roadmap \
  --kind research \
  --pre "Project goal is understood" \
  --post "Roadmap lists priorities, risks, and next task graph" \
  --description "Summarize current project state and define the next execution roadmap."
```

## Execution Loop

Standard loop:

```bash
./tools/plandb status --detail
PLANDB_AGENT=codex-main ./tools/plandb go
# Do the work.
./tools/plandb context "Important decision or discovery." --kind decision
PLANDB_AGENT=codex-main ./tools/plandb done --result '{"summary":"...", "verification":"...", "risks":[]}'
./tools/plandb status --detail
```

Use these commands to inspect priority:

```bash
./tools/plandb critical-path
./tools/plandb bottlenecks
./tools/plandb list --status ready
```

## Context Rules

Record only information that should survive the current conversation.

Use these `--kind` values:

- `decision`: confirmed decision.
- `constraint`: explicit constraint or forbidden action.
- `blocker`: unresolved blocker.
- `discovery`: important finding.
- `risk`: known risk.
- `pattern`: reusable workflow or implementation pattern.
- `handoff`: continuation summary.

Examples:

```bash
./tools/plandb context "Do not run the official PlanDB install script during this trial." --kind constraint
./tools/plandb context "Use project-local .plandb.db; do not reuse another project's PlanDB database." --kind decision
```

PlanDB search is BM25 keyword search, not semantic search. Prefer concrete keywords:

```bash
./tools/plandb search "portfolio ledger"
```

## Completion Rules

`done` must include a structured result. Do not mark a task done with no useful handoff.

Recommended shape:

```json
{
  "summary": "What changed",
  "verification": "What was checked",
  "files": ["Relevant files"],
  "risks": ["Remaining risks"]
}
```

If verification was not run, say so explicitly:

```json
{
  "summary": "Task completed",
  "verification": "not run",
  "risks": ["Reason verification was skipped"]
}
```

## Rollback

To remove this project trial:

```bash
rm -f tools/plandb
rm -f .plandb.db .plandb.db-*
rm -f docs/plandb-codex-protocol.md
```

No global files should need cleanup because this trial does not modify global Codex configuration.
