#!/usr/bin/env python3
"""协作看板：别的 Claude 会话在改什么，从 git 推出来，不靠任何人登记。

    python3 tools/board.py              取最新的远端分支再看（开工时的钩子就这样跑）
    python3 tools/board.py --no-fetch   只看本地已有的

Why derive it from git: in the franchise project a hand-kept "who is working on what" table was touched by
81% of merges and 17 of its 18 rows were stale. Git already knows who touched what.

What it shows, against the integration branch (origin/main once it exists, else the remote's default branch):
- every claude/* branch pushed in the last few days, plus any older one never merged (work that would be lost);
- for each: merged or not, its last commit, and the files it changed since it left the integration branch;
- which of those files this session has changed too, and which are hot files (merge conflicts are likely);
- the highest design-freeze version anywhere, so two sessions do not both call their version 5.8.

"Merged" is ancestry, which only works because branches are joined with real merges, never squashed.
Best effort: it must never block a session, so every failure degrades to a short note and exit 0.
"""

from __future__ import annotations

import re
import signal
import subprocess
import sys
import time

DAYS = 3
HOT = {
    "explorations/design-freeze/index.html": "单文件原型，两个会话同时改几乎必冲突",
    "explorations/design-freeze/data/cities.json": "一整行的大文件，冲突无法手工合；用生成脚本重新生成",
    "STATUS.md": "人人都要更新；并进主线前最后再改",
    "CLAUDE.md": "规则本身",
    "pipeline/parse/bulletin.py": "公报解析，改动影响全部数字",
    "pipeline/check.py": "数据铁律和上限；上限冲突时取较小的那个",
}
VERSION = re.compile(r"Design (?:freeze |draft )?v?(\d+)\.(\d+)(?:\.(\d+))?", re.I)


def git(*args: str, timeout: float = 20) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout, check=True).stdout.strip()


def ok(*args: str) -> bool:
    return subprocess.run(["git", *args], capture_output=True).returncode == 0


def integration_branch() -> str | None:
    if ok("rev-parse", "--verify", "-q", "refs/remotes/origin/main"):
        return "origin/main"
    try:
        return git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    except Exception:
        try:  # origin/HEAD is not always set locally; ask the remote
            head = git("ls-remote", "--symref", "origin", "HEAD", timeout=15).splitlines()[0]
            return "origin/" + head.split()[1].removeprefix("refs/heads/")
        except Exception:
            return None


def changed_since(base: str, ref: str) -> list[str]:
    try:
        mb = git("merge-base", base, ref)
        return [f for f in git("diff", "--name-only", mb, ref).splitlines() if f]
    except Exception:
        return []


def main(argv: list[str]) -> int:
    if "--no-fetch" not in argv:
        try:
            git("fetch", "-q", "--prune", "origin", timeout=20)
        except Exception:
            print("（看板：取远端分支失败，下面是本地已有的信息，可能不是最新）")
    base = integration_branch()
    me = git("rev-parse", "--abbrev-ref", "HEAD")
    now = time.time()
    rows = []
    for line in git("for-each-ref", "refs/remotes/origin/claude/",
                    "--format=%(refname:short)\t%(committerdate:unix)\t%(subject)").splitlines():
        ref, when, subject = line.split("\t", 2)
        merged = bool(base) and ok("merge-base", "--is-ancestor", ref, base)
        carried = ok("merge-base", "--is-ancestor", ref, "HEAD")  # already joined into this session's branch
        age_days = (now - int(when)) / 86400
        if age_days > DAYS and merged:
            continue
        rows.append((ref, age_days, subject, merged, carried))

    mine = set(changed_since(base, "HEAD")) if base else set()
    mine |= {l[3:] for l in git("status", "--porcelain").splitlines() if len(l) > 3}

    print("━━━━ 协作看板（多个会话可能在同时改这个项目）━━━━")
    if base == "origin/main":
        print("主线：origin/main")
    else:
        print(f"⚠ 还没有 main 主线；新会话从默认分支 {base or '（未知）'} 起步，那只是某个会话的工作分支。见 docs/COLLABORATION.md。")
    behind = int(git("rev-list", "--count", f"HEAD..{base}")) if base else 0
    if behind:
        print(f"⚠ 主线上有 {behind} 个提交你还没合并进来：开工改东西之前、并进主线之前，先 git merge {base}。")
    if me.startswith("claude/") and not ok("rev-parse", "--verify", "-q", f"refs/remotes/origin/{me}"):
        print(f"⚠ 本会话的分支 {me} 还没推到远端：别的会话看不到你在改什么。先推一次，推了就算认领。")
    if not rows:
        print("最近没有别的会话推送过分支。")
    versions = []
    for ref, age, subject, merged, carried in sorted(rows, key=lambda r: r[1]):
        name = ref.removeprefix("origin/")
        tag = "（本会话）" if name == me else "（默认分支）" if ref == base else ""
        state = ("" if ref == base else "已并进主线" if merged
                 else "未并进主线，但已并进本会话" if carried and name != me else "未并进主线")
        when = f"{age * 24:.0f} 小时前" if age < 2 else f"{age:.0f} 天前"
        print(f"· {name}{tag}：{when}{'，' + state if state else ''}；最近一次「{subject[:60]}」")
        if name == me or merged or carried:
            continue
        files = changed_since(base, ref) if base else []
        both = sorted(set(files) & mine)
        hot = sorted(f for f in files if f in HOT)
        if both:
            print(f"    ⚠ 你也改了：{'、'.join(both)}。先把它并进来再继续改这些文件。")
        if hot:
            print(f"    热点文件：{'；'.join(f'{f}（{HOT[f]}）' for f in hot)}")
        if not merged and age > 2:
            print("    ⚠ 两天以上没并进主线：里面的修改可能会丢。先并进来，或问用户还要不要。")
    for ref in [base] + [r[0] for r in rows]:
        if not ref:
            continue
        try:
            for s in git("log", "--format=%s", "-200", ref).splitlines():
                m = VERSION.search(s)
                if m:
                    versions.append(tuple(int(x or 0) for x in m.groups()))
        except Exception:
            pass
    if versions:
        top = max(versions)
        print(f"设计定稿已用到的最高版本号：{top[0]}.{top[1]}" + (f".{top[2]}" if top[2] else "")
              + f"；新一版用 {top[0]}.{top[1] + 1}（撤回过的版本号也不再用）。")
    print("规矩：只改自己的分支；推一个分支就算认领；并进主线前先合并最新主线。全文见 docs/COLLABORATION.md。")
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # piped into head: stop quietly
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # never block a session
        print(f"（看板没能运行：{exc}。可手动运行 python3 tools/board.py）")
        sys.exit(0)
