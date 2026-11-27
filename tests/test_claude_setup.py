"""Guards for the Claude Code setup (CLAUDE.md, .claude/settings.json, the per-turn card).

Hooks fail silently: a wrong path or a deleted script just means the rules stop being
injected, and nobody notices. These checks make that failure loud. The two budgets only
ever go down: to add a rule, remove one first (see "一条新规则该放哪" in CLAUDE.md).
"""

import datetime
import json
import re
import subprocess

from conftest import ROOT

CLAUDE_MD_MAX_LINES = 95
PROJECT_CARD_MAX_CHARS = 360

SETTINGS = ROOT / ".claude" / "settings.json"


def _hook_commands():
    hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    for entries in hooks.values():
        for entry in entries:
            for hook in entry["hooks"]:
                yield hook["command"]


def test_every_hook_points_at_an_existing_script():
    commands = list(_hook_commands())
    assert commands, "no hooks configured"
    for command in commands:
        # The bare form collapses to /.claude/... when the variable is missing.
        assert "${CLAUDE_PROJECT_DIR:-.}/" in command, command
        script = re.search(r'\$\{CLAUDE_PROJECT_DIR:-\.\}/([^"]+)', command).group(1)
        assert (ROOT / script).is_file(), f"hook script missing: {script}"


def test_plain_language_rule_card_is_injected():
    out = subprocess.run(
        ["bash", ".claude/skills/i-dont-read-code/scripts/inject-rules.sh"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "PLAIN-ENGLISH MODE" in out


def test_project_card_is_injected_and_within_budget():
    out = subprocess.run(
        ["sh", ".claude/project-card.sh"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "江山图鉴 每轮规矩" in out
    assert len(out) <= PROJECT_CARD_MAX_CHARS, (
        f"per-turn card is {len(out)} chars (budget {PROJECT_CARD_MAX_CHARS}); remove a rule first"
    )


def test_stale_handoffs_are_surfaced_under_the_chinese_heading(tmp_path):
    asked = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    (tmp_path / ".git").mkdir()
    (tmp_path / "STATUS.md").write_text(
        f"# 我们到哪了\n\n## 等你做的\n\n- `{asked}` 跑本地采集工具\n\n## 最近的变化\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        ["bash", str(ROOT / ".claude/skills/i-dont-read-code/scripts/session-start.sh")],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout
    assert "ATTENTION" in out and "跑本地采集工具" in out


def test_status_md_fits_the_session_start_window():
    # session-start.sh shows only the first 6000 bytes; past that, the decisions at the
    # bottom are silently cut. Chinese is 3 bytes a character, so this is ~2000 characters.
    size = len((ROOT / "STATUS.md").read_bytes())
    assert size <= 6000, f"STATUS.md is {size} bytes; trim 最近的变化 or archive old lines"


def test_claude_md_within_line_budget():
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").count("\n")
    assert lines <= CLAUDE_MD_MAX_LINES, (
        f"CLAUDE.md is {lines} lines (budget {CLAUDE_MD_MAX_LINES}); move prose to docs/"
    )
