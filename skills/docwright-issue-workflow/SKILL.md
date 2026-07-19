---
name: docwright-issue-workflow
description: End-to-end GitHub issue processing — branch, fix, test, PR, merge, cleanup
distributable: true
---

# docwright-issue-workflow

End-to-end workflow for processing a GitHub issue: from pre-flight through
branch, fix, test, PR, merge, and cleanup. Core steps are automated via MCP
tools for consistency and reduced token usage.

## Trigger

Any task matching: "process issue #N", "work on issue N", "fix issue N",
"address issue N", "tackle issue N", "resolve issue N".

## MCP Tools

| Tool | Function | When to call |
|------|----------|-------------|
| `issue_preflight({ num })` | Confirm issue open, check branches/PRs/plans, sync status | **Step 1** — always first |
| `sync_issue_file({ num })` | Create/update `issues/<slug>.md` from GH data | **Step 2** — if no local file |
| `start_issue_branch({ num, type })` | Create validated branch from latest main | **Step 3** — before coding |
| `complete_issue_branch({ num, merge?, skip_tests? })` | Tests → push → PR → merge → cleanup | **Step 7** — after implementation |

## Workflow Steps

### 1. Pre-flight

Call `issue_preflight({ num })`.

The tool returns structured JSON with:
- `ready: bool` — false if branches/PRs already exist for this issue
- `issue: { state, title, labels, url }` — from GitHub
- `existingBranches: string[]` — any branches referencing this number
- `existingPRs: { number, title, url }[]` — any open PRs
- `issueFile: string|null` — matching file in `issues/` if found
- `issueFileHasLink: bool` — whether `github_issue:` frontmatter is set
- `planMatches: string[]` — matching plans/proposals
- `warnings: string[]` — actionable flags

If `ready: false`, report the warnings to the human and ask how to proceed.
If issue is closed or not found, stop.

### 2. Issue File Sync

Call `sync_issue_file({ num })` if no local `issues/` file was found in
pre-flight, or if the file exists but lacks `github_issue:` frontmatter.

The tool:
- Fetches title, body, and labels from the GitHub issue
- Generates a kebab-case slug from the title
- Creates `issues/<slug>.md` with full frontmatter (`github_issue: <num>`)
- Or updates the existing file to add the `github_issue:` link
- Idempotent: skips if link already exists; pass `force: true` to overwrite

Returns path to the file.

### 3. Create Branch

Call `start_issue_branch({ num, type })`.

- `type` must be one of: `fix`, `feat`, `docs`, `refactor`, `chore`
- Fetches latest `origin/main` before branching
- Creates `fix/115-duplicate-plan-paths` style branch
- Idempotent: returns existing branch name if one already exists

Returns branch name.

### 4. Implement

- Follow codebase conventions (see AGENTS.md, CLAUDE.md)
- One logical change per commit
- Commit message format: `<type>: <description> (#<num>)`
- Reference the issue in the commit body if relevant

### 5. Testing Phase (REQUIRED — gate before PR)

Before calling `complete_issue_branch`, run the relevant tests:

```bash
npm run typecheck          # zero errors
npm run lint               # zero warnings  
npm run test:webui         # all passing
npm run test:dispatch      # all passing
# Any additional test suites relevant to the change
```

If any step fails, fix before proceeding.

### 6. Commit & Push (as you work)

Stage changes and commit with a message referencing the issue:

```bash
git add <files>
git commit -m "<type>: <description> (#<num>)"
```

### 7. Complete (PR, Merge, Cleanup)

Call `complete_issue_branch({ num, merge?, skip_tests? })`.

**Without merge (default):** Runs tests, pushes branch, creates PR with
`Closes #<num>`, returns PR URL for human review.

**With merge=true:** Runs tests, pushes, creates PR, squash-merges,
verifies the issue auto-closed, checks out main, deletes the local branch.

Parameters:
- `num` — issue number (required)
- `merge` — set `true` to auto-merge (default: false)
- `skip_tests` — set `true` to skip test suite (default: false; use
  only if you already ran tests in step 5)

If auto-merge is set, the tool also:
- Verifies the GH issue transitioned to CLOSED
- Switches to main, resets to origin/main
- Deletes the local feature branch
- Logs to `.docwright/audit.jsonl`

### 8. Post-Merge Verification

If the GH issue did NOT auto-close (rare but possible with race conditions),
close it manually: `gh issue close <num>` and investigate why auto-close
failed.

## Error Handling

| Scenario | Action |
|----------|--------|
| Issue already closed | Report, stop, suggest next issue |
| Existing branch/PR found | Report, ask human how to proceed |
| Tests fail | Fix failures, re-run full suite before PR |
| `complete_issue_branch` merge fails | PR was created — human can merge manually |
| GH API unreachable | Work locally, document issue number, create GH issue later |
