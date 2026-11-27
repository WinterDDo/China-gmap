#!/usr/bin/env python3
"""PreToolUse hook: run the test suite before any `git commit` or `git push` in this project; block if red.

CLAUDE.md used to say "run pytest before every commit". Written down, that was a promise;
this makes it a guard. Exit code 2 blocks the commit and shows stderr to Claude.

Push is guarded too because several sessions work on this project at once: after merging another session's
branch (a merge is not a `git commit`), two green branches can be red together. The push is where that
combined state would leave this machine, so the suite runs on it there.

Problems with the hook itself (unreadable input, a commit in some other checkout) exit 0:
a broken guard must not wedge the session. tests/test_claude_setup.py keeps it wired and
checks that it really blocks.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# `git commit` / `git push`, also with options before the subcommand (`git -C dir commit`, `git -c k=v push`).
COMMIT = re.compile(r"(?:^|[;&|(]|\s)git(?:\s+-[cC]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+(commit|push)(?![\w-])")
DIR_HINTS = re.compile(r"(?:\bgit\s+-C\s+|(?:^|[;&|(]\s*)cd\s+)(\"[^\"]+\"|'[^']+'|\S+)")
TAIL_LINES = 40


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    hit = COMMIT.search(command)
    if not hit:
        return 0
    what = "提交" if hit.group(1) == "commit" else "推送"

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    cwd = Path(data.get("cwd") or os.getcwd())
    # Only this project's commits: skip if the shell is elsewhere or the command points elsewhere.
    places = [cwd] + [cwd / Path(m.strip("'\"")).expanduser() for m in DIR_HINTS.findall(command)]
    if not all(inside(p, project) for p in places):
        return 0

    try:
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=project, capture_output=True, text=True, timeout=100,
        )
    except subprocess.TimeoutExpired:
        print(f"{what}被拦下：测试跑了 100 秒还没结束。先查清哪项测试卡住了。", file=sys.stderr)
        return 2

    if run.returncode in (0, 5):  # 5 = no tests collected
        return 0

    output = (run.stdout + run.stderr).strip().splitlines()
    if "No module named pytest" in run.stderr:
        hint = "这台机器没装测试工具。先运行 `uv sync` 或 `python3 -m pip install pytest numpy pillow`。"
    else:
        hint = ("测试没有全绿。先修好（或者确认是测试本身错了，再改测试）。不要跳过或删掉测试。"
                "刚合并过别的会话的分支的话，多半是两边各自绿、合起来红：两边的改动一起看。")
    print(f"{what}被拦下：{hint}\n\n" + "\n".join(output[-TAIL_LINES:]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
