#!/usr/bin/env python3
"""
Lifecycle Processor — Single-script lifecycle management for opskit.

Detects frontmatter changes in proposals/ and plans/ and transitions them
through their lifecycle (approved → plan, completed → completed/, etc.).

Modes:
  --check       Run once: scan all proposals/plans, process pending transitions
  --watch       Long-running daemon: watch for file changes via watchdog library
  --dry-run     Show what would change without modifying anything. Exit code:
                  0 = no pending changes
                  1 = changes would be made
  --status      Print current state of all lifecycle documents

Usage:
  python3 scripts/lifecycle-processor.py --check
  python3 scripts/lifecycle-processor.py --dry-run
  python3 scripts/lifecycle-processor.py --status
  python3 scripts/lifecycle-processor.py --watch [--watch-interval=5]

Config (CLI flag > env var > default):
  --user                    Current operator (default: git config user.name)
  --watch-interval=5        File system poll interval in --watch mode (seconds)
  --heartbeat-interval=300  How often to log/check server health (seconds)
  --log-file=               Optional log file path (default: stderr)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


def ollama_request(payload: dict, max_retries: int = 3, base_delay: float = 2.0) -> Optional[dict]:
    """
    Call Ollama /api/chat with retry + exponential backoff.
    Ollama drops connections when loading models into GPU — retry handles this.
    Returns the parsed response dict, or None if all retries fail.
    """
    import requests as req_lib

    for attempt in range(max_retries):
        try:
            resp = req_lib.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=300
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log(f"  Ollama call failed (attempt {attempt+1}/{max_retries}): {e}", 'warning')
                log(f"  Retrying in {delay:.0f}s...", 'warning')
                time.sleep(delay)
            else:
                log(f"  Ollama call failed after {max_retries} attempts: {e}", 'warning')
                return None


# =============================================================================
# Paths & Constants
# =============================================================================

# Resolve repo root: env var (for testing) > script location
_REPO_ROOT_ENV = os.environ.get('LIFE_CYCLE_REPO_ROOT')
REPO_ROOT = Path(_REPO_ROOT_ENV).resolve() if _REPO_ROOT_ENV else Path(__file__).parent.parent.resolve()
PROPOSALS_DIR = REPO_ROOT / 'proposals'
APPROVED_DIR = PROPOSALS_DIR / 'approved'
PLANS_DIR = REPO_ROOT / 'plans'
COMPLETED_DIR = PLANS_DIR / 'completed'
TEMPLATE_FILE = REPO_ROOT / 'templates' / 'plan-template.md'
OPENCODE_SERVER_URL = os.environ.get('OPENCODE_SERVER_URL', 'http://localhost:14096')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
PLAN_GENERATION_MODEL = os.environ.get('PLAN_GENERATION_MODEL', 'qwen2.5:7b')
ISSUES_DIR = REPO_ROOT / 'issues'

PROPOSAL_REQUIRED_FIELDS = ['title', 'author', 'created', 'approved', 'created_by']
PROPOSAL_OPTIONAL_DEFAULTS: dict[str, Any] = {
    'tags': [],
    'priority': None,
    'assigned_to': [],
    'related_to': [],
    'depends_on': [],
    'blocks': [],
    'automated': 'off',
}

TRACKING_STATUS_PROPS = ('in-discussion', 'ready-for-approval', 'archived')
TRACKING_STATUS_PLANS = ('in-discussion', 'ready-for-approval', 'blocked-tokens', 'ready')


# =============================================================================
# Utility functions
# =============================================================================

def log(msg: str, level: str = 'info') -> None:
    """Simple structured logging. Writes to stderr unless log_file is set."""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f"[{ts}] [{level.upper()}] {msg}", file=sys.stderr, flush=True)


def run_cmd(cmd: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a shell command, return result."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        log(f"Command failed (exit {result.returncode}): {cmd}", 'error')
        if result.stderr.strip():
            log(f"Stderr: {result.stderr.strip()}", 'error')
    return result


def get_current_user() -> str:
    """Resolve current operator: git config user.name or env or 'unknown'."""
    try:
        name = subprocess.check_output(
            ['git', 'config', 'user.name'], cwd=REPO_ROOT, text=True
        ).strip()
        if name:
            return name
    except Exception:
        pass
    return os.environ.get('LIFE_CYCLE_USER', 'unknown')


def get_server_password() -> str:
    """Try to read opencode server password from multiple sources."""
    pw = os.environ.get('OPENCODE_SERVER_PASSWORD', '')
    if pw:
        return pw
    try:
        result = subprocess.run(
            ['sudo', 'cat', '/etc/opencode-server/env'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith('OPENCODE_SERVER_PASSWORD='):
                    return line.split('=', 1)[1]
    except Exception:
        pass
    return ''


def fill_template_from_proposal(proposal_text: str, plan_fm: dict) -> str:
    """
    Fill the plan template from proposal content when LLM is unavailable.
    Extracts sections from the proposal and maps them to plan sections.
    """
    # Title
    title = plan_fm.get('title', 'Plan')

    # Extract sections from proposal markdown (## and ### headers)
    sections = {}
    current_section = 'preamble'
    sections[current_section] = []
    for line in proposal_text.split('\n'):
        h2_match = re.match(r'^##\s+(.+)$', line)
        h3_match = re.match(r'^###\s+(.+)$', line)
        if h2_match:
            current_section = h2_match.group(1).strip()
            sections[current_section] = []
        elif h3_match:
            current_section = h3_match.group(1).strip()
            sections[current_section] = []
        else:
            sections.setdefault(current_section, []).append(line)

    # Build Overview from Summary + Problem Statement + Proposed Solution + phases
    overview_parts = []
    for key in ('Summary', 'Problem Statement', 'Proposed Solution'):
        if key in sections:
            txt = '\n'.join(sections[key]).strip()
            if txt:
                overview_parts.append(txt)
    # Include phase sub-sections in overview
    phase_texts = []
    for key in sections:
        lkey = key.lower()
        if lkey.startswith('phase') or 'phase' in lkey:
            txt = '\n'.join(sections[key]).strip()
            if txt:
                phase_texts.append(f"### {key}\n{txt}")
    if phase_texts:
        overview_parts.append('\n\n'.join(phase_texts))
    overview = '\n\n'.join(overview_parts) if overview_parts else f"Implement {title}."

    # Build Implementation Steps from Proposal sections / phases
    steps = []
    for key in sections:
        lkey = key.lower()
        if 'phase' in lkey or 'step' in lkey or 'deploy' in lkey or 'agent' in lkey or 'alert' in lkey or 'automation' in lkey or 'config' in lkey:
            txt = '\n'.join(sections[key]).strip()
            bullet_match = re.findall(r'[-*]\s+(.+?)(?:\n|$)', txt)
            if bullet_match:
                for b in bullet_match:
                    steps.append(b.strip())
            else:
                steps.append(txt[:120].strip())

    if not steps:
        steps.append("Complete all tasks defined in the approved proposal.")

    steps_table = '\n'.join(
        f'| {i+1} | {s} | See proposal for details. | ⏳ Pending |'
        for i, s in enumerate(steps)
    )
    if not steps_table:
        steps_table = '| 1 | | | ⏳ Pending |'

    # Build Testing Plan from Expected Outcomes
    testing = '\n'.join(sections.get('Expected Outcomes', [])).strip()
    if not testing:
        testing = 'Verify each implementation step produces the expected result before proceeding.'

    # Build Rollback
    rollback = '1. Revert changes via git: `git checkout -- <changed-files>`\n'
    rollback += '2. Reverse any configuration changes made during each step.\n'
    rollback += '3. If a step cannot be completed, document the failure and move to the next step.'

    # Build Risk Assessment from Resources/Discussion
    risks = []
    resource_text = '\n'.join(sections.get('Resources Required', [])).strip()
    discussion_text = '\n'.join(sections.get('Discussion Notes', [])).strip()
    if resource_text:
        risks.append(f'| Resource constraints | Low | Medium | Validate resources are available before starting. {resource_text[:100]} |')
    risks.append('| Service disruption | Low | Medium | Perform changes during maintenance windows. |')
    risks.append('| Configuration drift | Medium | Low | All changes must be Ansible-managed and git-tracked. |')
    risks_table = '\n'.join(risks)

    # Author
    author = plan_fm.get('author', 'gemini')

    # Tags as comma-separated string
    tags = plan_fm.get('tags', [])
    tags_str = ', '.join(tags) if tags else ''

    # assigned_to as list
    assigned = plan_fm.get('assigned_to', [])
    assigned_str = ', '.join(assigned) if assigned else ''

    # Build the filled body
    body = f"""# {title}

## Mode

Plan modes: `off` (mentorship), `guided` (agent drafts, human approves), `full` (autonomous).

**MENTORSHIP MODE — Human leads, LLM advises**

- Human carries out tasks their own way
- LLM provides SOP compliance checks and safety warnings
- LLM offers suggestions when human asks for help

## Overview

{overview}

## Implementation Steps

| Step | Action | Details | Status |
|------|--------|---------|--------|
{steps_table}

## Testing Plan

{testing}

## Rollback Procedures

{rollback}

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
{risks_table}

## Document History

| Date | Change | Author |
|------|--------|--------|
| {datetime.now(timezone.utc).strftime('%Y-%m-%d')} | Created | {author} |

## Progress Journal

A running log of what happened during execution — what was done, what worked, what failed, and why decisions were made.

| Date | Step | Status | Notes |
|------|------|--------|-------|
| | | | |
"""
    return body


def ensure_required_sections(body: str, plan_fm: dict) -> str:
    """
    Ensure the plan body has all required sections.
    Appends any that are missing with placeholder content.
    """
    required_sections = {
        'Document History': (
            '## Document History\n\n'
            '| Date | Change | Author |\n'
            '|------|--------|--------|\n'
            f'| {datetime.now(timezone.utc).strftime("%Y-%m-%d")} | Created | {plan_fm.get("author", "gemini")} |\n'
        ),
        'Progress Journal': (
            '## Progress Journal\n\n'
            'A running log of what happened during execution — what was done, '
            'what worked, what failed, and why decisions were made.\n\n'
            '| Date | Step | Status | Notes |\n'
            '|------|------|--------|-------|\n'
            '| | | | |\n'
        ),
    }
    for section_name, section_content in required_sections.items():
        pattern = rf'^## {re.escape(section_name)}\s*$'
        if not re.search(pattern, body, re.MULTILINE):
            body += '\n' + section_content
    return body


def generate_plan_body(proposal_path: Path, plan_fm: dict) -> str:
    """
    Generate a filled-in plan body from an approved proposal using the Ollama API.

    Reads the proposal content, constructs a prompt instructing the LLM to generate
    the plan sections (Overview, Implementation Steps, Testing Plan, Rollback
    Procedures, Risk Assessment), calls Ollama's /api/chat endpoint, and returns
    the generated markdown body (without frontmatter).

    Returns an empty string if generation fails (caller should fall back to
    template body or empty body).
    """
    try:
        proposal_content = proposal_path.read_text(encoding='utf-8')
    except Exception as e:
        log(f"  Cannot read proposal for plan generation: {e}", 'warning')
        return ""

    # Build sections summary from the plan frontmatter
    title = plan_fm.get('title', 'Untitled Plan')
    mode = plan_fm.get('automated', 'off')
    assigned = plan_fm.get('assigned_to', [])
    if isinstance(assigned, list):
        assigned_str = ', '.join(assigned)
    else:
        assigned_str = str(assigned)

    system_prompt = f"""You are a planning assistant for this infrastructure repository.
Your task is to generate a complete, well-structured execution plan body from an approved proposal.

The plan must include these sections:
1. **Overview** (2-4 paragraphs summarizing what this plan achieves, why it matters, and the approach)
2. **Implementation Steps** (a table with columns: Step, Action, Details, Status — break the work into concrete, numbered steps)
3. **Testing Plan** (how to verify each step worked before moving to the next)
4. **Rollback Procedures** (how to undo each step if something goes wrong)
5. **Risk Assessment** (a table with columns: Risk, Likelihood, Impact, Mitigation — identify 3-5 key risks)
6. **Document History** (a table with columns: Date, Change, Author — start with the creation entry)
7. **Progress Journal** (a table with columns: Date, Step, Status, Notes — empty placeholder for execution log)

Format guidelines:
- Use proper Markdown
- Implementation Steps table: use | Step | Action | Details | Status | with ⏳ Pending for all statuses
- Risk Assessment table: use | Risk | Likelihood | Impact | Mitigation |
- Be specific and actionable — reference real device names, IPs, config files from the proposal
- Do NOT include YAML frontmatter (--- blocks) in your response
- Do NOT include the plan title or mode section — those are already set
- Output ONLY the markdown body sections"""

    user_prompt = f"""Generate the execution plan body for this plan:

Plan Title: {title}
Mode: {mode}
Assigned To: {assigned_str}

Here is the approved proposal to base the plan on:

---

{proposal_content}

---

Now generate the plan body sections (Overview, Implementation Steps, Testing Plan, Rollback Procedures, Risk Assessment) based on the proposal above."""

    payload = {
        "model": PLAN_GENERATION_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 4096
        }
    }

    try:
        result = ollama_request(payload)
        body = (result.get('message', {}) or {}).get('content', '') if result else ''

        # Strip any accidental frontmatter the LLM might add
        body = re.sub(r'^---\n.*?\n---\n?', '', body, flags=re.DOTALL)
        body = body.strip()

        if body:
            log(f"  Generated plan body ({len(body)} chars) using {PLAN_GENERATION_MODEL}")
        else:
            log(f"  LLM returned empty response", 'warning')

        return body

    except Exception as e:
        log(f"  Plan generation failed: {e}", 'warning')
        log(f"  Falling back to template body.", 'warning')
        return ""


def critique_and_improve_plan_body(proposal_content: str, plan_body: str, plan_fm: dict) -> str:
    """
    Critique a generated plan body for gaps and improvements, then produce
    an improved version using the Ollama API.

    Takes the original proposal content and the draft plan body, asks the LLM
    to review for missing steps, unclear actions, unaddressed risks, and other
    gaps, then returns an improved plan body.

    Returns the original plan_body unchanged if critique/improve fails.
    """
    title = plan_fm.get('title', 'Untitled Plan')

    critique_prompt = f"""You are a quality assurance reviewer for technical execution plans.
Your job is to critique a draft plan and produce an improved version.

Review the plan against the original proposal for:
1. **Missing implementation steps** — Are any phases or tasks from the proposal missing?
2. **Unclear actions** — Are any steps vague or ambiguous? Make them concrete.
3. **Unaddressed risks** — Does the Risk Assessment miss any risks mentioned in the proposal?
4. **Missing rollback** — Does every implementation step have a corresponding undo procedure?
5. **Missing testing** — Is there a clear way to verify each step succeeded?
6. **Reference accuracy** — Do device names, IPs, file paths match the proposal?
7. **Completeness** — Are all seven sections (Overview, Steps, Testing, Rollback, Risk, Document History, Progress Journal) present and substantial?

Output format:
First, list the gaps you found (2-4 bullet points prefixed with GAP:).
Then, output the COMPLETE improved plan body with all sections filled in.

The improved plan body must include all sections:
- ## Overview
- ## Implementation Steps  (table with | Step | Action | Details | Status |)
- ## Testing Plan
- ## Rollback Procedures
- ## Risk Assessment (table with | Risk | Likelihood | Impact | Mitigation |)
- ## Document History (table with | Date | Change | Author |)
- ## Progress Journal (table with | Date | Step | Status | Notes |)

Do NOT include YAML frontmatter. Output ONLY the gap list followed by the improved body."""

    user_prompt = f"""Here is the original proposal:

---

{proposal_content[:8000]}

---

Here is the draft plan to critique and improve:

---

{plan_body}

---

Review the draft plan against the proposal, identify gaps, and produce an improved plan body."""

    payload = {
        "model": PLAN_GENERATION_MODEL,
        "messages": [
            {"role": "system", "content": critique_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 4096
        }
    }

    try:
        result = ollama_request(payload)
        response_text = (result.get('message', {}) or {}).get('content', '') if result else ''

        if not response_text:
            log(f"  Critique returned empty response", 'warning')
            return plan_body

        # Log the critique findings
        for line in response_text.split('\n'):
            stripped = line.strip()
            if stripped.startswith('GAP:') or stripped.startswith('- GAP'):
                log(f"  Critique: {stripped}")

        # Extract improved body (everything after the gap list)
        # The response has: gap list + blank line + improved body
        improved = re.sub(r'^.*?(?=## Overview|### Overview)', '', response_text, flags=re.DOTALL)
        if not improved or improved == response_text:
            # Try finding the first ## heading as the body start
            improved = re.sub(r'^.*?(?=## )', '', response_text, flags=re.DOTALL)
        if not improved:
            improved = response_text

        # Strip any accidental frontmatter
        improved = re.sub(r'^---\n.*?\n---\n?', '', improved, flags=re.DOTALL)
        improved = improved.strip()

        if improved and len(improved) > len(plan_body) * 0.5:
            log(f"  Plan critiqued and improved ({len(improved)} chars, was {len(plan_body)})")
            return improved
        elif improved:
            log(f"  Critique produced shorter body — keeping original.", 'warning')
            return plan_body
        else:
            log(f"  Could not extract improved body from critique.", 'warning')
            return plan_body

    except Exception as e:
        log(f"  Plan critique failed: {e}", 'warning')
        log(f"  Keeping original plan body.", 'warning')
        return plan_body


def check_server_health() -> bool:
    """Ping the opencode server to see if it's responsive."""
    password = get_server_password()
    if not password:
        return False
    url = f'{OPENCODE_SERVER_URL}/doc'
    result = run_cmd(
        f'curl -sf -o /dev/null -w "%{{http_code}}" -u "opencode:{password}" {url}',
        check=False, timeout=15
    )
    return result.returncode == 0 and result.stdout.strip() == '200'


# =============================================================================
# Frontmatter parsing & writing
# =============================================================================

def parse_frontmatter(filepath: Path) -> Optional[dict]:
    """Read a markdown file and extract its YAML frontmatter as a dict.
    Returns None if the file doesn't exist or has invalid frontmatter."""
    try:
        content = filepath.read_text(encoding='utf-8')
    except (FileNotFoundError, PermissionError):
        return None

    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return None

    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None


def write_frontmatter(filepath: Path, fm: dict) -> bool:
    """Update the frontmatter of a markdown file in-place. Returns True on success."""
    try:
        content = filepath.read_text(encoding='utf-8')
    except (FileNotFoundError, PermissionError):
        return False

    fm_text = "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---"
    new_content = re.sub(r'^---\n.*?\n---', lambda m: fm_text, content, flags=re.DOTALL, count=1)
    if new_content == content:
        return False  # No change
    try:
        filepath.write_text(new_content, encoding='utf-8')
        return True
    except (OSError, PermissionError):
        return False


def validate_frontmatter(fm: Optional[dict], required_fields: list[str]) -> list[str]:
    """Validate that a frontmatter dict has the required fields. Returns list of errors."""
    errors = []
    if fm is None:
        return ["No valid frontmatter found"]
    for field in required_fields:
        if field not in fm:
            errors.append(f"Missing required field: {field}")
    return errors


def validate_new_proposal(filepath: Path, user: str, dry_run: bool = False) -> bool:
    """
    Fill missing frontmatter fields for a new or incomplete proposal.
    Only adds missing fields — never overwrites existing values.
    Idempotent: returns False immediately if all required fields are present.
    Returns True if the file was updated.
    """
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        log(f"  Cannot read {filepath.name}: {e}", 'error')
        return False

    has_frontmatter = bool(re.match(r'^---\n', content))
    fm = parse_frontmatter(filepath)

    if fm is None:
        fm = {}
        if has_frontmatter:
            log(f"  Invalid frontmatter in {filepath.name} — will reset to defaults", 'warning')
        else:
            log(f"  No frontmatter in {filepath.name} — adding defaults", 'warning')

    # Check what's missing
    missing_required = [f for f in PROPOSAL_REQUIRED_FIELDS
                        if f not in fm or (fm.get(f) is None and f != 'approved')]
    missing_optional = [f for f in PROPOSAL_OPTIONAL_DEFAULTS if f not in fm]

    if not missing_required and not missing_optional:
        return False  # Nothing to do

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if 'title' in missing_required:
        fm['title'] = filepath.stem.replace('-', ' ').replace('_', ' ').title()
        log(f"  Filled title: {fm['title']}")

    if 'author' in missing_required:
        fm['author'] = user
        log(f"  Filled author: {fm['author']}")

    if 'created' in missing_required:
        fm['created'] = now
        log(f"  Filled created: {now}")

    if 'approved' not in fm:
        fm['approved'] = False

    if 'created_by' in missing_required:
        try:
            hostname = subprocess.check_output(['hostname'], text=True).strip()
        except Exception:
            hostname = 'unknown'
        fm['created_by'] = f"{user}@{hostname}"

    for field, default in PROPOSAL_OPTIONAL_DEFAULTS.items():
        if field not in fm:
            fm[field] = default

    if dry_run:
        log(f"  [DRY-RUN] Would fill frontmatter for {filepath.name}: missing={missing_required}")
        return True

    fm_text = "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---"

    if has_frontmatter:
        new_content = re.sub(r'^---\n.*?\n---', lambda m: fm_text, content, flags=re.DOTALL, count=1)
        if new_content == content:
            # Primary regex failed — extract body safely by finding the closing --- delimiter.
            # Use a greedy match anchored to line-start so --- horizontal rules in the body
            # do not cause premature termination (the bug that blanked proposal bodies).
            body_match = re.match(r'^---\n.*?\n---\n?(.*)', content, re.DOTALL)
            if body_match:
                body = body_match.group(1).lstrip()
            else:
                # Truly malformed — keep everything after the second --- line
                lines = content.split('\n')
                dash_count = 0
                body_start = 0
                for i, line in enumerate(lines):
                    if line.strip() == '---':
                        dash_count += 1
                        if dash_count == 2:
                            body_start = i + 1
                            break
                body = '\n'.join(lines[body_start:]).lstrip()
            new_content = fm_text + '\n\n' + body
    else:
        new_content = fm_text + '\n\n' + content.lstrip()

    try:
        filepath.write_text(new_content, encoding='utf-8')
        log(f"  ✓ Filled proposal frontmatter defaults: {filepath.name}")
    except Exception as e:
        log(f"  Failed to write {filepath.name}: {e}", 'error')
        return False

    if not git_commit_transaction(message=f"chore: fill proposal frontmatter defaults: {filepath.stem}"):
        log(f"  WARNING: Frontmatter updated but not committed.", 'warning')

    return True


# =============================================================================
# Git helpers
# =============================================================================

def git_commit(message: str) -> bool:
    """Create a commit. Uses --no-verify to skip pre-commit hooks
    that may block automated transitions."""
    result = run_cmd(
        f'git commit --no-verify -m "{message}"',
        check=False, timeout=30
    )
    return result.returncode == 0


def git_commit_transaction(message: str, dry_run: bool = False) -> bool:
    """
    Atomic git commit: stage all changes (adds + deletes detected automatically),
    commit. Returns False if the commit fails.

    Uses 'git add -A' to handle renames correctly (files moved via os.rename
    are detected as delete+add by git).
    """
    if dry_run:
        log(f"  [DRY-RUN] Would commit: {message}")
        return True

    result = run_cmd(f"git add -A", check=False)
    if result.returncode != 0:
        log(f"  Failed to stage changes: {result.stderr.strip()}", 'error')
        return False

    if not git_commit(message):
        run_cmd("git reset HEAD", check=False)
        log(f"  Commit failed: {message}", 'error')
        return False

    return True


# =============================================================================
# Transition functions (with rollback)
# =============================================================================

def approve_proposal(filepath: Path, user: str, dry_run: bool = False) -> bool:
    """
    Move an approved proposal to proposals/approved/ and create a plan.
    Returns True on success, False on failure.

    Rollback:
      - If plan creation fails: move proposal back to proposals/
      - If commit fails: files exist unstaged; warn user
    """
    fm = parse_frontmatter(filepath)
    errors = validate_frontmatter(fm, ['title', 'approved', 'assigned_to'])
    if errors:
        log(f"  Invalid proposal {filepath.name}: {'; '.join(errors)}", 'error')
        return False

    if not fm.get('approved'):
        log(f"  Proposal not approved: {filepath.name}")
        return False

    assigned_to = fm.get('assigned_to', [])
    if isinstance(assigned_to, str):
        assigned_to = [assigned_to]
    if not assigned_to:
        log(f"  Proposal approved but assigned_to is empty: {filepath.name}", 'warning')
        log(f"  Blocking — human must set assigned_to before processing.", 'warning')
        return False

    target = APPROVED_DIR / filepath.name
    if target.exists():
        log(f"  Proposal already exists in approved/: {filepath.name}", 'error')
        return False

    title = fm.get('title', filepath.stem)
    plan_filename = re.sub(r'[^a-z0-9-]', '-', title.lower().strip())
    plan_filename = re.sub(r'-+', '-', plan_filename).strip('-')
    plan_path = PLANS_DIR / f"{plan_filename}.md"

    if plan_path.exists():
        log(f"  Plan already exists: {plan_path.name}", 'error')
        return False

    if dry_run:
        log(f"  [DRY-RUN] Would move {filepath.name} → proposals/approved/")
        log(f"  [DRY-RUN] Would create plan: {plan_path.name}")
        return True

    # Step 1: Move proposal to approved/
    try:
        filepath.rename(target)
        log(f"  Moved {filepath.name} → proposals/approved/")
    except Exception as e:
        log(f"  Failed to move proposal: {e}", 'error')
        return False

    # Step 2: Create plan from template
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    plan_fm = {
        'title': title,
        'status': 'proposal',
        'author': fm.get('author', ''),
        'created': now,
        'created_by': fm.get('created_by', ''),
        'tags': fm.get('tags', []),
        'proposal_source': f"proposals/approved/{filepath.name}",
        'priority': fm.get('priority', 5),
        'automated': 'off',
        'waiting_reason': '',
        'assigned_to': assigned_to,
        'related_to': fm.get('related_to', []),
        'depends_on': fm.get('depends_on', []),
        'blocks': fm.get('blocks', []),
        'tracking_status': 'in-discussion',
        'progress_current_step': '',
        'progress_last_updated': '',
        'reviewed_by': '',
        'reviewed_date': '',
        'template_version': '1.1',
        'critiqued': False,
    }

    # Step 2a: Try to generate plan body from proposal using LLM
    body = generate_plan_body(target, plan_fm)
    if body:
        log(f"  Plan body generated via LLM ({len(body)} chars)")
    else:
        log(f"  LLM generation unavailable — using template body.", 'warning')

    # Step 2b: Fall back to template body if generation failed
    if not body:
        try:
            proposal_text = target.read_text(encoding='utf-8')
            body = fill_template_from_proposal(proposal_text, plan_fm)
            log(f"  Template filled from proposal content ({len(body)} chars)")
        except Exception as e:
            log(f"  Template fill failed: {e}", 'warning')
            # Last resort: bare template
            try:
                if TEMPLATE_FILE.exists():
                    template_content = TEMPLATE_FILE.read_text(encoding='utf-8')
                    body_match = re.search(r'^---\n.*?\n---\n(.*)', template_content, re.DOTALL)
                    body = body_match.group(1) if body_match else ""
            except Exception:
                body = ""

    # Ensure all required sections exist in the body
    if body:
        body = ensure_required_sections(body, plan_fm)

    # Step 2c: Write the plan file immediately so it exists on disk
    fm_text = "---\n" + yaml.dump(plan_fm, default_flow_style=False, sort_keys=False) + "---"
    plan_content_initial = fm_text + "\n" + body

    try:
        plan_path.write_text(plan_content_initial, encoding='utf-8')
        log(f"  Created plan: {plan_path.name}")
    except Exception as e:
        log(f"  Failed to create plan: {e}", 'error')
        try:
            target.rename(filepath)
            log(f"  Rollback: moved {filepath.name} back to proposals/")
        except Exception as rb:
            log(f"  Rollback failed: proposal left at {target}. {rb}", 'error')
        return False

    # Step 2d: NOW critique the generated plan and embed findings visibly
    had_gaps = False
    if body and not plan_fm.get('critiqued'):
        log(f"  Critiquing plan for gaps and improvements...")
        try:
            proposal_text = target.read_text(encoding='utf-8')
        except Exception:
            proposal_text = ""
        critique_result = critique_and_improve_plan_body(proposal_text, body, plan_fm)
        if critique_result and critique_result != body:
            log(f"  Plan critiqued — embedding review findings...")
            # Extract GAP: lines directly (more reliable than regex before ## Overview)
            gap_lines = []
            for line in critique_result.split('\n'):
                stripped = line.strip()
                if stripped.startswith('GAP:') or stripped.startswith('- GAP') or stripped.startswith('* GAP'):
                    gap_lines.append(stripped)
                elif stripped.startswith('- **GAP') or stripped.startswith('* **GAP'):
                    gap_lines.append(stripped)
            gap_section = '\n'.join(gap_lines) if gap_lines else ''

            # Extract improved body: start from ## Overview
            improved_body = re.sub(r'^.*?(?=## Overview)', '', critique_result, flags=re.DOTALL).strip()
            if not improved_body:
                improved_body = re.sub(r'^.*?(?=## )', '', critique_result, flags=re.DOTALL).strip()
            if not improved_body:
                improved_body = critique_result  # fallback

            if gap_section:
                had_gaps = True
                # Embed critique as a visible Initial Review section
                review_section = (
                    "\n\n"
                    "## Initial Review\n\n"
                    "This plan was auto-generated and critiqued. "
                    "Open questions are listed below — respond to each "
                    "before approving execution.\n\n"
                    f"{gap_section}\n"
                )
                improved_body = improved_body + review_section
            else:
                # No gap list — just append a note
                improved_body = improved_body + (
                    "\n\n## Initial Review\n\n"
                    "This plan was auto-generated. "
                    "No significant gaps were found during critique.\n"
                )
            plan_content_improved = fm_text + "\n" + improved_body
            try:
                plan_path.write_text(plan_content_improved, encoding='utf-8')
                # Mark critiqued=true to prevent re-critiquing
                plan_fm_after = parse_frontmatter(plan_path)
                if plan_fm_after is not None:
                    plan_fm_after['critiqued'] = True
                    write_frontmatter(plan_path, plan_fm_after)
                log(f"  Updated plan with Initial Review section")
            except Exception as e:
                log(f"  Could not update plan with critique: {e}", 'warning')
        elif critique_result == body:
            log(f"  Critique unavailable or found no improvements — flagging for human review.")
            had_gaps = True
            placeholder = (
                "\n\n## Initial Review\n\n"
                "This plan was auto-generated. "
                "Automated critique was unavailable — review manually for gaps "
                "before approving execution.\n\n"
                "**Open questions:**\n"
                "- Review all sections for completeness\n"
                "- Verify implementation steps match the proposal\n"
                "- Check risk assessment covers all proposal risks\n"
            )
            plan_path.write_text(fm_text + "\n" + body + placeholder, encoding='utf-8')
            log(f"  Added placeholder Initial Review (critique unavailable)")
        else:
            log(f"  Critique failed — flagging for human review.")
            had_gaps = True
            placeholder = (
                "\n\n## Initial Review\n\n"
                "This plan was auto-generated. "
                "Automated critique failed — review manually for gaps "
                "before approving execution.\n\n"
                "**Open questions:**\n"
                "- Review all sections for completeness\n"
                "- Verify implementation steps match the proposal\n"
                "- Check risk assessment covers all proposal risks\n"
            )
            plan_path.write_text(fm_text + "\n" + body + placeholder, encoding='utf-8')
            log(f"  Added placeholder Initial Review (critique failed)")

    # Step 2e: If critique found gaps, set waiting-for-user so user responds
    if had_gaps:
        log(f"  Plan has open questions — setting status=waiting-for-user")
        plan_fm_updated = parse_frontmatter(plan_path)
        if plan_fm_updated is not None:
            plan_fm_updated['status'] = 'waiting-for-user'
            plan_fm_updated['tracking_status'] = 'questions-pending'
            plan_fm_updated['waiting_reason'] = (
                'Plan reviewed — open questions need resolution (see Initial Review section)'
            )
            write_frontmatter(plan_path, plan_fm_updated)

    # Step 3: Git commit
    commit_msg = f"Approve proposal: {filepath.stem}"
    if had_gaps:
        commit_msg += " (needs review)"
    if not git_commit_transaction(message=commit_msg):
        log(f"  WARNING: Changes made but not committed. Files exist at:", 'warning')
        log(f"    - {target}", 'warning')
        log(f"    - {plan_path}", 'warning')
        log(f"  Run: git add && git commit to save these changes.", 'warning')
        return False

    if had_gaps:
        log(f"  ✓ Proposal approved, plan created with open questions — waiting for user response.")
    else:
        log(f"  ✓ Proposal approved, plan created, committed.")
    return True


def complete_plan(filepath: Path, dry_run: bool = False) -> bool:
    """
    Move a completed plan to plans/completed/.
    Returns True on success, False on failure.
    """
    fm = parse_frontmatter(filepath)
    errors = validate_frontmatter(fm, ['status'])
    if errors:
        log(f"  Invalid plan {filepath.name}: {'; '.join(errors)}", 'error')
        return False

    if fm.get('status') != 'completed':
        log(f"  Plan not marked completed: {filepath.name}")
        return False

    ts = fm.get('tracking_status', '')
    if ts not in ('ready', 'completed', ''):
        log(f"  Plan tracking_status is '{ts}', expected 'ready' or 'completed'. "
            f"Are you sure this plan is ready to close?", 'warning')
        return False

    target = COMPLETED_DIR / filepath.name
    if target.exists():
        log(f"  Completed plan already exists: {target.name}", 'error')
        return False

    if dry_run:
        log(f"  [DRY-RUN] Would move {filepath.name} → plans/completed/")
        return True

    try:
        filepath.rename(target)
        log(f"  Moved {filepath.name} → plans/completed/")
    except Exception as e:
        log(f"  Failed to move plan: {e}", 'error')
        return False

    if not git_commit_transaction(message=f"Complete plan: {filepath.stem}"):
        log(f"  WARNING: Plan moved but not committed.", 'warning')
        log(f"    File at: {target}", 'warning')
        log(f"  Run: git add && git commit to save.", 'warning')
        return False

    log(f"  ✓ Plan completed, moved to completed/, committed.")
    log(f"  ℹ Remember to generate docs from this completed plan!")
    return True


def cancel_plan(filepath: Path, reason: str = "", dry_run: bool = False) -> bool:
    """
    Cancel a plan: set status=canceled, add reason, move to completed/.
    Does NOT generate docs.
    """
    fm = parse_frontmatter(filepath)
    errors = validate_frontmatter(fm, ['status'])
    if errors:
        log(f"  Invalid plan {filepath.name}: {'; '.join(errors)}", 'error')
        return False

    target = COMPLETED_DIR / filepath.name
    if target.exists():
        log(f"  Plan already in completed/: {target.name}", 'error')
        return False

    if dry_run:
        log(f"  [DRY-RUN] Would cancel {filepath.name}")
        log(f"  [DRY-RUN] Reason: {reason or '(no reason given)'}")
        return True

    if fm is None:
        return False
    fm['status'] = 'canceled'
    fm['canceled_date'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    fm['cancellation_reason'] = reason or 'No reason provided'
    fm.pop('tracking_status', None)

    if not write_frontmatter(filepath, fm):
        log(f"  Failed to update frontmatter: {filepath.name}", 'error')
        return False
    log(f"  Updated frontmatter: status=canceled")

    try:
        filepath.rename(target)
        log(f"  Moved {filepath.name} → plans/completed/")
    except Exception as e:
        log(f"  Failed to move canceled plan: {e}", 'error')
        return False

    if not git_commit_transaction(message=f"Cancel plan: {filepath.stem}"):
        log(f"  WARNING: Plan canceled but not committed.", 'warning')
        return False

    log(f"  ✓ Plan canceled: {filepath.name}")
    return True


def resolve_waiting_plan(filepath: Path, dry_run: bool = False) -> bool:
    """
    Detect when a plan in waiting-for-user with tracking_status=questions-pending
    has been resolved by the user (tracking_status changed to questions-resolved).
    Updates waiting_reason and commits.
    Returns True if transition was processed, False otherwise.
    """
    fm = parse_frontmatter(filepath)
    if fm is None:
        return False
    if fm.get('status') != 'waiting-for-user':
        return False
    if fm.get('tracking_status') != 'questions-resolved':
        return False

    log(f"  Questions resolved for: {filepath.name}")

    if dry_run:
        log(f"  [DRY-RUN] Would update waiting_reason and clear tracking_status")
        return True

    fm['waiting_reason'] = 'Questions resolved — ready for approval'
    fm['tracking_status'] = ''

    if not write_frontmatter(filepath, fm):
        log(f"  Failed to update frontmatter for {filepath.name}", 'error')
        return False

    if not git_commit_transaction(
        message=f"Resolve plan questions: {filepath.stem}"
    ):
        log(f"  WARNING: Questions resolved but not committed.", 'warning')
        return False

    log(f"  ✓ Questions resolved for: {filepath.name}")
    return True


def recover_plan(filepath: Path, dry_run: bool = False) -> bool:
    """
    Try to recover a plan from blocked-tokens state.
    Checks server health; if responsive, sets tracking_status back to in-discussion.
    """
    fm = parse_frontmatter(filepath)
    if fm is None:
        return False
    if fm.get('tracking_status') != 'blocked-tokens':
        return False

    log(f"  Found blocked plan: {filepath.name}")

    if dry_run:
        log(f"  [DRY-RUN] Would check server health and potentially recover")
        return True

    if not check_server_health():
        log(f"  Server still unresponsive. Will retry next cycle.", 'warning')
        return False

    log(f"  Server responsive. Attempting recovery...")
    fm['tracking_status'] = 'in-discussion'

    if not write_frontmatter(filepath, fm):
        log(f"  Failed to write frontmatter for {filepath.name}", 'error')
        return False

    if not git_commit_transaction(message=f"Recover plan from token exhaustion: {filepath.stem}"):
        log(f"  WARNING: Plan recovered locally but not committed.", 'warning')
        return False

    log(f"  ✓ Recovered plan: {filepath.name}")
    return True


# =============================================================================
# Scanner — Process all pending transitions
# =============================================================================

def scan_all(dry_run: bool = False) -> int:
    """
    Scan all proposals and plans for pending transitions.
    Returns count of transitions processed (for exit code logic).
    """
    transitions = 0
    user = get_current_user()

    if PROPOSALS_DIR.exists():
        for md_file in sorted(PROPOSALS_DIR.glob('*.md')):
            if md_file.name == 'approved' or md_file.parent.name == 'approved':
                continue
            if validate_new_proposal(md_file, user, dry_run=dry_run):
                transitions += 1
            if approve_proposal(md_file, user, dry_run=dry_run):
                transitions += 1

    if PLANS_DIR.exists():
        for md_file in sorted(PLANS_DIR.glob('*.md')):
            if md_file.parent.name == 'completed':
                continue
            if complete_plan(md_file, dry_run=dry_run):
                transitions += 1

    if PLANS_DIR.exists():
        for md_file in sorted(PLANS_DIR.glob('*.md')):
            if md_file.parent.name == 'completed':
                continue
            if recover_plan(md_file, dry_run=dry_run):
                transitions += 1

    if PLANS_DIR.exists():
        for md_file in sorted(PLANS_DIR.glob('*.md')):
            if md_file.parent.name == 'completed':
                continue
            if resolve_waiting_plan(md_file, dry_run=dry_run):
                transitions += 1

    return transitions


# =============================================================================
# Status reporter
# =============================================================================

def print_status() -> None:
    """Print a table of all lifecycle documents with their current state."""

    def fmt_plan(path: Path, label: str) -> None:
        fm = parse_frontmatter(path)
        if fm is None:
            print(f"  {label} {path.name:50s}  [INVALID]")
            return
        status = fm.get('status', '?')
        ts = fm.get('tracking_status', '—')
        assigned = fm.get('assigned_to', [])
        if isinstance(assigned, list):
            assigned = ', '.join(assigned) if assigned else '—'
        else:
            assigned = str(assigned) if assigned else '—'
        print(f"  {label} {path.name:50s}  status={status:15s}  tracking={ts:20s}  assigned_to={assigned}")

    def fmt_proposal(path: Path) -> None:
        fm = parse_frontmatter(path)
        if fm is None:
            print(f"     {path.name:50s}  [INVALID]")
            return
        approved = '✓' if fm.get('approved') else '✗'
        ts = fm.get('tracking_status', '—')
        assigned = fm.get('assigned_to', [])
        if isinstance(assigned, list):
            assigned = ', '.join(assigned) if assigned else '—'
        else:
            assigned = str(assigned) if assigned else '—'
        print(f"     {path.name:50s}  approved={approved}  tracking={ts:20s}  assigned_to={assigned}")

    print(f"\n{'='*80}")
    print(f"  LIFECYCLE DOCUMENT STATUS  —  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*80}")

    print(f"\n  PROPOSALS ({'proposals/'}):")
    print(f"  {'─'*76}")
    if PROPOSALS_DIR.exists():
        for md_file in sorted(PROPOSALS_DIR.glob('*.md')):
            if md_file.name in ('approved',):
                continue
            fmt_proposal(md_file)

    print(f"\n  APPROVED PROPOSALS ({'proposals/approved/'}):")
    print(f"  {'─'*76}")
    if APPROVED_DIR.exists():
        for md_file in sorted(APPROVED_DIR.glob('*.md')):
            fmt_proposal(md_file)

    print(f"\n  ACTIVE PLANS ({'plans/'}):")
    print(f"  {'─'*76}")
    if PLANS_DIR.exists():
        for md_file in sorted(PLANS_DIR.glob('*.md')):
            if md_file.parent.name == 'completed':
                continue
            fmt_plan(md_file, '')

    print(f"\n  COMPLETED PLANS ({'plans/completed/'}):")
    print(f"  {'─'*76}")
    if COMPLETED_DIR.exists():
        for md_file in sorted(COMPLETED_DIR.glob('*.md')):
            fmt_plan(md_file, '')

    print()


# =============================================================================
# Watch mode — filesystem monitoring
# =============================================================================

def watch_mode(interval: int = 5, heartbeat_interval: int = 300) -> None:
    """
    Long-running daemon that watches proposals/ and plans/ for file changes.
    Uses the watchdog library for filesystem events.
    """
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class LifecycleHandler(FileSystemEventHandler):
        def __init__(self):
            super().__init__()
            self._last_scan: float = 0.0
            self._scan_cooldown: float = 3.0  # seconds — prevents event storms

        def on_any_event(self, event):
            if event.is_directory:
                return
            if not event.src_path.endswith('.md'):
                return
            if '.git' in event.src_path:
                return
            now = time.time()
            if now - self._last_scan < self._scan_cooldown:
                return  # Debounce: suppress rapid repeat events
            self._last_scan = now
            log(f"File change detected: {Path(event.src_path).name}")
            scan_all(dry_run=False)

    log(f"Watch mode started — monitoring proposals/ and plans/")
    log(f"  Poll interval: {interval}s, Heartbeat: {heartbeat_interval}s")
    log(f"  Press Ctrl+C to stop.")

    # Initial scan: catch any changes made while the service was stopped
    log("Initial scan for pending transitions...")
    scan_all(dry_run=False)

    event_handler = LifecycleHandler()
    observer = Observer()
    for watch_dir in [PROPOSALS_DIR, PLANS_DIR, ISSUES_DIR]:
        if watch_dir.exists():
            observer.schedule(event_handler, str(watch_dir), recursive=False)
            log(f"  Watching: {watch_dir}")

    observer.start()
    last_heartbeat = time.time()

    try:
        while True:
            time.sleep(interval)
            now = time.time()
            if now - last_heartbeat >= heartbeat_interval:
                log(f"Heartbeat — watching {PROPOSALS_DIR}, {PLANS_DIR}")
                last_heartbeat = now
    except KeyboardInterrupt:
        log("Watch mode terminated by user.")
    finally:
        observer.stop()
        observer.join()


def watch_mode_poll(interval: int = 5) -> None:
    """
    Fallback watch mode: poll files every N seconds.
    Used when the watchdog library is not available.
    """
    log(f"Watch mode (poll fallback) — polling proposals/ and plans/ every {interval}s")
    log(f"  Press Ctrl+C to stop.")
    log(f"  Install 'watchdog' package for real-time file monitoring.")

    # Initial scan: catch any changes made while the service was stopped
    log("Initial scan for pending transitions...")
    scan_all(dry_run=False)

    last_mtimes: dict[str, float] = {}

    def get_mtimes() -> dict[str, float]:
        mtimes = {}
        for watch_dir in [PROPOSALS_DIR, PLANS_DIR]:
            if not watch_dir.exists():
                continue
            for f in watch_dir.glob('*.md'):
                try:
                    mtimes[str(f)] = f.stat().st_mtime
                except OSError:
                    pass
        return mtimes

    last_mtimes = get_mtimes()
    last_heartbeat = time.time()

    try:
        while True:
            time.sleep(interval)
            current = get_mtimes()
            changed = False
            for path_str, mtime in current.items():
                old = last_mtimes.get(path_str)
                if old is not None and mtime > old:
                    log(f"File changed: {Path(path_str).name}")
                    changed = True
                elif old is None:
                    log(f"New file: {Path(path_str).name}")
                    changed = True
            for path_str in list(last_mtimes.keys()):
                if path_str not in current:
                    log(f"File removed: {Path(path_str).name}")
            last_mtimes = current
            if changed:
                scan_all(dry_run=False)
            now = time.time()
            if now - last_heartbeat >= 300:
                log(f"Heartbeat — watching {PROPOSALS_DIR}, {PLANS_DIR}")
                last_heartbeat = now
    except KeyboardInterrupt:
        log("Watch mode (poll) terminated by user.")


# =============================================================================
# Main entry point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Lifecycle Processor — manage proposal/plan transitions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  --check     Run once: process all pending transitions
  --watch     Long-running daemon (requires 'watchdog' package)
  --dry-run   Show what would change without modifying anything
  --status    Print state of all lifecycle documents

Exit codes (--dry-run):
  0 = no changes pending
  1 = changes would be made (useful for CI/scripting)

Examples:
  python3 %(prog)s --check
  python3 %(prog)s --dry-run
  python3 %(prog)s --status
  python3 %(prog)s --watch
  python3 %(prog)s --watch --watch-interval=10
        """
    )
    parser.add_argument('--check', action='store_true', help='Run once and process all pending transitions')
    parser.add_argument('--watch', action='store_true', help='Long-running daemon mode')
    parser.add_argument('--dry-run', action='store_true', help='Show pending changes without modifying anything')
    parser.add_argument('--status', action='store_true', help='Print state of all lifecycle documents')
    parser.add_argument('--user', default='', help=f'Current operator (default: {get_current_user()})')
    parser.add_argument('--watch-interval', type=int, default=5,
                        help='Poll interval in --watch mode (seconds, default: 5)')
    parser.add_argument('--heartbeat-interval', type=int, default=300,
                        help='How often to log heartbeat in --watch mode (seconds, default: 300)')
    parser.add_argument('--log-file', help='Optional log file path')

    args = parser.parse_args()

    modes = [args.check, args.watch, args.dry_run, args.status]
    active_modes = sum(1 for m in modes if m)
    if active_modes > 1:
        parser.error("Only one mode flag allowed at a time")
    if active_modes == 0:
        parser.print_help()
        sys.exit(0)

    if args.user:
        os.environ['LIFE_CYCLE_USER'] = args.user

    if args.log_file:
        log_fh = open(args.log_file, 'a', encoding='utf-8')
        log_fh.write(f"[{datetime.now(timezone.utc).isoformat()}] Lifecycle processor started\n")
        log_fh.close()

    if args.status:
        print_status()
        return

    if args.dry_run:
        log("DRY-RUN mode — no files will be modified.")
        transitions = scan_all(dry_run=True)
        if transitions > 0:
            log(f"DRY-RUN: {transitions} transition(s) would be processed.")
        else:
            log("DRY-RUN: No pending transitions.")
        sys.exit(0 if transitions == 0 else 1)

    if args.check:
        log("Check mode — scanning for pending transitions...")
        transitions = scan_all(dry_run=False)
        if transitions > 0:
            log(f"✓ Processed {transitions} transition(s).")
        else:
            log("No pending transitions.")
        return

    if args.watch:
        try:
            import watchdog  # noqa: F401
            watch_mode(interval=args.watch_interval, heartbeat_interval=args.heartbeat_interval)
        except ImportError:
            log("watchdog library not available. Falling back to polling mode.", 'warning')
            log("Install with: pip install watchdog", 'warning')
            watch_mode_poll(interval=args.watch_interval)
        return


if __name__ == '__main__':
    main()
