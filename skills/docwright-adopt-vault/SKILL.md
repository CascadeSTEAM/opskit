---
name: docwright-adopt-vault
description: Adopt an existing repo or folder into DocWright governance — Open, Lightweight, or Full mode. Use when the user says "adopt this vault", "adopt this repo", "set up docwright on this repo", "initialize docwright here", or "open this folder with docwright".
---

# DocWright Vault Adoption Skill

Bring an existing directory, repo, or Obsidian vault under DocWright governance,
or simply browse one with the DocWright Web UI.

## Modes

| Mode | Command | Effect |
|------|---------|--------|
| **Open** | `npm run open -- --vault <path>` | Zero-commitment browse — points Web UI at folder, writes nothing |
| **Lightweight** | `npm run adopt -- --dest <path> --mode lightweight` | Wires AI surfaces (MCP, hooks, skills); no git workflow changes |
| **Full** | `npm run adopt -- --dest <path> --mode full` | Permanent adoption: directory structure, hook install, frontmatter audit |
| **Upgrade** | `npm run adopt -- --dest <path> --upgrade` | Refreshes stale DocWright-managed files using manifest baseline |

## Process

### 1. Determine mode

- Check whether `.docwright/config.json` exists in the target — if so, route to **Upgrade** automatically.
- Ask the user which mode they want if not already stated. Default to **Open** for first contact with an unknown repo.
- All commands run from `$DOCWRIGHT_PATH`, not from inside the vault.

### 2. Open mode

```bash
cd $DOCWRIGHT_PATH
npm run open -- --vault /path/to/repo
```

Confirm the Web UI starts and `/api/list` returns files from the target. Nothing is written to the target directory.

### 3. Lightweight or Full mode

```bash
cd $DOCWRIGHT_PATH
npm run adopt -- --dest /path/to/vault --mode lightweight   # or full
```

After the script completes:
- Prompt the user to run `direnv allow` in the vault root.
- For full mode: confirm the pre-commit hook installed correctly (`git commit --dry-run` or `npm run hook:install -- --vault <path>`).

### 4. Review interactive outputs (full mode only)

The script presents findings for human approval before writing:
- `.gitignore` additions — review each entry, confirm or skip.
- Frontmatter audit findings — review flagged files, approve normalisation or skip.

Never auto-write frontmatter changes. Present findings and wait for confirmation.

### 5. Offer GitHub/Forgejo repo creation (optional)

```bash
gh repo create <name> --private --source /path/to/vault --remote origin
```

Only if the vault doesn't already have a remote.

### 6. Guide initial commit

Stage only DocWright-managed files for the first commit:
```bash
git add .env .envrc .mcp.json .claude/ .opencode/ .gemini/ .docwright/ profile.json GEMINI.md
git status   # review before committing
```

Confirm pre-commit validation passes before pushing.

### 7. Upgrade mode

```bash
cd $DOCWRIGHT_PATH
npm run adopt -- --dest /path/to/vault --upgrade
```

The script reports: files refreshed silently, files skipped (user-modified), new files added. Review the output and confirm.

## Failure handling

- **`DOCWRIGHT_PATH` unset:** stop and ask the user to set it (direnv or export)
  before running any command — do not guess the installation path.
- **hook:install fails:** report the exact command to run manually
  (`npm run hook:install -- --vault <path>`); don't retry silently.

## Notes

- `.gemini/settings.json` contains a machine-local absolute path — it is gitignored automatically and must never be committed.
- Skills copied to the vault (`.claude/skills/`, `.opencode/skills/`) are gitignored in adopted vaults — they are DocWright infrastructure, not vault content. (In the DocWright source repo itself they are canonical source and ARE committed.)
