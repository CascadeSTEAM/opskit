# Design: Slash Command & Skill Scaffolding Tool

> **Status:** Implemented v6  
> **Created:** 2026-08-25  
> **Owner:** operator  
> **Related:** `automation-ladder.py`, opencode `command` config schema

---

## 1. Problem

Creating a new Opencode slash command + skill pair requires manual setup of
three independent pieces:

1. The **skill file** in `.opencode/skills/` — the actual procedure
2. The **command markdown** in `.opencode/command/<name>.md` — makes it invokable as `/name`
3. **Ladder registration** (`tick --skill NAME`) — tracks usage for codification offers

None of these are linked. A skill can exist without a command, a command can exist
without a skill file, and the ladder can't track a skill that hasn't been registered.
No single tool creates a complete, consistent triple in one shot.

## 2. Goals

1. **One command creates all three:** `bin/gen-command <name>` scaffolds a skill,
   command entry, and ladder registration in one step.
2. **Re-use existing machinery:** Delegate SKILL.md creation + symlinks to
   `automation-ladder.py new-skill`. Delegate symlink sync to
   `automation-ladder.py sync-skills`.
3. **Global scope only:** Commands live in `~/.config/opencode/opencode.json`.
4. **Idempotent:** Running twice with `--force` overwrites; without it, refuses.

## 3. Architecture

### 3.1 Ladder interaction

The ladder's `new-skill` command already registers the skill in the ledger and
creates the SKILL.md. The scaffold tool only needs to call `tick --skill NAME`
afterward to initialize the usage counter to 0 (first tick = first use).

After >3 ticks, the ladder will offer codification (script → MCP tool). This is
the only ladder interaction needed. The two-phase journaling mechanism
(`log --task` → `mark-created`) is for processes that *emerge* from manual
repetition, not for commands users explicitly create.

| Ladder command | When called | Purpose |
|---------------|-------------|---------|
| `new-skill --name N --description D --triggers T` | After collecting params | Scaffolds SKILL.md, symlinks, registers skill in ledger |
| `tick --skill NAME` | Immediately after `new-skill` | Bumps skill count to 1 (first use) |
| `sync-skills` | After `new-skill` | Ensures `.claude/skills/<name>` symlink exists (defensive re-run) |

### 3.2 Full data flow

```
User runs: bin/gen-command grind --auto --description "Work the backlog..."
                │
                ▼
        Wizard collects params
                │
                ├── name: grind
                ├── description: "Work the backlog..."
                ├── triggers: grind, backlog, clear the backlog
                └── type: skill-loader
                │
                ▼
        Step 1: Create skill + register in ladder (delegate)
        ┌────────────────────────────────────────────┐
        │ new-skill --name grind                      │
        │   --description "Work the backlog..."       │
        │   --triggers "grind, backlog, clear the..." │
        └────────────────────────────────────────────┘
                │
                ▼
        Step 2: Ensure symlink exists (delegate)
        ┌────────────────────────────────────────────┐
        │ sync-skills                                 │
        └────────────────────────────────────────────┘
                │
                ▼
        Step 3: Initialize ladder counter
        ┌────────────────────────────────────────────┘
        │ tick --skill grind                          │
        └────────────────────────────────────────────┘
                │
                ▼
        Step 4: Create command markdown file
        ┌────────────────────────────────────────────┐
        │ Write .opencode/command/grind.md           │
        │ YAML frontmatter (description) + template  │
        │ Backup existing if --force                 │
        └────────────────────────────────────────────┘
                │
                ▼
        Output:
        "Created skill 'grind' and command '/grind'.
         Ladder counter initialized — >3 ticks will offer codification."
```

### 3.3 Existing commands audit

`--check-all` should verify every scaffolded command has all three pieces:
skill file, config entry, ladder registration.

| Check | What it verifies |
|-------|-----------------|
| Skill file | `.opencode/skills/<name>/SKILL.md` exists |
| Config entry | `command.<name>` exists in global config |
| Ladder registration | Skill in ledger with count > 0 (ticked at least once) |
| Symlink | `.claude/skills/<name>` exists (managed by sync-skills) |

## 4. CLI Interface

```bash
# Interactive wizard (default, TTY)
bin/gen-command <name>

# Non-interactive
bin/gen-command <name> \
  --description "Work the backlog..." \
  --triggers "grind, backlog, clear the backlog" \
  --type skill-loader

# Override global config path
bin/gen-command <name> --config /path/to/opencode.json

# Dry-run: show what would be created + ladder entries
bin/gen-command <name> --dry-run \
  --description "..." \
  --triggers "..."

# Validate one skill+command+ladder entry
bin/gen-command --check <name>

# Audit ALL scaffolded commands
bin/gen-command --check-all
```

## 5. Validation

| Check | Behavior |
|-------|----------|
| Name uniqueness | Fail if skill exists in `.opencode/skills/` or command in `.opencode/command/` (unless `--force`) |
| Description non-empty | Fail with error message |
| Command file valid | Frontmatter has `description`, body has template content |
| Frontmatter complete (skill) | 4 fields: name, description, mode, triggers |
| Step 0 present | Usage tracking in step 0 (non-negotiable) |
| Ladder registration | `--check`/`--check-all` verify skill is ticked in ledger |
| Description consistency | Skill description matches command frontmatter description |

## 6. Error Handling

| Error | Behavior |
|-------|----------|
| Command file write fails | Backup existing with timestamp suffix; original untouched |
| Ladder ledger corrupt | Warn, continue with scaffold (ladder state is separate from scaffolding) |
| Validation fails | Show ALL errors at once, write nothing |
| Name exists | Refuse, show what exists, offer `--force` |

## 7. Non-Goals

- **No per-project scaffolding** — commands live in `.opencode/command/`
- **No built-in templates** — templates are hardcoded in the script
- **No `--init` subcommand** — session commands already in config
- **No `--migrate` for existing skills** — ladder chain verification only
- **No `mark-created` or task slug** — these are for processes emerging from
  manual repetition, not for explicitly-created commands

## 8. File Locations

```
/home/netyeti/Projects/opskit/
├── bin/gen-command                     # The scaffold tool
├── .opencode/skills/<name>/            # Scaffolded skills
│   └── SKILL.md
├── .opencode/command/<name>.md         # Command markdown (scaffolded)
│   ---
│   description: ...
│   ---
│
│   <template body>
└── .claude/skills/<name>               # Symlink → ../../.opencode/skills/<name>
    # (managed by automation-ladder.py sync-skills)
```

## 9. Testing

1. Name uniqueness (pass + fail)
2. Description validation
3. Template type selection (3 types)
4. `new-skill` delegation
5. `tick` registration
6. `sync-skills` delegation
7. Command file creation + frontmatter
8. `--dry-run` output
9. `--check` validation (pass + fail)
10. `--check-all` audits all three pieces (skill + command + ladder)
11. `--force` overwrite behavior
12. Description consistency check

## 10. Design Decisions

### 10.1 Only `tick`, not `mark-created`

The ladder's `mark-created` links a journaled task to a newly-scaffolded skill.
This is for processes that *emerge* from manual repetition — the agent does the
work manually several times, the ladder offers a skill, and the skill replaces
the manual process.

Slash commands are explicit user requests for automation. There is no
"manual repetition" task journal behind them. `mark-created` would create a
phantom linkage. The only ladder interaction that matters is `tick` —
register the skill so usage can be tracked for codification offers.

**Decision:** Call `new-skill` (which registers the skill) + `tick --skill`.
No task slug, no `mark-created`, no `--task` flag.

### 10.2 `--dry-run` shows ladder entries

A dry run that only shows the config entry hides the ladder registration that
is the primary value of the tool (usage tracking for codification offers).

**Decision:** `--dry-run` prints the skill that would be created, the command
entry, AND the `tick --skill <name>` that would be executed.

### 10.3 Atomic writes via `os.replace()`

A corrupted opencode.json breaks all sessions. A backup-and-overwrite pattern
risks leaving the config in a broken state if interrupted between write and
backup removal.

**Decision:** Write to temp file, `os.replace()` (atomic on POSIX). A
pre-write backup is still created as a manual recovery safety net, but the
atomic rename is the primary corruption protection.
