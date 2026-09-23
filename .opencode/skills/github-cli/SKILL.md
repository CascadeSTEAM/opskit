---
name: github-cli
description: "Use the gh CLI for all GitHub work in Claude Code and Crush, and as the default in OpenCode too — issues, PRs, reviews, checks, raw API. OpenCode also has a scoped, self-hosted github MCP (context/issues/pull_requests/repos only, ~2026-09) for inline PR review comments specifically; gh CLI still owns everything else (#314, #386). Use for: github, pull request, pr, gh api, gh pr, gh issue"
mode: skill
triggers: github,pull request,pr,gh api,gh pr,gh issue
---

# github-cli

> Claude Code and Crush have no GitHub MCP server configured — `gh` is the only
> path there. OpenCode also defaults to `gh` for everything scripted/one-off
> (issue/branch/PR mechanics); it additionally has a self-hosted `github`
> MCP entry (`github-mcp-server stdio`, `GITHUB_TOOLSETS=context,issues,
> pull_requests,repos`) reintroduced 2026-09-23 (#386) specifically for inline
> PR review-comment threads, which are clunky to construct correctly via
> `gh api`. The original remote Copilot-hosted MCP (#314) is gone for good —
> this is a different, narrower, locally-built binary. `gh auth status` to
> check CLI auth.

## Quick Reference

| Need | Command |
|---|---|
| Issues | `gh issue list [--assignee @me] [--label L]` · `gh issue view N --comments` · `gh issue create --title T --body-file F` · `gh issue comment N --body …` · `gh issue close N` |
| Branch for an issue | `gh issue develop N --checkout`, then confirm with `git branch --show-current` |
| Pull requests | `gh pr list` · `gh pr view N --comments` · `gh pr create --fill --reviewer CascadeSTEAM/technology-support --assignee @me` · `gh pr checks N` · `gh pr diff N` · `gh pr review N --approve` / `--comment -b …` |
| Inline PR review comment (line-specific) | **OpenCode**: MCP tools `pull_request_review_write` (`method: create`) → `add_comment_to_pending_review` (repeat per comment) → `pull_request_review_write` (`method: submit_pending`) — the workflow the server's own tool description specifies. **Claude Code / Crush** (no MCP fallback): `gh api repos/{owner}/{repo}/pulls/N/comments -f body="…" -f commit_id="$(gh pr view N --json headRefOid -q .headRefOid)" -f path="path/to/file" -F line=42 -f side=RIGHT` |
| Merge | `gh pr merge N --squash` — **only when the operator asks**; never merge on your own |
| Search | `gh search issues "words" --repo OWNER/REPO` · `gh search code "words" --repo OWNER/REPO` |
| Everything else | `gh api repos/{owner}/{repo}/… [--paginate] [-f key=value]` — REST/GraphQL covers every remaining MCP tool |
| Another repo | add `--repo OWNER/REPO` to any command |

Prefer `--json <fields> -q <jq>` for machine-readable output over scraping tables.

## Key Rules

- The `gh` skill owns the full issue → branch → PR workflow; this skill only
  maps capabilities. Pull first, never commit issue work on `main`, PR body
  carries `Closes #N`.
- Public repos: no client names, environment names, IPs or secrets in issue or
  PR text or branch names. Hooks guard commits, not what you paste into `gh`.
- Read before you write: `gh issue view` / `gh pr view` first, then act.

## Related

- `.opencode/skills/gh/SKILL.md` — the issue → branch → PR workflow this maps onto
- `.opencode/skills/git/SKILL.md` — commit format and atomic-commit rules
- opskit #314 — why the broad remote GitHub MCP was dropped everywhere
- opskit #386 — the narrower, self-hosted github MCP reintroduced for OpenCode only
