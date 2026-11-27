"""Guards for the Claude Code setup (CLAUDE.md, .claude/settings.json, the per-turn card).

Hooks fail silently: a wrong path or a deleted script just means the rules stop being
injected, and nobody notices. These checks make that failure loud. The two budgets only
ever go down: to add a rule, remove one first (see "一条新规则该放哪" in CLAUDE.md).
"""

import datetime
import json
import os
import re
import subprocess
import sys

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


def _commit_hook(project, command, cwd=None):
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd or project)})
    return subprocess.run(
        [sys.executable, str(ROOT / ".claude/hooks/test-before-commit.py")],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
    )


def test_commit_hook_blocks_red_and_lets_green_through(tmp_path):
    # A throwaway project, so the hook does not re-run this very suite.
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_a.py").write_text("def test_a():\n    assert 1 + 1 == 3\n", encoding="utf-8")

    blocked = _commit_hook(tmp_path, 'git add -A && git commit -q -m "x"')
    assert blocked.returncode == 2 and "提交被拦下" in blocked.stderr

    assert _commit_hook(tmp_path, "git status && git log --grep commit").returncode == 0
    assert _commit_hook(tmp_path, "git -C /somewhere/else commit -m x").returncode == 0

    # Different length on purpose: same size + same second would reuse the stale bytecode.
    (tests / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    assert _commit_hook(tmp_path, "git -c user.name=x commit -m x").returncode == 0


SKILLS = ROOT / ".claude" / "skills"
REPO_PATH = re.compile(r"`((?:\.claude|pipeline|tests|tools|docs|explorations)/[^`\s<>…]+)`")
# Code a project skill tells Claude to copy or edit. If it moves, the skill is lying: update both.
SKILL_ANCHORS = {
    "add-data-source": {
        "pipeline/core/source.py": ["class SourceInfo", "def download(", "def offline("],
        "pipeline/core/store.py": ['"_files"'],
        "pipeline/sources/census_flows.py": ["def check_matrix"],
        "pipeline/sources/tjcn_bulletins.py": ["DELAY ="],
        "pipeline/parse/places.py": ["class PlaceMatcher"],
    },
    "design-freeze": {
        "explorations/design-freeze/index.html": ["const RUBRIC", "const BASICS", "const SCORE", "const T = {",
                                                  "const ZH", 'id="s-decide"', 'class="newtag"', 'data-t="'],
        "explorations/design-freeze/audit-buttons.js": ["const secs", "dead:"],
    },
}


def test_project_skills_are_wellformed_and_point_at_real_things():
    for skill in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        md = (skill / "SKILL.md").read_text(encoding="utf-8")
        head = re.match(r"---\nname: (\S+)\ndescription: (.+?)\n---\n", md, re.S)
        assert head and head.group(1) == skill.name, f"{skill.name}: frontmatter name must match the folder"
        for path in REPO_PATH.findall(md):
            assert (ROOT / path).exists(), f"skill {skill.name} mentions {path}, which does not exist"
    for path in REPO_PATH.findall((ROOT / "docs" / "TOOLBOX.md").read_text(encoding="utf-8")):
        assert (ROOT / path).exists(), f"docs/TOOLBOX.md mentions {path}, which does not exist"
    for skill, files in SKILL_ANCHORS.items():
        assert (SKILLS / skill / "SKILL.md").is_file(), skill
        for path, anchors in files.items():
            text = (ROOT / path).read_text(encoding="utf-8")
            for anchor in anchors:
                assert anchor in text, f"skill {skill} relies on {anchor!r} in {path}"


def test_claude_md_within_line_budget():
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").count("\n")
    assert lines <= CLAUDE_MD_MAX_LINES, (
        f"CLAUDE.md is {lines} lines (budget {CLAUDE_MD_MAX_LINES}); move prose to docs/"
    )
