---
name: script-scout
description: Mine this repo's (or all your) Claude Code session logs for repeated, token-heavy work, propose scripts that replace it, and write a full spec for them. Learns from earlier runs.
argument-hint: "[repo|user] [--since YYYY-MM-DD]"
disable-model-invocation: true
---

# Script scout

You turn the user's own Claude Code history into **evidence**, and the evidence into scripts that make repeated work cheaper. Every claim you make cites a number from the scan or a measurement. The deliverable is a spec the user can build from. Writing the scripts themselves is a later step.

Scope is `$ARGUMENTS`: `repo` (default) covers sessions run in this repository; `user` covers every project. Pass `--since` through when given.

## Steps

### 1. Scan

Run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scout.py scan --scope <scope> [--since <date>] --save
```

The report prints tool costs, Bash command families, inline scripts (heredocs Claude wrote, which cost **output** tokens), hot files with their current size, repeated three-command sequences, skills and slash commands used, repeated requests, and **HISTORY** from earlier runs.

Done when the report printed and its first line names the scope and session count. If it found no tool calls, tell the user which homes were searched and stop.

### 2. Read the history

If HISTORY lists decisions:

- A `built` script used 0× since: it missed. Find out why (wrong name, the agent never learned it exists, a native feature does it better) and make fixing or deleting it a candidate.
- A `built` script whose pattern still has high uses: the pointer that should send the agent to it is too weak. Make sharpening it a candidate (a CLAUDE.md line, a skill).
- A `rejected` candidate: leave it out unless its pattern's uses per session at least doubled since.

Done when every decision line has a verdict: working, missed, or dropped.

### 3. Measure

For the top patterns, get the cost of **one** use:

- Logged: `avg in` per command family is already one use.
- Live, for a read-only command whose output varies (a test run, a build): run it once as `<command> 2>&1 | wc -lc`. Run only commands that change nothing: no deploys, pushes, writes or anything that touches real hardware or services.

Done when each pattern you will rank has uses, tokens per use, and whether those tokens are input (tool results) or output (Claude-written heredocs, edits).

### 4. Check what exists, then climb the ladder

For each pattern, stop at the first rung that removes it:

1. **A flag** on the tool already used (`cargo test -q`, `--quiet`, `--porcelain`, `| tail -n 20`).
2. **A script the repo already has** (`package.json` scripts, `Makefile`, `scripts/`, `justfile`): the finding is the missing pointer, not a new script.
3. **A native Claude Code feature**: the LSP tool for code navigation in hot files, a hook for something that must happen every time, a status line for something glanced at often.
4. **An installed skill or plugin** that covers it.
5. **A new script.**

Done when every candidate names its rung, and every rung-5 candidate says why rungs 1–4 don't cover it.

### 5. Design the scripts

Follow **Design rules** below. For each script: its name, where it lives, every command with what it prints, what it reads and writes, which pattern it replaces, how it works, its failure output, its test seam, and how it's invoked.

Score each candidate as `uses per month × tokens saved per use`, counting output tokens 5× (they cost more and are slower). Rank by score.

Done when each candidate has a score and every command has a printed-output example.

### 6. Present

Show the user, in this order:

1. The evidence: one table, at most 8 rows (pattern, uses, tokens per use, total, source line from the scan).
2. History verdicts from step 2, if any.
3. Up to 5 ranked candidates: name, rung, commands, estimated monthly savings.

Ask which to keep. Done when the user has said keep or drop for each candidate.

### 7. Write the spec

Read [spec-template.md](spec-template.md) and fill every section for the kept candidates. Save it where the repo keeps specs (look for `docs/*/spec/`, `docs/specs/`, `specs/`, or a path CLAUDE.md names). Otherwise save it as `docs/script-scout/SPEC-scripts-<YYYY-MM-DD>.md`. With `user` scope, save it to `~/.claude/script-scout/`.

Done when every template section is filled or marked "none" with a reason, and every number in it traces to the scan or a measurement.

### 8. Record

For each candidate, record the user's call so the next run can learn from it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scout.py decide <id> accepted|rejected --pattern "<family as scan printed it>" [--note "<why>"]
```

When a script gets built later, run `decide <id> built --script <command name>` so the next scan counts its uses. If the repo has an issue tracker, offer to file each accepted script as a ticket.

Done when `scout.py history` lists every candidate from step 6.

## Design rules

- **One script per domain, with subcommands** (`tickets next|left|show`), not one script per question. Stdlib or the repo's own language; no new dependencies.
- **Read the least**: headers, one section, or `--format` fields, never whole files when a line answers.
- **Print the least**: one line per item, a one-line pass, and on failure only what failed and why. Budget every command: say how many lines it prints at most.
- **Writes are atomic and validated**: write to a temporary file and rename it. Refuse names with path separators or `..`. A failed run writes nothing.
- **Errors name their stage**: `tickets use: no docs/v9 folder`.
- **Secrets stay out**: no printed environment values, tokens or prompt text.
- **Invocation that costs nothing until used**: a plain CLI on PATH that the agent runs through Bash. For the user, a skill with `disable-model-invocation: true` per command, whose body runs `` !`<script> <command> $ARGUMENTS` ``, so the output arrives with no tool call and no standing context cost. Avoid MCP tools for this: their definitions load into every session.
- **Bundle sequences**: three commands always run together become one command (`cargo-gate` for fmt → check → test).
- **Point to it**: each script gets one line where the agent will look (CLAUDE.md or a skill), worded with the trigger the user actually types. Without the pointer the script never gets used.
- **One test seam**: run the script as a subprocess on a temporary fixture and check what it prints and writes.
