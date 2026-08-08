"""One skill tree, not two (opskit #130, #131).

This repo used to track `skills/` and `.opencode/skills/`, neither generated.
Every skill present in both differed — nine pairs, one of them by 19 lines.
Skills encode operating procedure, so two versions of a skill is two
procedures, and which one an agent got depended on which tree its harness
read.

Ledger row 10 reported one symptom: `skills/endsession/SKILL.md` was a
*DocWright* skill instructing `npm run session:end`, in a repo with no
`package.json`, while explicitly forbidding the manual fallback that would
have worked.

Owner decision 2026-08-05: merge selectively, then delete `skills/` — one
tree survives. `.opencode/skills/` is canonical: `AGENTS.md` loads skills via
`opencode tool skill use <name>`, and Claude Code reaches the same files
through `.claude/skills/<name>` symlinks. So the guard is no longer "do not
drift further apart" but "there is only one tree to drift from".

The 11 DocWright-origin skills that lived only in `skills/` were deleted
rather than merged: they are alive and maintained in that project's own repo,
and a second maintained copy is the disease, not the cure.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / ".opencode" / "skills"
RETIRED = ROOT / "skills"


def test_the_retired_second_tree_is_gone():
    assert not RETIRED.exists(), (
        "skills/ was deleted in #131 — one tree survives. Adding it back "
        "recreates the two-procedures problem that issue existed to fix; put "
        "new skills in .opencode/skills/ instead."
    )


def test_the_canonical_tree_exists_and_has_skills():
    """A vacuous pass would hide every assertion below."""
    assert CANONICAL.is_dir()
    assert list(CANONICAL.glob("*/SKILL.md"))


def test_no_skill_references_another_projects_tooling():
    """Row 10's defect class, now checked across every skill rather than just
    endsession: a skill that tells an agent to run tooling this repo does not
    have is worse than no skill at all."""
    foreign = ("docwright", "npm run", "session:end", "phase:close")

    offenders = []
    for skill in sorted(CANONICAL.glob("*/SKILL.md")):
        text = skill.read_text().lower()
        for token in foreign:
            if token in text:
                offenders.append(f"{skill.relative_to(ROOT)} references '{token}'")

    assert not offenders, (
        "these skills reference another project's tooling, which does not "
        "exist in this repo:\n  " + "\n  ".join(offenders)
    )


def test_no_skill_points_at_the_nonexistent_scripts_directory():
    """The tools live in bin/; `scripts/` has never existed here, so a step-0
    command naming it fails on its first line (#166)."""
    offenders = [
        str(skill.relative_to(ROOT))
        for skill in sorted(CANONICAL.glob("*/SKILL.md"))
        if "scripts/" in skill.read_text()
    ]

    assert not offenders, (
        f"{offenders} reference a scripts/ path; the tools are in bin/"
    )


def test_endsession_names_the_real_shutdown_steps():
    """Guards against a fix that merely deletes the wrong content."""
    text = (CANONICAL / "endsession" / "SKILL.md").read_text().lower()

    for expected in ("session-log", "session note", "definition-of-done"):
        assert expected in text, f"endsession skill does not mention {expected}"
