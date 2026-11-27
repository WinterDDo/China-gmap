"""Guards for the Claude Code setup (CLAUDE.md, .claude/settings.json, the per-turn card).

Hooks fail silently: a wrong path or a deleted script just means the rules stop being
injected, and nobody notices. These checks make that failure loud. The two budgets only
ever go down: to add a rule, remove one first (see "一条新规则该放哪" in CLAUDE.md).
"""

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


def test_claude_md_within_line_budget():
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").count("\n")
    assert lines <= CLAUDE_MD_MAX_LINES, (
        f"CLAUDE.md is {lines} lines (budget {CLAUDE_MD_MAX_LINES}); move prose to docs/"
    )
