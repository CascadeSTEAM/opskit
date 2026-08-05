"""Two tracked skill trees must not drift further apart (opskit #130, #131).

This repo tracks `skills/` and `.opencode/skills/`, and neither is generated. Every
skill present in both differed — nine pairs, one of them by 19 lines. Skills encode
operating procedure, so two versions of a skill is two procedures, and which one an
agent gets depends on which tree its harness reads.

Ledger row 10 reported one symptom: `skills/endsession/SKILL.md` was a *DocWright*
skill instructing `npm run session:end`, in a repo with no `package.json`, while
explicitly forbidding the manual fallback that would have worked. Fixed by matching
the correct copy.

The eight remaining pairs are **grandfathered on purpose**. Reconciling them needs a
content decision per skill and a ruling on which tree is canonical — tracked in #131.
Enforcing zero divergence today would fail on pre-existing drift, and a check that
cannot pass gets disabled, which is how the drift grew unnoticed in the first place.

So: freeze the known set, fail on anything new. The allowlist shrinking is a valid
change and needs no edit here; growing it requires a deliberate one, which is the
point.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TREE_A = ROOT / "skills"
TREE_B = ROOT / ".opencode" / "skills"

# Divergent as of 2026-08-05, tracked in #131. Remove entries as they are
# reconciled; do NOT add entries to make a failure go away.
KNOWN_DIVERGENT = {
    "backup",
    "check-connectivity",
    "git",
    "infra",
    "lifecycle",
    "security",
    "templates",
    "tools",
}


def shared_skills() -> list[str]:
    if not TREE_A.is_dir() or not TREE_B.is_dir():
        return []
    a = {d.name for d in TREE_A.iterdir() if (d / "SKILL.md").is_file()}
    b = {d.name for d in TREE_B.iterdir() if (d / "SKILL.md").is_file()}
    return sorted(a & b)


def diverges(name: str) -> bool:
    return (TREE_A / name / "SKILL.md").read_text() != (TREE_B / name / "SKILL.md").read_text()


def test_there_are_shared_skills_to_compare():
    """A vacuous pass would hide every assertion below."""
    assert shared_skills()


@pytest.mark.parametrize("name", shared_skills())
def test_no_new_divergence(name):
    if name in KNOWN_DIVERGENT:
        pytest.skip(f"{name} is known-divergent, tracked in #131")

    assert not diverges(name), (
        f"skills/{name}/SKILL.md and .opencode/skills/{name}/SKILL.md differ.\n"
        f"Two copies of a skill means two operating procedures, and which one an "
        f"agent follows depends on its harness. Update both, or reconcile the trees "
        f"(#131). Do NOT add '{name}' to KNOWN_DIVERGENT to silence this."
    )


def test_the_allowlist_does_not_name_skills_that_now_agree():
    """Keeps the list honest as pairs are reconciled — a stale entry overstates the
    problem and hides a regression behind a skip."""
    stale = sorted(n for n in KNOWN_DIVERGENT
                   if n in shared_skills() and not diverges(n))

    assert not stale, (
        f"{stale} no longer differ — remove them from KNOWN_DIVERGENT so the guard "
        f"protects them again"
    )


def test_the_allowlist_does_not_name_skills_that_are_not_shared():
    stale = sorted(n for n in KNOWN_DIVERGENT if n not in shared_skills())

    assert not stale, f"{stale} are not present in both trees — drop them"


def test_endsession_is_this_projects_procedure_not_another_projects():
    """Row 10: it was a DocWright skill telling agents to run npm scripts that do
    not exist here, and forbidding the manual fallback that would have worked."""
    for tree in (TREE_A, TREE_B):
        skill = tree / "endsession" / "SKILL.md"
        if not skill.is_file():
            continue
        text = skill.read_text().lower()
        for foreign in ("docwright", "npm run", "session:end", "phase:close"):
            assert foreign not in text, (
                f"{skill.relative_to(ROOT)} references '{foreign}' — that is another "
                f"project's tooling and does not exist in this repo"
            )


def test_endsession_names_the_real_shutdown_steps():
    """Guards against a fix that merely deletes the wrong content."""
    text = (TREE_B / "endsession" / "SKILL.md").read_text().lower()

    for expected in ("session-log", "session note", "definition-of-done"):
        assert expected in text, f"endsession skill does not mention {expected}"
