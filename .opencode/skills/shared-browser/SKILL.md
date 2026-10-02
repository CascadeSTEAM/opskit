---
name: shared-browser
description: "Open a visible browser on the operator's desktop that operator and agent use together, for admin consoles that need a human login; the agent reads read-only through a loopback debugging port"
mode: skill
triggers: shared browser,collaborative browser,admin console,remote debugging,cdp,open a browser,playwright attach,login together
---

# Shared Browser

<!-- Scaffolded by bin/automation-ladder.py. Replace the placeholder
     steps but KEEP step 0: it is how the automation ladder measures
     whether this skill deserves a codified script/tool. -->

## Steps

0. **Usage tracking (always, before anything else):**

   ```bash
   python3 bin/automation-ladder.py tick --skill shared-browser
   ```

   If the output has `"offer_upgrade": true`, tell the operator this
   skill has crossed the usage threshold and offer to codify it. Target
   selection (IaC rule): if this skill changes the state of ANY system —
   remote host or the local workstation — the codified form is an
   **Ansible playbook/role** in `ansible/`; a plain script only for
   repo/dev workflow. Offer an MCP tool under `mcp/` if a
   playbook/script already backs it. If they decline permanently, run
   `python3 bin/automation-ladder.py mute --skill shared-browser`
   so they are never asked again.

1. **Check the preconditions**: a desktop session (`echo $DISPLAY $WAYLAND_DISPLAY`), real
   Google Chrome (`google-chrome --version`), port 9222 free (`ss -ltn | grep 9222`), and
   Playwright in a SCRATCH virtualenv for attaching (`python3 -m venv <scratch>/pw &&
   <scratch>/pw/bin/pip install -q playwright`; attaching needs no browser download).
2. **Launch a visible Chrome with its OWN empty profile and a loopback debugging port**
   (never the operator's everyday profile):

   ```bash
   mkdir -p ~/.cache/shared-browser
   nohup google-chrome --user-data-dir="$HOME/.cache/shared-browser" \
     --remote-debugging-port=9222 --no-first-run --no-default-browser-check \
     "<start url>" >/dev/null 2>&1 & disown
   curl -s http://127.0.0.1:9222/json/version     # up?   ss -ltn | grep 9222   # 127.0.0.1 only?
   ```

   Launch it normally and attach afterwards. A browser started BY automation is refused by
   Google sign-in ("this browser may not be secure"); one started by hand and attached to is not.
3. **Hand over and state the ground rules out loud.** The operator signs in themselves,
   including 2FA; you never type, read or store credentials. You read only the page you
   named; you click nothing in their admin console unless they ask; no cookies or storage
   are exported. Whatever is visible in that window you could read, so stay on the task.
4. **Attach and read**, read-only:

   ```python
   from playwright.sync_api import sync_playwright
   with sync_playwright() as p:
       b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
       page = [pg for c in b.contexts for pg in c.pages if "<host>" in pg.url][0]
       print(page.inner_text("body"))     # b.close() only detaches; the window stays open
   ```

   Take values that will be copied (a DKIM key, an address) from the page TEXT or DOM, never
   from a screenshot. Check which tenant, domain or account is selected before trusting a
   value. Use a NEW tab for third-party sites so the console tab is left as it was.
5. **The human does the mutating clicks** ("Start authentication", "Save"); you re-read the
   page to confirm the result and report it.
6. **Wrap up**: ask whether to close it. Close with `pkill -f 'remote-debugging-port=9222'`
   and delete the profile (`rm -rf ~/.cache/shared-browser`); that also signs the operator
   out. Never leave the debugging port open between sessions.

## Failure handling

- Port 9222 busy: another session may be using it. Ask, or pick another port consistently.
- "Browser may not be secure" at sign-in: the browser was started by automation. Relaunch as
  in step 2.
- A selector finds nothing: read the page text first; consoles rebuild their DOM often.
- The operator says "stop" or "close it": stop reading, close, delete the profile.

## Do NOT

- Use the operator's everyday Chrome profile, or leave the port open.
- Act in a console beyond what was asked, or browse unrelated pages while signed in.
- Copy cookies, local storage or anything credential-like out of the window.
