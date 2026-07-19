# Rule: Model Tiers and Project Capabilities

## Tier Definitions

### T1 — Frontier Cloud (Full Capabilities)
**Models:** `claude-sonnet-4-6`, `claude-haiku-4-5`, `big-pickle`, `claude-opus-*`, `gpt-4*`, `gemini-2.5*`
Full project capabilities — no additional restrictions beyond base rules.

### T2 — Capable Local (Full Lifecycle, Extra Caution)
**Models:** `mistral-small3.2:24b`, `qwen2.5:14b`, `qwen2.5-coder:14b`, `qwen3.5:27b`
Full lifecycle access, with mandatory extra gates:
- **Always** run `lifecycle-processor.py --dry-run` before any lifecycle transition
- **Always** explain reasoning before writing files or running bash
- Prefer proposing over executing when uncertain

### T3 — Small Local (Draft and Query Only)
**Models:** `llama3.1:8b`, `qwen2.5:7b`, `deepseek-r1:14b`, `gemma3:12b`
Restricted to: querying state, drafting raw text, reading documentation.
Cannot: write proposals/plans, run infra commands, commit, execute transitions.

### T4 — Utility (No Direct Project Interaction)
**Models:** `qwen2.5:1.5b`, `nomic-embed-text`
Used for: query classification, embeddings, autocomplete.

## Routing Reference

| Model | Tier | Tool Use | Project Role |
|-------|------|----------|--------------|
| `claude-sonnet-4-6`, `big-pickle` | T1 | Verified | Full capabilities |
| `mistral-small3.2:24b` | T2 | Verified | Full lifecycle + extra gates |
| `qwen2.5:14b`, `qwen2.5-coder:14b` | T2 | Likely | Full lifecycle + extra gates |
| `qwen3.5:27b` | T2 | Unproven | Extra gates; test before trusting |
| `llama3.1:8b`, `qwen2.5:7b` | T3 | Limited | Draft + query only |
| `deepseek-r1:14b`, `gemma3:12b` | T3 | None | Text-only; read + explain only |
| `qwen2.5:1.5b`, `nomic-embed-text` | T4 | — | Utility only |

If you do not know your own tier, assume T3 (restricted) and tell the operator before taking any write action.
