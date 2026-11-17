#!/usr/bin/env python3
"""script-scout: find repeated, costly work in Claude Code session logs.

  scout.py scan    [--scope repo|user] [--root DIR] [--since YYYY-MM-DD] [--top N] [--save]
  scout.py decide  ID accepted|rejected|built [--pattern FAMILY] [--script NAME] [--note TEXT]
  scout.py history

Common flags: --scope, --root, --home DIR (repeatable; default $CLAUDE_CONFIG_DIR and ~/.claude).
Stdlib only. Reads session logs; writes only the history file (--save, decide).
Tokens are estimated as bytes / 4.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

SECRET = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")
PATH = re.compile(r"(?:~|\.{0,2}/)?[\w.@-]+(?:/[\w.*@-]+)+|\b[\w-]+\.(?:rs|py|ts|tsx|js|jsx|go|rb|java|kt|swift|c|cc|cpp|h|md|json|toml|ya?ml|tsv|csv|sh|sql|html|css)\b")
WRAPPERS = {"timeout", "env", "sudo", "nice", "time", "command", "exec", "xargs", "nohup"}
SKIP = re.compile(r"^(cd|pushd|popd|export|set|unset|source|\.|true|false|done|fi|esac|\}|\{|then|else|for|while|if|case)\b|^\w+=\S*$")
INLINE = {"python", "python3", "node", "bash", "sh", "ruby", "perl", "cat", "tee"}


IMAGE_BYTES = 1600 * 4  # an image costs about 1,600 tokens however large its base64 is


def tok(nbytes):
    return nbytes // 4


def result_bytes(cc):
    if isinstance(cc, str):
        return len(cc)
    if isinstance(cc, list):
        return sum(IMAGE_BYTES if isinstance(b, dict) and b.get("type") == "image" else result_bytes(b.get("text", "") if isinstance(b, dict) else b) for b in cc)
    return len(json.dumps(cc))


def real_file(p, root):
    """A path worth reporting: an existing file, or a missing one that has an extension. Never a folder or /dev."""
    p = os.path.normpath(os.path.expanduser(p.strip("'\"`,;:()")))
    if p.startswith("/dev/") or p in (".", "..") or "*" in p:
        return None
    full = p if os.path.isabs(p) or not root else os.path.join(root, p)
    if os.path.isdir(full):
        return None
    if not os.path.isfile(full) and not os.path.splitext(p)[1]:
        return None
    return full if os.path.isabs(full) else os.path.abspath(full)


def redact(s):
    return SECRET.sub("<redacted>", s)


def homes(extra):
    cands = extra or [os.environ.get("CLAUDE_CONFIG_DIR"), os.path.expanduser("~/.claude")]
    out, seen = [], set()
    for h in cands:
        if h and os.path.isdir(os.path.join(h, "projects")) and os.path.realpath(h) not in seen:
            seen.add(os.path.realpath(h))
            out.append(h)
    return out


def repo_root(root):
    if root:
        return os.path.realpath(root)
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.realpath(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(os.getcwd())


def state_file(args):
    if args.scope == "repo":
        return os.path.join(repo_root(args.root), ".claude", "script-scout", "history.jsonl")
    hs = homes(args.home)
    base = hs[0] if hs else os.path.expanduser("~/.claude")
    return os.path.join(base, "script-scout", "history.jsonl")


def log_files(hs):
    seen, out = set(), []
    for h in hs:
        for f in glob.glob(os.path.join(h, "projects", "**", "*.jsonl"), recursive=True):
            key = (os.path.basename(f), os.path.getsize(f))
            if os.path.realpath(f) in seen or key in seen:
                continue
            seen.update({os.path.realpath(f), key})
            out.append(f)
    return sorted(out)


def family(cmd):
    """The command a Bash call is really about: `cd x && FOO=1 timeout 60 cargo test -q` -> `cargo test`."""
    for seg in re.split(r"\s*(?:&&|\|\||;|\n|\|)\s*", cmd.strip()):
        seg = re.sub(r"^(do|then|else)\s+", "", seg)
        seg = re.sub(r"^(\w+=\S*\s+)+", "", seg)
        if not seg or SKIP.match(seg) or seg.startswith("#"):
            continue
        toks = seg.split()
        while toks and (toks[0] in WRAPPERS or re.fullmatch(r"-\S+|\d+[smh]?", toks[0])):
            toks = toks[1:]
        if not toks:
            continue
        prog = os.path.basename(toks[0].strip("'\"()"))
        if not prog:
            continue
        rest = toks[1:]
        sub = ""
        if rest:
            a = rest[0]
            if re.fullmatch(r"[a-z][\w-]*", a) or re.fullmatch(r"-\w*", a):
                sub = a
        return f"{prog} {sub}".strip()
    return "(shell)"


def path_group(p, root):
    """Group a path by folder and extension, digits folded: docs/v7.7/x/12-a.md -> docs/vN.N/x/*.md"""
    p = p.strip("'\"`,;:()")
    if root and os.path.isabs(p) and (p == root or p.startswith(root + os.sep)):
        p = os.path.relpath(p, root)
    p = p.replace(os.path.expanduser("~"), "~")
    d, b = os.path.split(p)
    ext = os.path.splitext(b)[1]
    g = (re.sub(r"\d+", "N", d) + "/" if d else "") + ("*" + ext if ext else b)
    return redact(g)


def short_path(p, root):
    p = p.strip("'\"`,;:()")
    if root and os.path.isabs(p) and p.startswith(root + os.sep):
        return os.path.relpath(p, root)
    return p.replace(os.path.expanduser("~"), "~")


def entries(f):
    with open(f, errors="ignore") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def scan_logs(args):
    root = repo_root(args.root) if args.scope == "repo" else None
    since = args.since or ""
    calls = []          # dicts: session, ts, tool, family, in_b, out_b, paths, inline
    requests = collections.Counter()
    commands = collections.Counter()  # /slash-command uses
    sessions, first, last = set(), None, None
    usage = collections.defaultdict(dict)  # session -> message id -> (ts, usage); a message is logged once per content block
    titles = {}
    for f in log_files(homes(args.home)):
        decided = None
        pending = {}
        sub = os.sep + "subagents" + os.sep in f
        for e in entries(f):
            cwd = e.get("cwd")
            if decided is None and cwd:
                decided = root is None or cwd == root or cwd.startswith(root + os.sep)
            if decided is False:
                break
            ts = e.get("timestamp") or ""
            if since and ts and ts < since:
                continue
            m = e.get("message") or {}
            c = m.get("content")
            sid = e.get("sessionId") or f
            if e.get("type") == "custom-title" and e.get("customTitle"):
                titles[sid] = e["customTitle"]  # the last rename wins
            u = m.get("usage") if isinstance(m, dict) else None
            if e.get("type") == "assistant" and isinstance(u, dict) and m.get("id") and not sub:
                usage[sid].setdefault(m["id"], (ts, u))
            if e.get("type") == "user" and not e.get("isMeta") and not sub:
                texts = [c] if isinstance(c, str) else [b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text"]
                for t in texts:
                    for name in re.findall(r"<command-name>/?([\w:.-]+)</command-name>", t):
                        commands[name] += 1
                    if t and not t.lstrip().startswith(("<", "[")):
                        requests[re.sub(r"\d+", "N", redact(t.strip().lower()))[:40]] += 1
            if not isinstance(c, list):
                continue
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    sessions.add(sid)
                    first = min(first or ts, ts) if ts else first
                    last = max(last or ts, ts) if ts else last
                    inp = b.get("input") or {}
                    tool = b.get("name", "?")
                    rec = {"session": sid, "ts": ts, "tool": tool, "family": tool, "in_b": 0,
                           "out_b": len(json.dumps(inp)), "paths": [], "inline": False, "skill": None}
                    if tool == "Bash":
                        cmd = inp.get("command", "")
                        rec["family"] = family(cmd)
                        prog = rec["family"].split()[0]
                        rec["inline"] = "<<" in cmd and prog in INLINE or bool(re.search(r"\b(python3?|node)\s+-[ce]?\s", cmd))
                        rec["paths"] = [x for x in (real_file(q, root) for q in PATH.findall(cmd)) if x]
                    elif tool == "Skill":
                        rec["skill"] = inp.get("skill")
                    else:
                        fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                        if isinstance(fp, str) and real_file(fp, root):
                            rec["paths"] = [real_file(fp, root)]
                    pending[b.get("id")] = rec
                    calls.append(rec)
                elif b.get("type") == "tool_result":
                    rec = pending.get(b.get("tool_use_id"))
                    if rec is not None:
                        cc = b.get("content")
                        rec["in_b"] += result_bytes(cc)
    return root, calls, requests, commands, sessions, first, last, usage, titles


WIDTH = 120  # no output line is longer: long paths and names are cut, never wrapped


def say(text):
    for line in str(text).split("\n"):
        print(line if len(line) <= WIDTH else line[:WIDTH - 1] + "…")


def table(title, rows, header):
    if not rows:
        return
    say(f"\n{title}")
    say("  " + header)
    for r in rows:
        say("  " + r)


def cmd_scan(args):
    root, calls, requests, commands, sessions, first, last, usage, titles = scan_logs(args)
    top = args.top
    where = f"repo {root}" if root else "all projects"
    if not calls:
        say(f"script-scout · {where} · no tool calls found in the logs (homes: {', '.join(homes(args.home)) or 'none'})")
        return {}
    n_s = max(len(sessions), 1)
    say(f"script-scout · {where} · {len(sessions)} sessions · {first[:10]}..{last[:10]} · {len(calls)} tool calls")
    say("tokens ≈ bytes/4 · in = what tools returned · out = what Claude wrote into the call")

    by_tool = collections.defaultdict(lambda: [0, 0, 0])
    for r in calls:
        t = by_tool[r["tool"]]
        t[0] += 1; t[1] += r["in_b"]; t[2] += r["out_b"]
    rows = sorted(by_tool.items(), key=lambda kv: -(kv[1][1] + kv[1][2]))[:top]
    table("TOOLS (by tokens)", [f"{k[:34]:34} {v[0]:6} {tok(v[1]):>9,} {tok(v[2]):>9,}" for k, v in rows],
          f"{'tool':34} {'calls':>6} {'in≈tok':>9} {'out≈tok':>9}")

    fam = collections.defaultdict(lambda: [0, 0, 0])
    for r in calls:
        if r["tool"] == "Bash":
            t = fam[r["family"]]
            t[0] += 1; t[1] += r["in_b"]; t[2] += r["out_b"]
    rows = sorted(fam.items(), key=lambda kv: -kv[1][0])[:top]
    table("COMMANDS (Bash, by uses)", [f"{redact(k)[:26]:26} {v[0]:6} {tok(v[1] // v[0]):>8,} {tok(v[1]):>9,} {tok(v[2]):>9,}" for k, v in rows],
          f"{'command':26} {'uses':>6} {'avg in':>8} {'in≈tok':>9} {'out≈tok':>9}")

    inl = collections.defaultdict(lambda: [0, 0])
    for r in calls:
        if r["inline"]:
            groups = collections.Counter(path_group(p, root) for p in r["paths"])
            target = groups.most_common(1)[0][0] if groups else "(no path)"
            inl[(r["family"], target)][0] += 1
            inl[(r["family"], target)][1] += r["out_b"]
    rows = sorted(inl.items(), key=lambda kv: -kv[1][1])[:top]
    table("INLINE SCRIPTS (heredocs and -c/-e; Claude writes these as output tokens)",
          [f"{k[0][:12]:12} {k[1][:44]:44} {v[0]:5} {tok(v[1]):>9,}" for k, v in rows],
          f"{'runner':12} {'mostly touches':44} {'uses':>5} {'out≈tok':>9}")

    hot = collections.defaultdict(lambda: [0, 0])
    for r in calls:
        if r["tool"] in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep") or r["family"].split()[0] in ("sed", "grep", "rg", "cat", "head", "tail", "awk"):
            for p in set(r["paths"]):
                hot[p][0] += 1
                hot[p][1] += r["in_b"] // max(len(set(r["paths"])), 1)
    rows = []
    for p, v in sorted(hot.items(), key=lambda kv: -kv[1][0])[:top]:
        try:
            with open(p, errors="ignore") as fh:
                lines = str(sum(1 for _ in fh))
        except OSError:
            lines = "-"
        rows.append(f"{redact(short_path(p, root))[:48]:48} {v[0]:6} {lines:>7} {tok(v[1]):>9,}")
    table("HOT FILES (read, searched or edited most)", rows, f"{'file':48} {'uses':>6} {'lines':>7} {'in≈tok':>9}")

    seq = collections.Counter()
    by_session = collections.defaultdict(list)
    for r in calls:
        if r["tool"] == "Bash":
            by_session[r["session"]].append(r["family"])
    for fams in by_session.values():
        fams = [x for i, x in enumerate(fams) if i == 0 or fams[i - 1] != x]  # a run of one command counts once
        for i in range(len(fams) - 2):
            g = tuple(fams[i:i + 3])
            if len(set(g)) > 1:
                seq[g] += 1
    rows = [f"{c:5}  {' → '.join(redact(x) for x in g)}"[:100] for g, c in seq.most_common(top) if c >= 3 and len(set(g)) == 3]
    table("SEQUENCES (three commands in a row, 3+ times: bundle candidates)", rows, f"{'times':>5}  commands")

    sk = collections.Counter(r["skill"] for r in calls if r["skill"]) + commands
    table("SKILLS AND SLASH COMMANDS USED", [f"{k[:40]:40} {v:5}" for k, v in sk.most_common(top)], f"{'name':40} {'uses':>5}")

    rq = [(k, v) for k, v in requests.most_common(top) if v >= 2]
    table("REPEATED REQUESTS (first 40 chars, digits masked)", [f"{v:5}  {k}" for k, v in rq], f"{'times':>5}  request")

    sess = []
    for sid, msgs in usage.items():
        n = lambda u, k: u.get(k) or 0  # a usage field may be missing or null
        ctx = [(ts, n(u, "input_tokens") + n(u, "cache_creation_input_tokens") + n(u, "cache_read_input_tokens"))
               for ts, u in sorted(msgs.values(), key=lambda x: x[0])]
        sess.append((titles.get(sid) or sid[:8], len(msgs), ctx[0][1], max(c for _, c in ctx),
                     sum(n(u, "output_tokens") for _, u in msgs.values()),
                     sum(n(u, "cache_read_input_tokens") for _, u in msgs.values())))
    table("SESSIONS (by peak context)",
          [f"{redact(t)[:40]:40}  {n:>5} {a:>9,} {b:>9,} {o:>8,} {c:>12,}" for t, n, a, b, o, c in sorted(sess, key=lambda r: -r[3])[:top]],
          f"{'session (title or id)':40}  {'calls':>5} {'start':>9} {'peak':>9} {'output':>8} {'cached read':>12}")

    print_history(args, calls, commands, fam, n_s)

    snap = {"kind": "scan", "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "scope": args.scope, "root": root, "since": args.since, "sessions": len(sessions),
            "families": {k: [v[0], tok(v[1])] for k, v in sorted(fam.items(), key=lambda kv: -kv[1][0])[:40]}}
    if args.save:
        append(state_file(args), snap)
        say(f"\nsaved this scan to {state_file(args)}")
    return snap


def read_history(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def append(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def print_history(args, calls, commands, fam, n_sessions):
    hist = read_history(state_file(args))
    if not hist:
        say("\nHISTORY: none yet (scan --save and decide write it)")
        return
    scans = [h for h in hist if h.get("kind") == "scan"]
    decisions = [h for h in hist if h.get("kind") == "decision"]
    say(f"\nHISTORY ({state_file(args)})")
    if scans:
        prev = scans[-1]
        ps = max(prev.get("sessions") or 1, 1)
        say(f"  last scan {prev['ts'][:10]}: uses per session, then → now (top changes)")
        changes = []
        for k, (n, _) in prev.get("families", {}).items():
            now = fam.get(k, [0])[0] / n_sessions
            was = n / ps
            if was and abs(now - was) / was >= 0.25:
                changes.append((abs(now - was), f"  {k[:26]:26} {was:6.1f} → {now:5.1f}"))
        for _, line in sorted(changes, reverse=True)[:8]:
            say(line)
    for d in decisions:
        line = f"  {d['ts'][:10]} {d['id']}: {d['decision']}"
        if d.get("script"):
            name = d["script"]
            uses = sum(1 for r in calls if r["ts"] >= d["ts"] and (r["family"].split()[0] == name or name in r["family"]))
            uses += commands.get(name, 0)
            line += f" · {name} used {uses}× since"
        if d.get("pattern"):
            line += f" · pattern '{d['pattern']}' now {fam.get(d['pattern'], [0])[0]} uses"
        if d.get("note"):
            line += f" · {d['note'][:60]}"
        say(line)


def cmd_decide(args):
    if not re.fullmatch(r"[\w.-]{1,60}", args.id):
        sys.exit("decide: the id may use letters, digits, '.', '_' and '-' only")
    rec = {"kind": "decision", "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "id": args.id, "decision": args.decision, "script": args.script, "pattern": args.pattern, "note": args.note}
    append(state_file(args), rec)
    say(f"recorded {args.id}: {args.decision} in {state_file(args)}")


def cmd_history(args):
    hist = read_history(state_file(args))
    if not hist:
        say(f"no history at {state_file(args)}")
    for h in hist:
        if h.get("kind") == "scan":
            say(f"{h['ts'][:10]} scan · {h.get('sessions')} sessions · top: {', '.join(list(h.get('families', {}))[:5])}")
        else:
            say(f"{h['ts'][:10]} {h['id']}: {h['decision']}" + (f" ({h['script']})" if h.get("script") else ""))


def main(argv=None):
    p = argparse.ArgumentParser(prog="scout.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--scope", choices=["repo", "user"], default="repo")
    common.add_argument("--root", help="repo root (default: git top level, else the current folder)")
    common.add_argument("--home", action="append", help="Claude Code config home holding projects/ (repeatable)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", parents=[common])
    s.add_argument("--since", help="YYYY-MM-DD")
    s.add_argument("--top", type=int, default=10, help="rows per table (default 10)")
    s.add_argument("--save", action="store_true", help="append this scan to the history file")
    d = sub.add_parser("decide", parents=[common])
    d.add_argument("id")
    d.add_argument("decision", choices=["accepted", "rejected", "built"])
    d.add_argument("--script", help="the command name the built script is run by")
    d.add_argument("--pattern", help="the command family it replaces, as scan prints it")
    d.add_argument("--note")
    sub.add_parser("history", parents=[common])
    args = p.parse_args(argv)
    if getattr(args, "since", None) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        sys.exit("scan: --since must be YYYY-MM-DD")
    {"scan": cmd_scan, "decide": cmd_decide, "history": cmd_history}[args.cmd](args)


if __name__ == "__main__":
    main()
