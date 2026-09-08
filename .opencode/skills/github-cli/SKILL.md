---
name: github-cli
description: "Use the gh CLI for all GitHub work in every agent runtime — issues, PRs, reviews, checks, raw API — in place of the remote GitHub MCP server, whose tool schemas cost tens of thousands of tokens per request and are no longer loaded anywhere (#314). Use for: github, pull request, pr, gh api, gh pr, gh issue"
mode: skill
triggers: github,pull request,pr,gh api,gh pr,gh issue
---

# github-cli

> No runtime loads the GitHub MCP server any more (#314). `gh` gives the same
> capability from the shell and is already authenticated — `gh auth status` to check.

## Quick Reference

| Need | Command |
|---|---|
| Issues | `gh issue list [--assignee @me] [--label L]` · `gh issue view N --comments` · `gh issue create --title T --body-file F` · `gh issue comment N --body …` · `gh issue close N` |
| Branch for an issue | `gh issue develop N --checkout`, then confirm with `git branch --show-current` |
| Pull requests | `gh pr list` · `gh pr view N --comments` · `gh pr create --fill --reviewer CascadeSTEAM/technology-support --assignee @me` · `gh pr checks N` · `gh pr diff N` · `gh pr review N --approve` / `--comment -b …` |
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
- opskit #314 — why the GitHub MCP server is not loaded in any runtime
