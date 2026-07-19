# Rule: Model Tiers and Project Capabilities

## Overview

Models operating in this project carry different capabilities and should apply
different constraints. Tier is determined by model identity, parameter count,
and verified tool-use capability.

**If you do not know your own tier, assume T3 (restricted) and tell the
operator before taking any action beyond reading and querying.**

---

## Tier Definitions

### T1 — Frontier Cloud (Full Capabilities)

**Models:** `claude-sonnet-4-6`, `claude-haiku-4-5`, `big-pickle`, `claude-opus-*`, `gpt-4*`, `gemini-2.5*`
**Context:** 128K–200K | **Tool use:** ✅ Proven

Full project capabilities — no additional restrictions beyond the base rules.
Apply the 3-strike escalation rule before digging deeper on any problem.

---

### T2 — Capable Local (Full Lifecycle, Extra Caution)

**Models:** `mistral-small3.2:24b`, `qwen2.5:14b`, `qwen2.5-coder:14b`, `qwen3.5:27b`, `llama3.3:*`
**Context:** 32K–131K | **Tool use:** ✅ Proven (mistral) or likely (others)

Full lifecycle access, with mandatory extra gates:
- **Always** run `lifecycle-processor.py --dry-run` before any lifecycle transition
- **Always** explain reasoning before writing files or running bash
- **Always** flag decisions with more than one valid path — present options, don't pick
- Prefer proposing over executing when uncertain
- Context is limited: be concise, read only what you need

Cannot do (same as all tiers):
- Set `approved: true` on proposals
- Skip dry-run gate before infra operations
- Make irreversible infrastructure changes without explicit human confirmation

---

### T3 — Small Local (Draft and Query Only)

**Models:** `llama3.1:8b`, `llama3:8b`, `qwen2.5:7b`, `qwen2.5-coder:7b`, `deepseek-r1:14b`, `gemma3:12b`, `nemotron-3-nano:4b`
**Context:** 4K–32K | **Tool use:** ⚠ Unreliable or ❌ None

> ⚠️ `deepseek-r1` and `gemma3` have **no tool support** — they cannot call bash,
> read files via tools, or edit files. They are text-only. Do not use them for
> interactive project sessions.

Restricted to:
- Querying project state: `lifecycle-processor.py --status` or `--dry-run` (read-only)
- Drafting raw text for new issues in `issues/` (no frontmatter, just notes)
- Reading and explaining project documentation
- Answering questions based on docs already in context

**Cannot do:**
- Write to `proposals/`, `plans/`, or `docs/` directly
- Run Ansible playbooks or any infrastructure command
- Commit to git
- Execute lifecycle transitions

If asked to do any of the above, respond:
> "This task requires a T1 or T2 model. I'm operating in T3 (draft/query) mode.
> Please switch to `cluster-ollama/mistral-small3.2:24b` or a cloud model to proceed."

---

### T4 — Utility (No Direct Project Interaction)

**Models:** `qwen2.5:1.5b`, `nomic-embed-text`, `qwen2.5-coder:7b` (autocomplete only)

Used for: query classification, embeddings, inline autocomplete.
Never invoked for project-interactive sessions.

---

## Smart Router (`cluster-smart-router/auto`) Warning

`cluster-smart-router/auto` is the default OpenCode model. It classifies queries
and routes to the best local model — which may be a T3 model (e.g., `gemma3:12b`
for "longform" tasks, `deepseek-r1:14b` for "reasoning" tasks).

**For any session that involves tool use, file edits, or lifecycle operations:**
- ❌ Do NOT use `cluster-smart-router/auto`
- ✅ Use `cluster-ollama/mistral-small3.2:24b` (only verified local tool model)
- ✅ Use `cluster-litellm/claude-sonnet-4-6` (cloud fallback)

The router is appropriate for: general questions, documentation lookups,
summarization, and read-only queries where tool calling is not needed.

---

## OpenCode Agent Modes

Select the mode matching your model tier when starting a session:

| Mode | Use when running | Permissions |
|------|-----------------|-------------|
| *(default)* | T1 frontier models | `edit/write/bash: ask` |
| `local-capable` | T2 capable local models | `edit: allow`, `write/bash: ask` + dry-run enforced |
| `local-small` | T3 small local models | `read: allow`, all writes/bash: `deny` |

---

## Routing Reference Table

| Model | Tier | Tool Use | Project Role |
|-------|------|----------|--------------|
| `claude-sonnet-4-6` | T1 | ✅ | Full capabilities |
| `claude-haiku-4-5` | T1 | ✅ | Full capabilities |
| `big-pickle` | T1 | ✅ | Full capabilities |
| `mistral-small3.2:24b` | T2 | ✅ Verified | Full lifecycle + extra gates |
| `qwen2.5:14b` | T2 | ✅ Likely | Full lifecycle + extra gates |
| `qwen2.5-coder:14b` | T2 | ✅ Likely | Full lifecycle + extra gates |
| `qwen3.5:27b` | T2 | ⚠ Unproven | Extra gates; test before trusting |
| `llama3.1:8b` | T3 | ⚠ Limited | Draft + query only |
| `qwen2.5:7b` | T3 | ⚠ Limited | Draft + query only |
| `qwen2.5-coder:7b` | T3/T4 | ⚠ | Autocomplete; project queries only |
| `deepseek-r1:14b` | T3 | ❌ None | Text-only; read + explain only |
| `gemma3:12b` | T3 | ❌ None | Text-only; read + explain only |
| `nemotron-3-nano:4b` | T4 | — | Autocomplete only |
| `qwen2.5:1.5b` | T4 | — | Router classifier only |
| `nomic-embed-text` | T4 | — | Embeddings only |
