#!/usr/bin/env python3
"""PostToolUse hook: the first time a session opens a project file, show where that file came from.

A new session does not know why things are the way they are. The reasons exist, in commit messages and in
docs/DECISIONS.md, but nobody goes looking for them at the moment it matters (a session wrote "the reason for
rolling back 3D was not recorded" while the reason sat in that very commit's message). So the reasons are put
in front of Claude when it first reads or edits a file: the latest commits that touched it, and the decisions
that name it. Once per file per session, so the cost stays a few lines.

Never blocks anything: every problem exits 0 silently.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

COMMITS = 5
DECISIONS = "docs/DECISIONS.md"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = (data.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".").resolve()
    try:
        rel = Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return 0

    seen_file = Path(tempfile.gettempdir()) / f"china-gmap-history-{data.get('session_id', 'x')}.txt"
    seen = set(seen_file.read_text(encoding="utf-8").splitlines()) if seen_file.exists() else set()
    if rel in seen:
        return 0
    with seen_file.open("a", encoding="utf-8") as f:
        f.write(rel + "\n")

    log = subprocess.run(["git", "log", f"-{COMMITS}", "--date=short", "--format=%ad %h %s", "--", rel],
                         cwd=root, capture_output=True, text=True).stdout.strip()
    related = []
    dec = root / DECISIONS
    if dec.exists():
        title = None
        for line in dec.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                title = line[4:].strip()
            elif title and rel in line and title not in related:
                related.append(title)
    if not log and not related:
        return 0

    parts = [f"【{rel} 的来历】改它之前先弄清以前为什么这样："]
    if log:
        parts.append("最近的修改（新的在上；要看原因，读那次提交的完整说明 git show <编号>）：\n" + log)
    if related:
        parts.append(f"{DECISIONS} 里和它有关的决定：\n" + "\n".join(f"- {t}" for t in related[:8]))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": "\n".join(parts)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
