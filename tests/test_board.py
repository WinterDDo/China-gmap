"""tools/board.py on a throwaway remote: main, two other sessions' branches, and this session's branch."""

import os
import subprocess
import sys

from conftest import ROOT

BOARD = ROOT / "tools" / "board.py"
OLD = "2026-01-01T12:00:00+00:00"


def run(cwd, *args, date=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if date:
        env |= {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def commit(repo, path, text, subject, date=None):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    run(repo, "git", "add", path)
    run(repo, "git", "commit", "-q", "-m", subject, date=date)


def test_board_names_overlaps_orphans_and_the_next_version(tmp_path):
    origin, seed, me = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "me"
    run(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    run(tmp_path, "git", "clone", "-q", str(origin), str(seed))
    commit(seed, "STATUS.md", "start\n", "Design freeze 5.7: start", date=OLD)
    run(seed, "git", "push", "-q", "origin", "main")

    run(seed, "git", "checkout", "-q", "-b", "claude/other")  # another session, active now, on a hot file
    commit(seed, "explorations/design-freeze/index.html", "theirs\n", "Design freeze 5.9: their trial")
    run(seed, "git", "push", "-q", "origin", "claude/other")
    run(seed, "git", "checkout", "-q", "main")
    run(seed, "git", "checkout", "-q", "-b", "claude/forgotten")  # old work never merged
    commit(seed, "pipeline/fix.py", "fix\n", "A fix nobody merged", date=OLD)
    run(seed, "git", "push", "-q", "origin", "claude/forgotten")

    run(tmp_path, "git", "clone", "-q", str(origin), str(me))
    run(me, "git", "checkout", "-q", "-b", "claude/me")
    commit(me, "explorations/design-freeze/index.html", "mine\n", "My change")

    out = run(me, sys.executable, str(BOARD))
    assert "主线：origin/main" in out
    assert "claude/me 还没推到远端" in out
    assert "你也改了：explorations/design-freeze/index.html" in out
    assert "热点文件" in out
    assert "两天以上没并进主线" in out  # claude/forgotten
    assert "新一版用 5.10" in out

    run(me, "git", "push", "-q", "-u", "origin", "claude/me")  # pushing is the claim
    assert "claude/me（本会话）" in run(me, sys.executable, str(BOARD))

    run(seed, "git", "checkout", "-q", "main")  # main moves on: the board says so
    commit(seed, "README.md", "x\n", "Something on main")
    run(seed, "git", "push", "-q", "origin", "main")
    assert "主线上有 1 个提交你还没合并进来" in run(me, sys.executable, str(BOARD))


def test_board_never_fails_outside_a_repository(tmp_path):
    done = subprocess.run([sys.executable, str(BOARD), "--no-fetch"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0 and "看板没能运行" in done.stdout
