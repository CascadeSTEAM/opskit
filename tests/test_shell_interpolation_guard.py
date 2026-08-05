"""Every value interpolated into a shell-parsed command must be quoted.

opskit #124, ledger row 17.

`ssh` joins its trailing arguments into a **single string** that a shell on the
remote host parses. Passing values as separate argv elements gives no protection
whatsoever — a fact this repo learned once already when a code review caught
arbitrary remote execution via a crafted container name.

`bin/baseline.py` had four unquoted interpolations, two of which fed **filenames
read off the remote host** into a command that host's shell would parse. A file
named with shell metacharacters became execution on the machine being baselined —
and a baseline tool is pointed at hosts in unknown states by design.

This guard is AST-based rather than regex-based on purpose: a regex cannot reliably
distinguish `f"cat {shlex.quote(p)}"` from `f"cat {p}"`, and a guard with false
positives gets disabled, at which point it protects nothing.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Functions whose argument is handed to a shell — locally via shell=True, or
# remotely because ssh concatenates and the far end parses. Add to this list when
# a new such helper appears; test_the_helper_list_is_not_empty keeps it honest.
SHELL_HELPERS = {
    "run",           # bin/baseline.py's local closure over ssh_cmd
    "ssh_cmd",
    "run_remote",
    "remote_exec",
}

SOURCE_DIRS = ("bin", "mcp")


def python_sources() -> list[Path]:
    out: list[Path] = []
    for d in SOURCE_DIRS:
        out.extend(sorted((ROOT / d).glob("*.py")))
    # bin/ holds extensionless executables too; include the ones that are python.
    for p in sorted((ROOT / "bin").iterdir()):
        if p.suffix == "" and p.is_file():
            head = p.read_text(errors="replace")[:80]
            if "python" in head:
                out.append(p)
    return out


def _is_quoted(node: ast.AST) -> bool:
    """True when the interpolated expression is a shlex.quote(...) call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "quote":
        return True
    return isinstance(func, ast.Name) and func.id == "quote"


def unquoted_interpolations(path: Path) -> list[tuple[int, str]]:
    """(line, code) for each f-string arg to a shell helper with a bare value."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return []

    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name not in SHELL_HELPERS:
            continue

        for arg in node.args:
            if not isinstance(arg, ast.JoinedStr):
                continue
            for piece in arg.values:
                if isinstance(piece, ast.FormattedValue) and not _is_quoted(piece.value):
                    findings.append((piece.lineno, ast.unparse(arg)[:90]))
    return findings


def test_the_helper_list_is_not_empty():
    """A guard that checks nothing passes silently forever."""
    assert SHELL_HELPERS


def test_there_are_sources_to_scan():
    assert python_sources()


@pytest.mark.parametrize("path", python_sources(), ids=lambda p: p.name)
def test_no_unquoted_interpolation_into_a_shell_command(path):
    findings = unquoted_interpolations(path)

    assert not findings, (
        f"{path.relative_to(ROOT)} interpolates unquoted values into a shell-parsed "
        f"command:\n" + "\n".join(f"  line {ln}: {code}" for ln, code in findings)
        + "\n\nssh joins its trailing arguments into ONE string that the remote "
          "shell parses, so separate argv elements protect nothing. Wrap each "
          "interpolated value in shlex.quote()."
    )


# ── the guard's own behaviour ─────────────────────────────────────────────────
# A guard nobody has seen fail is a guard nobody knows works.

def test_the_guard_catches_a_bare_interpolation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('name = "x"\nrun(f"cat /etc/{name}")\n')

    findings = unquoted_interpolations(bad)

    assert len(findings) == 1


def test_the_guard_accepts_shlex_quote(tmp_path):
    good = tmp_path / "good.py"
    good.write_text('import shlex\nname = "x"\nrun(f"cat {shlex.quote(name)}")\n')

    assert unquoted_interpolations(good) == []


def test_the_guard_accepts_a_bare_quote_import(tmp_path):
    """`from shlex import quote` is equally correct and must not false-positive."""
    good = tmp_path / "good2.py"
    good.write_text('from shlex import quote\nn = "x"\nrun(f"cat {quote(n)}")\n')

    assert unquoted_interpolations(good) == []


def test_the_guard_ignores_calls_that_are_not_shell_helpers(tmp_path):
    """print(f"{x}") is not a security problem; flagging it would get this
    disabled."""
    other = tmp_path / "other.py"
    other.write_text('x = 1\nprint(f"value {x}")\nlogging.info(f"v {x}")\n')

    assert unquoted_interpolations(other) == []


def test_the_guard_flags_only_the_unquoted_part_of_a_mixed_string(tmp_path):
    mixed = tmp_path / "mixed.py"
    mixed.write_text('import shlex\na=1\nb=2\nrun(f"cp {shlex.quote(a)} {b}")\n')

    findings = unquoted_interpolations(mixed)

    assert len(findings) == 1


def test_a_syntax_error_does_not_break_the_scan(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def (\n")

    assert unquoted_interpolations(broken) == []
