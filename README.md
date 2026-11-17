# script-scout

A Claude Code skill that reads your own session logs, finds the work you and Claude repeat most and what it costs in tokens, and proposes scripts to replace it. It writes the result as a full spec you can build from. Each run is saved, so the next run can tell whether the scripts you built are used and whether the pattern went away.

```
/script-scout            # this repository's sessions
/script-scout user       # every project
/script-scout repo --since 2026-10-01
```

## What it does

1. **Scan.** `scout.py` reads `projects/**/*.jsonl` in `$CLAUDE_CONFIG_DIR` and `~/.claude` and prints:
   - tool cost (input and output tokens)
   - Bash command families, with `cd`, env prefixes and `timeout` stripped
   - heredoc scripts Claude wrote, by the files they touch
   - the hottest files and their size
   - commands that always run together
   - skills and slash commands used
   - repeated requests
2. **Learn.** It compares this run with earlier scans and decisions. A script you built that is never used is reported as a miss.
3. **Measure, check, design.** For each costly pattern, Claude checks the cheaper fixes first: a flag, an existing script, a native Claude Code feature, an installed skill. It designs a new script only when none of those cover the pattern.
4. **Present, then spec.** You pick which candidates to keep. Claude writes a full spec covering evidence, commands, token budget, tests, rollout order and the learning loop, using the bundled template. No other skill is needed.
5. **Record.** Your keep or drop decisions go to `.claude/script-scout/history.jsonl` (repo scope) or `~/.claude/script-scout/history.jsonl` (user scope).

## Install

Personal (every project):

```bash
git clone https://github.com/7kim/script-scout
ln -s "$PWD/script-scout/skills/script-scout" ~/.claude/skills/script-scout
```

One repository only: copy `skills/script-scout` into that repo's `.claude/skills/`.

With the `skills` CLI: `npx skills add 7kim/script-scout -a claude-code` (add `-g` for every project). Tested with skills 1.7.4 and `--copy`: it copies the skill into `.claude/skills/script-scout/` and writes a `skills-lock.json` beside it.

The skill is user-invoked (`disable-model-invocation: true`), so it adds nothing to your context until you type `/script-scout`.

## Run the scanner on its own

```bash
python3 skills/script-scout/scout.py scan --scope repo --top 10
python3 skills/script-scout/scout.py history
```

## Privacy

Everything stays on your machine. The report never prints prompt text beyond the first 40 characters of requests you repeated (digits masked), and any long token-like string is shown as `<redacted>`. Paths inside the repo are shown relative to it. The history file holds only counts and your decisions. Commit it if you want the learning shared with your team, or add it to `.gitignore`.

## Requirements

Python 3 and Claude Code. No dependencies. Tests run on the newest stable Python that [uv](https://docs.astral.sh/uv/) offers: `./test.sh` here, and on every push in GitHub Actions.

## Test

```bash
python3 skills/script-scout/test_scout.py
```

## Licence

MIT, see [LICENSE](LICENSE).
