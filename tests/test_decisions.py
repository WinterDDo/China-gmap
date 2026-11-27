"""docs/DECISIONS.md stays usable: every entry has its fields, names real files, and merges by union."""

import re

from conftest import ROOT

DECISIONS = ROOT / "docs" / "DECISIONS.md"
FIELDS = ("- 决定：", "- 为什么：", "- 放弃了：", "- 谁定的：", "- 出处：", "- 相关文件：")
WHO = ("用户", "评审", "Claude", "待核实")


def entries():
    text = DECISIONS.read_text(encoding="utf-8")
    return re.findall(r"^### (.+?)\n(.*?)(?=^### |^## |\Z)", text, re.S | re.M)


def test_decision_log_merges_by_union():
    # Several sessions append at once; union keeps both sides' entries instead of a conflict.
    assert "docs/DECISIONS.md merge=union" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_every_decision_has_its_fields_and_real_files():
    found = entries()
    assert len(found) >= 10
    for title, body in found:
        assert re.match(r"\d{4}-\d{2}-\d{2} · ", title), f"entry title needs a date: {title}"
        for field in FIELDS:
            assert field in body, f"{title}: missing {field}"
        who = body.split("- 谁定的：", 1)[1].strip()
        assert who.startswith(WHO), f"{title}: 谁定的 must start with one of {WHO}"
        files = body.split("- 相关文件：", 1)[1].splitlines()[0]
        for path in re.split(r"[、，,\s]+", files.strip()):
            assert (ROOT / path).exists(), f"{title}: 相关文件 {path} does not exist"


def test_two_sessions_appending_merge_without_conflict(tmp_path):
    import os
    import subprocess

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, env=env, capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    (tmp_path / ".gitattributes").write_text((ROOT / ".gitattributes").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    log = tmp_path / "docs" / "DECISIONS.md"
    log.write_text("# 已做的决定\n\n## 设计\n\n### old\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    git("checkout", "-qb", "a"); log.write_text(log.read_text(encoding="utf-8") + "\n### from session A\n", encoding="utf-8")
    git("commit", "-qam", "a")
    git("checkout", "-q", "main"); log.write_text(log.read_text(encoding="utf-8") + "\n### from session B\n", encoding="utf-8")
    git("commit", "-qam", "b")
    merged = git("merge", "-q", "--no-edit", "a")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    text = log.read_text(encoding="utf-8")
    assert "from session A" in text and "from session B" in text and "<<<<<<<" not in text
