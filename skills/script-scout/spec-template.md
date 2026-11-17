# Spec template: scripts from usage

Fill every section. A section with nothing to say says "none" and why. Quote the user exactly; take every number from the scan or a measurement and say which.

```markdown
# SPEC · <project or "all projects"> · scripts from usage

*<weekday> <date>.*

Status: ready-for-agent

- **Made with:** script-scout (`/script-scout <scope>`), from the user's messages of <dates>:
  - "<the user's words, quoted exactly>"
- **The user's decisions (<date>):**
  - <each kept or dropped candidate, and any rule the user set>
- **Facts checked (<date>):**
  - Scan: <scope>, <sessions> sessions, <first>..<last>, <tool calls> tool calls.
  - <each measurement: command, lines, bytes, ≈ tokens>
  - <what already exists: scripts, skills, native features, and why each does or doesn't cover a pattern>
  - History: <verdicts on earlier decisions, or "first run">

## Safety Rules

The project's own rules (from its CLAUDE.md / AGENTS.md / contributing docs) that these scripts touch, restated. Then these, which every script keeps:

- Input is validated: names can't hold path separators or `..`; unknown commands print the list.
- Writes are atomic: temporary file, then rename. A failed run writes nothing.
- Every error names its stage.
- No secrets, environment values or prompt text in output.
- Read-only unless the command's name says it writes.
- Tests never touch real external systems (deploys, services, hardware, accounts).

## Problem Statement

What the user and the agent keep doing, how often, and what it costs, from the user's side.

## Solution

What the user gets: the scripts, how they invoke them, and what it saves, in two or three sentences.

## Evidence

| Pattern | Uses | ≈ tokens per use | ≈ total | Output or input | Source |
|---|---|---|---|---|---|
| <family / sequence / hot file> | | | | | <scan table and row> |

## Scripts

One block per script:

### <name>

- **Rung:** <flag / existing script / native feature / skill / new script>, and why the rungs above don't cover it.
- **Lives in:** <path>; on PATH as `<name>`.
- **Replaces:** <patterns from Evidence>.

| Command | Prints (max lines) | Reads | Writes | Replaces |
|---|---|---|---|---|
| `<name> <command> [args]` | <example output> | | | |

- **How it works:** <steps, in order>.
- **On failure:** <exact shape of the output and exit code>.
- **Invoked by:** the agent via Bash; the user via `/<skill-name>` (`disable-model-invocation: true`, `` !`<name> <command> $ARGUMENTS` ``); the pointer line it adds to <CLAUDE.md / skill>.

## User Stories

A long, numbered list covering every command and failure: 1. As <the user / the agent>, I want <feature>, so that <benefit>.

## Implementation Decisions

Modules or files built or changed, interfaces, output formats, where state is kept, ordering rules, anything the user decided. No code beyond a short snippet that pins a decision more precisely than prose.

## Token Budget

| Script command | Before (≈ tokens per use) | After | Uses per month | ≈ saved per month |
|---|---|---|---|---|

Standing cost: <0 for user-invoked skills and plain CLIs; the size of any always-loaded line added>.

## Testing Decisions

- A good test runs the script as a subprocess on a temporary fixture and checks what it prints and writes, never its internals.
- Cases: <one per command and failure>.
- What only the user can check (slash commands appearing, status line, behaviour in a new session), listed separately.

## Rollout Order

Ticket-sized slices in build order, each with what it waits on: 1. <script, command> (blocked by: none).

## Learning Loop

- Record each candidate: `scout.py decide <id> accepted|rejected --pattern "<family>"`; after building, `decide <id> built --script <name>`.
- Next scan: a built script with 0 uses since is a miss (fix the pointer or delete it); a pattern whose uses didn't drop means the pointer is too weak.
- Re-run after <period or number of sessions>.

## Out of Scope

What these scripts don't do.

## Further Notes

Anything else.
```
