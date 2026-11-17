"""Runs scout.py the way a user does, on fake session logs, and checks what it prints and saves.

    python3 -m unittest test_scout.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scout.py")
SECRET = "sk-ant-" + "a" * 40


def bash(i, cmd, out="ok\n", ts="2026-11-10T10:00:00Z"):
    use = {"type": "assistant", "cwd": ROOT, "sessionId": "s1", "timestamp": ts,
           "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}]}}
    res = {"type": "user", "cwd": ROOT, "sessionId": "s1", "timestamp": ts,
           "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}}
    return [use, res]


def ask(text, ts="2026-11-10T10:00:00Z", cwd=None):
    return [{"type": "user", "cwd": cwd or ROOT, "sessionId": "s1", "timestamp": ts, "message": {"content": text}}]


ROOT = ""


class Scout(unittest.TestCase):
    def setUp(self):
        global ROOT
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        ROOT = os.path.join(t, "repo")
        os.makedirs(os.path.join(ROOT, "src"))
        with open(os.path.join(ROOT, "src", "big.rs"), "w") as fh:
            fh.write("fn x() {}\n" * 500)
        self.home = os.path.join(t, "home")
        proj = os.path.join(self.home, "projects", "-repo")
        os.makedirs(proj)
        rows = []
        n = 0
        for cmd in [f"cd {ROOT} && cargo test --locked", "FOO=1 timeout 600 cargo test -q", "grep -n fn src/big.rs",
                    "sed -n 1,20p src/big.rs", "cargo test", "grep -n x src/big.rs", "sed -n 5p src/big.rs", "cargo test",
                    "grep -n y src/big.rs", "sed -n 9p src/big.rs", "cargo test",
                    f"python3 - <<'EOF'\nopen('src/big.rs').read()  # {SECRET}\nEOF"]:
            n += 1
            rows += bash(n, cmd, out="x" * 400)
        rows += ask("what is the next ticket 12") + ask("What is the next ticket 13") + ask(f"my key {SECRET}")
        with open(os.path.join(proj, "s1.jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        other = os.path.join(self.home, "projects", "-elsewhere")
        os.makedirs(other)
        with open(os.path.join(other, "s2.jsonl"), "w") as fh:
            row = bash(99, "make deploy")[0]
            row["cwd"] = os.path.join(t, "elsewhere")
            fh.write(json.dumps(row) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_scout(self, *args):
        r = subprocess.run([sys.executable, "-I", SCOUT, *args, "--home", self.home, "--root", ROOT],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_scan_groups_commands_and_hides_secrets(self):
        out = self.run_scout("scan")
        line = next(l for l in out.splitlines() if l.strip().startswith("cargo test"))
        self.assertEqual(line.split()[2], "5", out)          # wrappers, cd and env stripped
        self.assertIn("src/big.rs", out)                     # hot file, with its line count
        self.assertIn("500", out)
        self.assertIn("grep -n → sed -n → cargo test", out)  # a repeated sequence
        self.assertIn("what is the next ticket N", out)      # repeated request, digits masked
        self.assertNotIn(SECRET, out)
        self.assertNotIn("make deploy", out)                 # another repo's session is left out

    def test_no_line_is_longer_than_120_characters(self):
        long_root = os.path.join(self.tmp.name, "r" * 150)
        os.makedirs(long_root)
        proj = os.path.join(self.home, "projects", "-long")
        os.makedirs(proj)
        rows = []
        for i in range(3):
            use, res = bash(200 + i, "x" * 300 + f" {i}")
            use["cwd"] = res["cwd"] = long_root
            use["message"]["content"][0]["name"] = "mcp__" + "y" * 200
            rows += [use, res]
        rows += ask("z" * 300, cwd=long_root)
        with open(os.path.join(proj, "s3.jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
        r = subprocess.run([sys.executable, "-I", SCOUT, "scan", "--home", self.home, "--root", long_root],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("…", r.stdout)  # the summary line with the long path was cut
        self.assertEqual([l for l in r.stdout.splitlines() if len(l) > 120], [])

    def test_top_defaults_to_10(self):
        r = subprocess.run([sys.executable, "-I", SCOUT, "scan", "--help"], capture_output=True, text=True, timeout=60)
        self.assertIn("default 10", r.stdout)

    def test_user_scope_sees_every_project(self):
        self.assertIn("make deploy", self.run_scout("scan", "--scope", "user"))

    def test_since_filters_old_sessions(self):
        self.assertIn("no tool calls", self.run_scout("scan", "--since", "2026-12-01"))

    def test_history_tracks_a_built_script(self):
        self.run_scout("scan", "--save")
        self.run_scout("decide", "test-gate", "built", "--script", "gate", "--pattern", "cargo test")
        log = os.path.join(self.home, "projects", "-repo", "s1.jsonl")
        with open(log, "a") as fh:
            fh.write(json.dumps(bash(50, "gate", ts="2099-01-01T00:00:00Z")[0]) + "\n")
        out = self.run_scout("scan")
        self.assertIn("test-gate: built · gate used 1× since", out)
        self.assertIn("pattern 'cargo test' now 5 uses", out)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, ".claude", "script-scout", "history.jsonl")))

    def test_decide_refuses_an_unsafe_id(self):
        r = subprocess.run([sys.executable, "-I", SCOUT, "decide", "../x", "built", "--home", self.home, "--root", ROOT],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".claude")))


if __name__ == "__main__":
    unittest.main()
