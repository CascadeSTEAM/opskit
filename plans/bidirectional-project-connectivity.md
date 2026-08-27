# Plan: Bidirectional project connectivity (issue #279)

## Task

Make `opskit init` establish full bidirectional connectivity between OpsKit and the target project, so any OpenCode session in the target can access OpsKit's capabilities.

## Scope

### In scope
- Wire `opskit member sync|mount|status|sync-mount|prune` into `bin/opskit` CLI (Phase 3)
- `opskit init` adds project to `.project-remotes` and runs sync-mount
- `opskit init` generates `opskit.md` in the target with capability reference
- `opskit init` adds OpsKit as a reference in target's `opencode.json`
- Tests for all new CLI paths

### Out of scope
- `config_fragment` / `context_generators` rendering (deferred in design doc)
- Auto-discovery of members without `.project-remotes` entries
- Modifying OpsKit's AGENTS.md per-member (keep it static)

## Steps

### Step 1: Wire `opskit member` CLI (Phase 3) ✅ DONE

**Files:** `bin/opskit` (lines 1066-1076 area)

Added subcommand group `opskit member` with:
- `opskit member status` → `project_sync.py status`
- `opskit member sync` → `project_sync.py sync`
- `opskit member mount` → `project_sync.py mount`
- `opskit member sync-mount` → `project_sync.py sync-mount`
- `opskit member prune` → `project_sync.py prune`

Also wired tab completion and help text.

### Step 2: `opskit init` bidirectional enhancements ✅ DONE

**Files:** `bin/opskit-aware.py` (`cmd_init` function)

Implemented all three enhancements:

1. **Append to `.project-remotes`** — added `<name> <absolute-path>` if not already present (single-read dedup check)
2. **Generate `opskit.md`** in the target root — thin reference file with:
   - Available member commands
   - `opskit check` from target project
   - What gets mounted (agents, skills, rules)
   - Trust levels
   - Re-sync instructions
3. **Add reference to `opencode.json`** — if the target has `opencode.json`, adds:
   ```json
   "references": {
     "opskit": {
       "path": "~/Projects/opskit",
       "description": "OpsKit — infrastructure toolkit, subagents, MCP servers, skills"
     }
   }
   ```
   Skips if reference already exists or file doesn't exist.

### Step 3: Auto-run sync-mount after init ✅ DONE

Implemented with safety guards:
- Added `--no-sync-mount` flag to skip automatic sync-mount
- Skips sync-mount when target is inside the OpsKit repo (members under `projects/` or repo root)
- Skips sync-mount when `--no-sync-mount` is passed (used by tests)

### Step 4: Tests ✅ DONE

Added 7 integration tests in `tests/test_opskit_aware.py::TestBidirectionalInit`:
- `test_init_generates_opskit_md`
- `test_init_adds_to_project_remotes`
- `test_init_no_duplicate_remotes`
- `test_init_adds_opencode_reference`
- `test_init_skips_existing_opencode_reference`
- `test_init_opskit_md_respects_force`
- `test_init_opskit_md_force_backs_up`

### Step 5: Docs ✅ DONE

PR description includes full documentation of changes. Design doc will be updated as a follow-up.

## Acceptance criteria

- [x] `opskit member status|sync|mount|sync-mount|prune` work from CLI
- [x] `opskit init <path>` adds project to `.project-remotes` and runs sync-mount
- [x] `opskit init <path>` generates `opskit.md` in target
- [x] `opskit init <path>` adds OpsKit reference to target's `opencode.json`
- [x] All tests pass (`make test`) — 1140 passed, 1 skipped
- [x] No duplicates in `.project-remotes` on re-init

## Review notes

During review, the following issues were found and fixed:
1. **`.project-remotes` double-read** — was reading file twice (once for dedup, once for append). Fixed to single-read.
2. **sync-mount output stream** — was going to stdout, now goes to stderr (it's status output).
3. **Test isolation** — `TestBidirectionalInit` tests were calling `sync-mount` against the real repo, modifying `.opencode/skills/` and breaking `test_skill_tree_divergence`. Fixed by adding `--no-sync-mount` flag and using it in tests.

## Document History

| Date | Change |
|------|--------|
| 2026-08-27 | Plan completed — PR #281 merged. All steps done. |
