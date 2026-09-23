---
name: websearch
description: "Search and fetch the web through the locally installed donsetch CLI (keyless multi-engine search + Markdown page fetch) instead of a persistent MCP server — no runtime pays a tool-schema cost for this. Use for: web search, websearch, research, fetch url, donsetch"
mode: skill
triggers: websearch,web search,research,fetch url,donsetch,search the web
---

# websearch

> No runtime registers a web-search MCP server. `donsetch` (npm-installed,
> keyless multi-engine search + Markdown fetch, built-in cache) is a plain
> CLI — shell out to it directly. This replaced `hound-mcp`/`master-fetch`
> (2026-09-23): same idea, actively maintained Rust rewrite, no MCP schema
> cost in any session.

## Quick Reference

| Need | Command |
|---|---|
| Search the web | `donsetch search "<query>" --max-results 7` |
| Search a vertical | `donsetch search "<query>" --intent code\|paper\|news\|entity\|web` |
| Fetch a page as Markdown | `donsetch fetch <url> --focus "<what you're looking for>"` |
| Fetch a search result directly | `donsetch fetch @<handle>` (handle comes from a `search` result) |
| Read structure before committing tokens | `donsetch fetch <url> --toc`, then `--section "<heading>"` |
| Bulk fetch (up to 12 URLs, one call) | `donsetch fetch <url1> <url2> ... --budget-tokens 20000` |
| Verify a claim without loading the page | `donsetch fetch <url> --must-contain "<string or /regex/>"` |
| Re-check a page you already read | `donsetch fetch <url> --since-last` |
| Dead page | `donsetch fetch <url> --archive auto` (Wayback fallback) |
| Health check | `donsetch doctor` |

## Steps

1. **Search first, fetch second.** `donsetch search "<query>"` returns ranked
   results with short handles (e.g. `@10hd73d`) — `donsetch fetch @<handle>`
   pulls one directly without re-typing the URL.
2. **Always set `--focus`** when you know what you're after — it cuts
   fetched tokens 50-80% by returning only the relevant blocks, with a
   full-page fallback if nothing scores. This is the single biggest lever
   for keeping fetch calls cheap.
3. **Use `--toc` / `--section` on long docs** instead of fetching the whole
   page — read the outline, then pull just the section that matters.
4. Report findings to the operator with the source URL; `--must-contain` is
   for verification questions (does X appear on this page), not for reading
   content — use `fetch` normally when you need the actual text.

## Failure handling

- No results / low-quality results: retry with `--query-variant` (up to 2
  alternate phrasings) rather than repeating the same query — useful for
  ambiguous, multilingual, or hard-to-recall searches.
- A fetch hits a bot-wall or JS-shell: leave `--tier auto` (default) — it
  escalates to a headless browser automatically. Only override `--tier` for
  testing.
- Command not found / looks broken: `donsetch doctor` diagnoses the install
  and suggests fixes; `donsetch -u` updates to the latest release.
- Rate-limited or slow engine: results still return (consensus ranking
  degrades gracefully); don't retry in a loop — reformulate the query
  instead.

## Related

- `mcp/external-servers.json` — does not list `donsetch`; it is intentionally
  not vault-launched or MCP-registered, since it needs no secrets and every
  runtime already has shell access
- opskit MCP-server critique (2026-09-22 session): why `hound-mcp` was
  replaced and why this stayed a CLI-backed skill instead of becoming an MCP
  entry
