#!/usr/bin/env python3
"""idea.py — deterministic CLI for the idea-capture ledger.

Ported from ~/Projects/M5Stack/lilyetibot (dev principle 1, "Never
lose an idea") per operator directive 2026-07-20.

Raw enhancement/tooling ideas get captured to docs/ideas.md as a
markdown table row instead of a GitHub issue per idea — that avoids a
ticket flood and keeps overlapping ideas consolidatable before they
become tracked work. GH issues are filed only at triage time, by the
`idea-triage` skill (.opencode/skills/idea-triage/SKILL.md), which
writes the resulting issue number back onto the covered ledger row(s)
via `mark` so they're never re-picked.

Ledger table shape (docs/ideas.md):
  | Date | Desire (1-5) | Title | Description | Status | GH# |

Status values: new | consolidated | accepted | declined (reason).
A literal "|" inside a title/description is escaped to "\\|" on write
and unescaped again whenever a row is read back out, so pipes in free
text never corrupt the table structure.

Usage:
  bin/idea.py [--file PATH] add --desire 1..5 --title T --desc D
  bin/idea.py [--file PATH] list [--status S] [--min-desire N]
  bin/idea.py [--file PATH] search WORD [WORD ...]
  bin/idea.py [--file PATH] mark (--row N | --title T) --status S
      [--gh N] [--reason R]

--file defaults to docs/ideas.md relative to the repo root (works
regardless of cwd); pass it explicitly to operate on a different copy
(tests use this to avoid touching the real ledger).

Exit non-zero on any failure; row numbers are 1-based and stable
across list/search/mark (they refer to position in the ledger, not to
a filtered view).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = REPO_ROOT / "docs" / "ideas.md"

HEADER_PREFIX = "| Date"
STATUSES = ("new", "consolidated", "accepted", "declined")


def git_add(path: Path) -> None:
    """Stage a file in git so the change is tracked (best-effort, no-op outside a repo)."""
    try:
        subprocess.run(
            ["git", "add", str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # not in a git repo or git unavailable — don't fail the idea tool over it


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def unescape_cell(text: str) -> str:
    return text.replace("\\|", "|")


def flatten(text: str) -> str:
    """Collapse a possibly-multi-line value to a single ledger line."""
    return "; ".join(line.strip() for line in text.splitlines() if line.strip())


def split_row(line: str) -> list[str]:
    """Split a markdown table row on unescaped '|', tolerating padding."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


@dataclass
class Idea:
    date: str
    desire: str
    title: str
    desc: str
    status: str
    gh: str

    def render(self) -> str:
        cells = [
            self.date,
            self.desire,
            escape_cell(self.title),
            escape_cell(self.desc),
            self.status,
            self.gh,
        ]
        return "| " + " | ".join(cells) + " |"


@dataclass
class Ledger:
    path: Path
    prefix: list[str]  # everything up to and including the separator row
    rows: list[Idea]
    suffix: list[str]  # any lines after the table (normally none)

    def write(self) -> None:
        lines = [*self.prefix, *(row.render() for row in self.rows), *self.suffix]
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"
        self.path.write_text(text)
        git_add(self.path)


def load_ledger(path: Path) -> Ledger:
    if not path.exists():
        raise SystemExit(f"ledger not found: {path}")
    lines = path.read_text().splitlines()
    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith(HEADER_PREFIX)),
        None,
    )
    if header_idx is None:
        raise SystemExit(f"no ledger table found in {path} (missing '{HEADER_PREFIX}' header)")
    sep_idx = header_idx + 1

    rows: list[Idea] = []
    row_end = sep_idx + 1
    for i in range(sep_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip().startswith("|"):
            row_end = i
            break
        row_end = i + 1
        cells = [unescape_cell(c) for c in split_row(line)]
        if len(cells) < 6:
            cells += [""] * (6 - len(cells))
        date, desire, title, desc, status, gh = cells[:6]
        rows.append(Idea(date, desire, title, desc, status, gh))

    prefix = lines[: sep_idx + 1]
    suffix = lines[row_end:]
    return Ledger(path=path, prefix=prefix, rows=rows, suffix=suffix)


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_table(entries: list[tuple[int, Idea]]) -> str:
    headers = ["#", "Date", "D", "Title", "Description", "Status", "GH#"]
    table = [headers]
    for idx, idea in entries:
        table.append([str(idx), idea.date, idea.desire, idea.title, idea.desc, idea.status, idea.gh])
    widths = [max(len(row[col]) for row in table) for col in range(len(headers))]
    return "\n".join(
        " | ".join(cell.ljust(width) for cell, width in zip(row, widths)) for row in table
    )


def numbered(ledger: Ledger) -> list[tuple[int, Idea]]:
    return list(enumerate(ledger.rows, start=1))


# --- subcommands -----------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> None:
    ledger = load_ledger(args.file)
    idea = Idea(
        date=dt.date.today().isoformat(),
        desire=str(args.desire),
        title=flatten(args.title),
        desc=flatten(args.desc),
        status="new",
        gh="",
    )
    ledger.rows.append(idea)
    ledger.write()
    print(f"added row {len(ledger.rows)}: {idea.title}")


def cmd_list(args: argparse.Namespace) -> None:
    ledger = load_ledger(args.file)
    entries = numbered(ledger)
    if args.status:
        entries = [
            (i, idea) for i, idea in entries
            if idea.status == args.status or idea.status.startswith(args.status + " ")
        ]
    if args.min_desire is not None:
        entries = [(i, idea) for i, idea in entries if safe_int(idea.desire) >= args.min_desire]
    if not entries:
        print("no matching ideas.")
        return
    print(format_table(entries))


def cmd_search(args: argparse.Namespace) -> None:
    ledger = load_ledger(args.file)
    words = [w.lower() for w in args.words]
    entries = []
    for i, idea in numbered(ledger):
        haystack = f"{idea.title} {idea.desc}".lower()
        if all(word in haystack for word in words):
            entries.append((i, idea))
    if not entries:
        print("no ideas matched.")
        return
    print(format_table(entries))


def cmd_mark(args: argparse.Namespace) -> None:
    ledger = load_ledger(args.file)
    if args.row is not None:
        if args.row < 1 or args.row > len(ledger.rows):
            raise SystemExit(f"row {args.row} out of range (1..{len(ledger.rows)})")
        idx = args.row - 1
    else:
        matches = [i for i, idea in enumerate(ledger.rows) if idea.title == args.title]
        if not matches:
            raise SystemExit(f"no row found with title exactly: {args.title!r}")
        if len(matches) > 1:
            raise SystemExit(
                f"ambiguous: {len(matches)} rows have title {args.title!r}; use --row instead"
            )
        idx = matches[0]

    row = ledger.rows[idx]
    row.status = f"{args.status} ({args.reason})" if args.reason else args.status
    if args.gh is not None:
        row.gh = str(args.gh)
    ledger.write()
    print(f"row {idx + 1} updated: status={row.status} gh={row.gh or '-'}")


# --- CLI wiring --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # NOTE: --file lives ONLY on the top-level parser, not on each
    # subparser. argparse's subparsers build their own sub-namespace and
    # merge it over the parent's, so a --file default repeated on a
    # subparser would clobber a value already parsed at the top level.
    # That means --file must be given BEFORE the subcommand name
    # (e.g. `idea.py --file X add ...`, not `idea.py add --file X ...`).
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_LEDGER,
        help="path to the ideas ledger (default: docs/ideas.md at the repo root); "
             "must precede the subcommand",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="capture a new idea row")
    add_p.add_argument("--desire", type=int, required=True, choices=[1, 2, 3, 4, 5])
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--desc", required=True)
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", help="list ledger rows")
    list_p.add_argument("--status")
    list_p.add_argument("--min-desire", type=int)
    list_p.set_defaults(func=cmd_list)

    search_p = sub.add_parser(
        "search",
        help="case-insensitive substring search over title+description",
    )
    search_p.add_argument("words", nargs="+")
    search_p.set_defaults(func=cmd_search)

    mark_p = sub.add_parser("mark", help="update a row's status/GH#")
    target = mark_p.add_mutually_exclusive_group(required=True)
    target.add_argument("--row", type=int, help="1-based row number (as shown by list/search)")
    target.add_argument("--title", help="exact title match")
    mark_p.add_argument("--status", required=True, choices=STATUSES)
    mark_p.add_argument("--gh", type=int, help="GitHub issue number")
    mark_p.add_argument("--reason", help="stored as 'status (reason)', e.g. for declined")
    mark_p.set_defaults(func=cmd_mark)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
