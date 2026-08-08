# SESSION-LOG

Strategic index of work sessions on the opskit tool itself: key decisions,
architectural choices, open threads. Detailed operational notes live in
`docs/session-notes/`.

**Publication policy:** any session touching live infrastructure — a client's
OR the org's own — is logged in that environment's private layer
(`environments/<env>/session-notes/`), never here. This file and
`docs/session-notes/` are published; they may describe *code and tool
development only, never infrastructure state* (facts leak even when tokens
don't). See docs/client-data-policy.md, "Facts leak too".

---

## 2026-08-07 — the guard goes live, and a peer lineage is founded

**Key decisions:**
- **The conserved core now actually guards.** The operator wired the #160
  PreToolUse hook — the one step deliberately left to human hands. It proved
  itself binding within minutes by denying a commit whose *message* mentioned
  a guarded path: confirmation and a new false-positive class in one event
  (#169). Per standing doctrine the deny was answered by rewording, not by
  allowlisting past the guard.
- **The self-modification question got its frame.** Evolution is variation
  plus *external* selection, and it conserves the selection machinery itself —
  replication enzymes are the most conserved sequences in biology because a
  mutation there breaks selection rather than producing a variant. OpsKit
  keeps the doctrine: agents propose everywhere; settings, hooks, and the
  governing files remain the operator-gated core. The design question worth
  carrying forward: how small can the conserved core be?
- **Self-empowerment goes in a peer project, not here.** Tinker founded
  (private repo growlf/tinker): a three-node lineage — Crone (full memory,
  rules, final judge), Mother (selection, merge, succession-by-proof), Maid
  (memory-empty explorer clone) — under a constitution with three gates that
  ramp toward autonomy while the operator keeps permanent override. The
  operator's observe-and-converse requirement settled the architecture: one
  persisted bus is transport, memory substrate, audit trail, gate mechanism,
  and kill switch.
- **The boundary is a law, not a hope.** Tinker's charter restricts it to its
  own vault collection, repo, and containers; #168 requests exactly that
  scoped slice (environment entry, vault collection, provision/clone/rebuild
  playbooks, guard-hook inheritance) and states the boundary explicitly.
  OpsKit's collaboration surface stays human-gated regardless of how
  autonomous Tinker becomes.

**Completed:** #160 hook wired (operator) and verified live. Tinker repo
founded — charter, architecture, orientation; `crone` as the blessed default
branch. Filed #168 (Tinker's scoped slice) and #169 (guard string-mention
false positive).

**Open threads:** #168 blocks Tinker genesis (its phase 2); Tinker phase 1
(bus + gatekeeper + web UI) can start now in the tinker repo. Prior threads
unchanged: #134 inventory, #131, #138, #159, #166 sweep.

---

## 2026-08-07 — /plow: batch backlog orchestration as a skill

Session note: `docs/session-notes/2026-08-07-plow-skill.md`

**Key decisions:**
- `/plow` layers on the `gh` skill rather than duplicating it: phase 1 clears
  the open-PR queue (review cycle, merge on green), phase 2 dedupes/connects/
  prioritizes open issues, phase 3 works each through the full `gh` cycle,
  strictly one item in flight. Priority triad: simple over complex, importance
  over less-immediate, impact over cosmetic.
- Policy divergence, by operator request: within a `/plow` run, invocation is
  the merge authorization (bounded — no branch-protection bypass, human-blocked
  PRs skipped and reported). Pre-authorizes exactly two actions: merging green
  reviewed PRs and closing unambiguous duplicates.
- Skill placement follows the codified scaffolder (`new-skill`): canonical in
  `.opencode/skills/`, `.claude/skills/<name>` symlink — adds no new pair to
  the #131 divergence freeze.

**Completed:** #164 filed and PR #167 opened (Closes #164); #166 filed
(scaffolder template's `scripts/` path is nonexistent; 11 skills affected).

**Open threads:** #166 sweep; #131 canonical-tree decision now matters more
(new skills keep landing in `.opencode/skills/`).

---

## 2026-08-07 — one definition per rule, and guards that had never guarded

Merged #153, #156, #161, #162, #163, #165. Closed #143, #146, #149 (duplicate),
#151, #152, #154, #155, #157, #158, #160. Ledger rows 4, 14, 19, 27, 41–44
resolved or accepted; rows 5+9 consolidated into one issue, row 22 into #103.
Suite 588 → 718.

**Key decisions:**
- **A rule with two implementations has already forked; the only question is
  when you find out.** Four separate defects this session were the same shape —
  secret patterns defined twice (hook vs CI), vault-session resolution defined
  once but consumed three ways, ticket precedence read straight from a shared
  file by three callers, and a review agent's tool policy that only one spawn
  path honoured. Each fix collapses the rule to one definition and adds a test
  that fails if a caller re-inlines it, because in every case a *comment*
  claiming the thing was shared is what had failed.
- **`|| true` turns a broken guard into a passing one.** The private-key pattern
  in the pre-commit hook had never matched anything: it starts with `-`, so grep
  parsed it as options, errored, and the swallow made it look clean. The same
  shape then bit again inside one change — removing an inline block orphaned a
  variable a later check read, and that check silently stopped seeing files while
  the hook still printed "All checks passed". Dead guards now have their own
  tests.
- **Fix the guard, don't allowlist yourself past it.** A structural test flagged
  a new resolver for mirroring the pattern it was told to mirror, because it
  keyed on a constant *name*. Tightening it to key on the actual lookup made it
  strictly more targeted; adding an exemption would have made it weaker forever.
  Same call on test fixtures: they are composed at runtime so the scanner can
  scan its own test file, rather than the test path being excluded.
- **Say when a deliverable would be theatre.** An issue asked for restricted
  agent definitions; definitions alone could not have prevented the incident that
  prompted it, because the built-in review workflow spawns default-tool agents
  and never reads them. The definition shipped, but the load-bearing half is a
  PreToolUse hook — and the wiring step is deliberately the operator's, since a
  session that can grant its own permissions can also revoke that guard.
- **A guard narrow enough to survive.** The credential-store hook covers
  credential stores, not "anything outside the repo". A guard that fires on
  ordinary work gets switched off, which is why the secret patterns still ignore
  Jinja placeholders.
- **Review before merge is not optional sequencing.** A PR was merged while its
  own review was still running; that review then found two regressions the merge
  had shipped, costing a second issue, PR and review cycle to undo. Standing rule
  now: unrequested actions get offered, not performed — and waiting for work
  already in flight is part of the task.

**Completed:** seven PRs, 9/9 CI on each, every fix verified by running it rather
than reasoning about it — which is how the code-root/data-root conflation, an
`ipaddress` stdlib edge on host routes, and an exported variable defeating its own
source-reporting were each caught before review.

**Open threads:** #134 needs a file-by-file inventory before any scrub — the call
on which files are real versus illustrative is the operator's. #131 and #138 have
owner decisions recorded and are ready to start. #159 is scoped as a comparison
first, with an explicit stop-and-discuss gate. The PreToolUse hook from #160 is
inert until wired into settings.


---

## 2026-08-05, continued — the collaboration layer gets its own tooling

Merged #129, #132, #135, #137. Closed #128, #130, #133, #136. Filed #131, #134, #138.
Ledger rows 7, 10, 11, 16, 17, 34, 39, 40 resolved.

**Key decisions:**
- **Two layers, stated explicitly.** The vehicle rule governs the *product* — what we do
  to environments. It is silent on the *collaboration surface*: the instruction files,
  skills, agents and harness wiring. An agent applied it to a proposal about improving
  that surface, concluded "script, not MCP tool", and cited doctrine as though it
  settled the question. The document never said which layer it governed, so the
  misreading was the document's fault as much as the reader's. Now a table at the top of
  the principles, with the incident recorded as the reason — a rule with no rationale
  gets re-litigated.
- **Verify may be automated; rewriting may not.** The governing files are the control
  surface for agent behaviour. An automated edit can silently weaken a hard rule, and no
  test catches a rule that has merely been softened. Tools there propose; a human
  disposes.
- **A guard is only as good as its list, and nothing can verify a list is complete.**
  Twice in one day the list was the weak link rather than the check. The response is a
  reporter that derives candidates from the private layers — and a standing
  acknowledgement that it narrows the gap rather than closing it.
- **Signal beats recall in any report a human must read.** The first version of that
  reporter suggested device names as client names. A report full of noise is ignored
  entirely, so a missed candidate is preferable to a list nobody reads.
- **A guard that only sees deltas cannot tell you the state of the thing it guards.**
  Every guard here checks added lines, so nothing has ever examined the repo's existing
  content — which is how pre-existing content went unreviewed. Generalises well beyond
  the specific finding.
- **Report the consequence, not the condition.** "No remote" was read as "host
  unreachable" and dismissed — correctly, about the hosts. A check understood as
  something else produces false reassurance.
- **Copying between projects is the disease.** Four independent instances surfaced in
  one day, all the same shape: a copy that could not tell it was stale. A survey of the
  sibling projects then found the cure already prototyped — one project consumes this
  repo's guards *by reference* rather than reimplementing them. #138 generalises that.

**Completed:** 588 tests, up from 341 at session start. Sixteen PRs, 9/9 CI on each.
Four subagent-assisted analyses; two found things a direct read would have missed.

**Open threads:** #134 and #131 need owner decisions; #138 needs a mechanism choice;
#94 still needs a lab device and #106 waits on it. Two helpdesk actions are prepared but
unposted. Ledger row 24 (an injected-variable deprecation across 12 files) is scoped and
unstarted — a clean first task next session.

---

## 2026-08-05 — Guards that had never guarded, and one that guarded the wrong surface

Merged #108, #111, #113, #115, #117, #119, #121, #123, #125. Closed #105, #110,
#112, #114, #116, #118, #120, #122, #124. Split #106. Ledger rows 7, 16, 17, 18,
20, 23, 25, 28, 29, 30, 31, 32, 33, 34, 35 resolved; rows 36, 37, 38 captured.

**The theme, unplanned:** almost every issue this session turned out to be a check
that existed and did not work. A lint that had never once passed because it globbed
the wrong extension. A launch validator that could not detect a server which parses
its config and then rejects it. A publication guard that read every surface except
the one a branch name is published on. A test suite that was green because CI has no
configuration. Schemas that described data nothing validated. In each case the
absence of signal read as success.

**Key decisions:**
- **Report before enforcing, with the flip as a deliberate step.** Dataset
  validation would fail unfixably on introduction — one layer has 58 of 59 records
  missing a required field. A check that can never pass gets ignored, which is
  worse than no check. `--strict` exists for when a layer is clean.
- **Prevention over detection** where both are possible. A test suite that behaves
  differently per machine is broken even if something notices, so config paths are
  isolated by construction rather than by everyone remembering.
- **Guards must be seen to fail.** Each new guard is verified against the real
  pre-fix code, not only against its own fixtures — a guard validated against its
  own test cases agrees with itself. The AST interpolation guard found 5 findings in
  the pre-fix file and 0 after.
- **Verification follows TLS by default.** Claiming transport security while
  skipping certificate checks is worse than plaintext: it looks secure and is not.
- **Nothing is dropped silently.** Generated config names what it could not include,
  with the reason. Omission leaving no trace is how a device stayed missing long
  enough to become an issue.
- **A missing value is a refusal, not a guess** when it selects an API path.
- **AST over regex for security guards.** A regex cannot distinguish a quoted
  interpolation from a bare one, and a guard with false positives gets disabled.
- **The client-data rule binds every published surface**, not just session notes —
  public issues, PR bodies, and the tracked idea ledger. Two issues describing an
  environment's device inventory were deleted (not closed: a closed issue stays
  public and indexed) and refiled privately. A finding usually splits: the device is
  private, the tool gap is public, and the public half generalises better anyway.
- **Environment layers are single-branch.** One had 26 commits of operational record
  on an unmerged branch, invisible to every other clone.

**Completed:** 566 tests, up from 341. Twelve PRs merged, 9/9 CI checks green on
each. Merged #108, #111, #113, #115, #117, #119, #121, #123, #125, #127, #129, #132.
Closed #105, #110, #112, #114, #116, #118, #120, #122, #124, #126, #128, #130. Split
#106; filed #131. Ledger rows 7, 10, 11, 16, 17, 18, 20, 23, 25, 28, 29, 30, 31, 32,
33, 34, 35 resolved.

**Later decisions in the same session:**
- **A published surface is any surface.** A client-named branch was found on the
  public remote — caught by an audit, not by a guard, because the token list did not
  contain that name. The guard chain now covers branch names at push time, but the
  lesson is the list: a guard is only as good as it, and nothing can verify the list
  is complete. Twice in one day it was the weak link rather than the check.
- **Report the consequence, not the condition.** A backup check said "no remote",
  which the operator correctly read as "host unreachable" and dismissed. A check
  understood as something else produces false reassurance — worse than no check. Every
  message now names its subject and disclaims the likely misreading.
- **An exported override beats a file, so a session can pin itself.** Two sessions
  sharing a clone shared one mutable global and could change each other's environment
  mid-task. A lock was rejected as serialising work that is legitimately parallel.
- **One implementation of a precedence rule.** Six readers had each reimplemented the
  same parse, and had already drifted. Guards now fail on a second implementation
  appearing, not just on the first one being wrong.
- **Freeze a known mess, prevent growth.** Two tracked skill trees had diverged in
  every shared skill. Rather than pick a winner and silently discard the loser's
  improvements, the one unambiguous case was fixed and the rest grandfathered in a
  visible allowlist that fails if it names a pair which now agrees.
- **Code root is not data root.** The same conflation broke 22 tests and then
  reappeared as importing a module from a caller-controlled path. Worth naming because
  it will recur in any shared helper.

**Process:** the operator set the full per-issue cycle — propose, critique, research,
improve, resolve, implement, check completeness, PR, critique, resolve, merge — and a
standing rule to land in-flight work before starting anything new. Both earned their
keep: the critique step caught that honouring an environment variable would
reintroduce a bug fixed hours earlier; the completeness step caught a design flaw
review would have missed; and self-review found a latent hang, a credential-exposure
path, and a 300-line reformatting diff hiding two real changes — all in code merged
the same day.

**Open threads:** #94 needs a lab device and #106 waits on it; #131 needs three
decisions from the owner before the skill trees can be reconciled; #103, #104
untouched. 13 ledger rows remain untriaged. Two helpdesk actions are prepared but
unposted, pending a vault session.

---

## 2026-08-04, continued (3) — the config becomes a build artifact

#105 finished as far as it can go; split #106 (TLS) and #107 (an unmanaged AP,
and a core switch with no automated path) for the parts with external
dependencies. Ledger rows 31, 32, 33; rows 28, 29, 32 marked accepted.

**Key decisions:**
- The external tool's device config is now **generated** from device datasets
  (`bin/gen-mikromcp-config.py`), not hand-maintained outside the repo. Datasets
  are canonical; the config is a build artifact with `--check` for drift.
- Everything is **derived by convention** from fields already on the device
  record — id, credential variable names, host, version, tags. Adding an
  environment means adding device records and editing nothing else. That was the
  deciding criterion over a per-device mapping table, which is one more thing to
  keep in sync.
- A record may override only what convention cannot know (port, TLS,
  verification, ssh port). This is how devices move to 443 one at a time as
  #94 lands, rather than in one flip.
- **Verification follows TLS by default.** Claiming TLS while skipping
  certificate checks is worse than plain HTTP — it looks secure and is not.
  Turning it off requires a pinned cert and a written reason.
- **Nothing is dropped silently.** A device that cannot be wired is named, with
  its reason, in the generated file. Omission leaving no trace is precisely how a
  device stayed missing long enough to become an issue.
- **A missing version is a refusal, not a guess** — the field selects an API
  path, so a wrong value silently targets the wrong endpoint.
- Corrected an earlier decision from the same session: a credential mapping
  justified as "behaviour-preserving" on the strength of a hash match turned out
  to preserve a 401. A hash proves two strings are equal, not that either works.
  Live verification is now the standard for a credential change.
- Documented a device the tooling deliberately **cannot** manage (different
  firmware family, no REST API) in its own record, so the exclusion reads as a
  decision rather than an oversight — and named the consequence nobody had
  stated: it has no rebuild path at all.

**Completed:** 24 generator tests, 9 launcher tests, 8 playbook tests; suite
373 passed. All device credentials now resolve from the vault — zero secrets
remain in any agent runtime config.

**Open threads:** #106, #107; ledger row 30 (datasets never validated against
their schema) and row 33 (environments should declare a schema version) both
point at the same missing validation layer; row 31 (no shell path to the
external tool's own tools) is the prerequisite for anything else generating
from live device state.

---

## 2026-08-04, continued (2) — the launcher learns about servers it does not contain

Started #105 (branch open, not finished). Operational detail is in the private
layer. Ledger rows 29, 30.

**Key decisions:**
- `bin/mcp-run.sh` now launches **external** MCP servers — ones installed
  outside this repo — declared in a new tracked `mcp/external-servers.json`,
  with the same vault resolution as the in-repo servers. The alternative was a
  second wrapper script, which is precisely the shape #80 deleted.
- A third-party server that cannot resolve vault secrets itself does not get an
  exemption from the credential rule; the launcher resolves them and the server
  is handed an already-populated environment. Applied here because the server in
  question accepts a `vault` credential source in its config schema but raises
  `VAULT_NOT_SUPPORTED` from the implementation — a capability that exists only
  as validation.
- The launcher's JSON parsing moved off the repo venv onto any `python3`, so an
  external server no longer inherits a Python dependency it has no use for.
  `--check` gained a PATH probe, because "installed outside the repo" is a new
  way for the launch path to be silently wrong.
- `os_version` on a device record is treated as canonical, with the external
  tool's copy reconciled to it rather than the reverse (ledger row 28).

**Completed:** 9 tests added to `tests/test_mcp_run.py` (341 passed);
shellcheck clean.

**Open threads:** #105 items 1 and 3 remain (TLS blocked on #94; one router's
credential has no vault item, so one cleartext value could not be removed);
generating the external tool's device config from this repo's datasets is still
unbuilt; ledger row 29 (a playbook credited in a vault note that exists nowhere)
blocks doing least-privilege API users properly.

---

## 2026-08-04, continued — a doctrine gap, and being wrong twice about the same file

Merged #101. Filed #103, #104, #105. Ledger row 28.

**The session's most useful correction was to a rule, not to code.** I recommended
retiring `mikrotik-configure-rest-api.yml` because an interactive tool already
covers every step it performs. The owner's correction: Ansible has to be able to
rebuild the infrastructure from zero, so an interactive tool is never a substitute
for a playbook — they do different jobs.

The repo mandated IaC and separately routed RouterOS work through a subagent, and
**never arbitrated between them.** With both documented and neither deferring, a
wrong conclusion was reachable by correctly applying one rule and forgetting the
other. #101 states the rebuild objective, states that an MCP tool does not replace a
playbook, and adds the discipline that keeps it honest: an interactive change must be
reflected back into the playbook the same session, or the rebuild path rots and you
discover it during a restore.

**Then I was wrong about the same file a second time, in the opposite direction.**
I reported that the interactive tool reaches RouterOS over SSH, so there was no
bootstrap dependency. Reading further: its primary transport is the REST API
(`/rest`, Basic auth, via undici); SSH is a secondary channel for a few tools, and
the diagnostic that misled me names exactly those tools. So RouterOS management does
depend on an HTTP service, and the playbook is what enables it — specifically the
**TLS** variants, making it a hardening step with a live motivation (#105).

**Both errors came from stopping at the first plausible reading.** The first
applied one rule and forgot another; the second took a grep hit as a conclusion
instead of reading the adapter. The improvement cycle catches the second kind
reliably; the first kind needs the doctrine to be written down, which it now is.

**A third correction, from the owner, worth keeping:** I claimed I could not read a
router's version because "the MCP tool namespace isn't loaded in this session". The
tool is also a CLI and was installed the whole time. Conflating "namespace not
loaded" with "capability unavailable" is a habit to break — and the fix, when a
capability really is missing, is to make it work rather than hand the task back.
That is a large part of what #104 exists for.

Threads: #94 (fix the module arguments; needs a test target — a RouterOS CHR VM in
the new lab pool is the agreed approach, pending the production version number),
#103 (codify token provisioning/tracking/revocation, and decide the vault ↔
ansible-vault direction of truth), #104 (CLI parity — settle the architecture and
port one capability), #105 (RouterOS on TLS, vault-resolved credentials, and one
unconfigured router).

---

## 2026-08-04 — Eleven PRs, and a class of defect that kept reappearing

Merged: #88, #89, #92, #63, #65, #93, #96, #97, #98, #99, #100. Every open issue
closed except one, which needs an owner decision and a device (#94). Six ledger
rows. This session touched live systems; operational detail is in the private
environment layer.

**One defect class accounted for most of the work: code that had never executed
on the path it exists to serve.** Not bugs in logic — bugs in *reachability*, all
invisible because the thing that would have noticed was itself broken.

- `skip_list` held an unskippable rule, so ansible-lint aborted rather than
  linting. 13 playbooks, 14 roles, never checked. CI had the same bug from a
  second direction with `continue-on-error` hiding it.
- Two subagents documented as having runtime-enforced tool permissions declared
  them under a nested key OpenCode silently ignores — so the MikroTik agent had
  MikroTik tools *denied*, and neither agent existed in either harness at all.
- A playbook templated a unit file that has never existed in git history; another
  pointed at a `requirements.yml` that never existed. Both failed at those tasks,
  so nothing after them had ever run.
- `open-ticket.sh` demanded a credential the repo never provisions, making the
  mandatory ticket gate unsatisfiable — so sessions fell back to `--local`, which
  records a marker and no helpdesk record. The audit trail degraded quietly.
- An internal-comment tool wrote to a doctype the Helpdesk portal does not render.
  The API returned success; agents saw nothing.

**The pattern in all of them is a success signal that means nothing.** A non-zero
exit that reads as "found problems" rather than "never ran". A 200 for a write
nobody will see. A config key accepted and discarded. The remedy that actually
worked was cheap and repeatable: *run the thing, then check reality rather than
the return value* — diff the parsed YAML rather than the text, re-read the server
after a mutation, assert the doctype rather than the status.

**Adopted as a standing practice mid-session (owner's instruction): critique →
research → improve, per component, before calling anything done.** It paid for
itself immediately and repeatedly:

- `ansible-lint --fix` "resolved" a `partial-become` finding by **deleting
  `become_user: postgres` from a pg_dump task**. Caught only by comparing parsed
  YAML before and after — 6 of 24 auto-fixed files had changed *meaning*. Three
  more tasks had the same defect.
- A `bw send --file` parser assumed a bare URL where the CLI returns JSON, so it
  rejected a Send it had just created — orphaning a config, private key included,
  in the vault. Found by running it, not reading it.
- An `install.sh` addition aborted the script under `set -euo pipefail` on a fresh
  clone, the one place it must never fail.
- Test fixtures wrote into the real `environments/` tree because a module
  captured its root at import, before the isolating fixture ran.

**Two corrections worth recording, because being wrong loudly is cheaper than
being wrong quietly.** A published issue blamed credential drift for a login
failure whose real cause was TOTP — the seed was in the vault the whole time, and
the wrong diagnosis pointed at a destructive fix on a live container. And a claim
that two orphan VPN peers had "never been used" rested on a handshake counter that
resets on interface restart. Both are corrected in place, and the second is now
encoded in the tool so nobody repeats it.

**Where guards were added, they were verified by breaking them.** Every regression
test in this session was run against the defect it guards and observed to fail
first. A guard that has never been seen to fail is indistinguishable from one that
cannot.

Threads: #94 needs a decision (retire the RouterOS playbook, or keep it and
document why it is exempt from the `@mikrotik` routing rule) plus a lab device.
Ledger rows cover the lifecycle-processor cutover, `mcp-run.sh --check` accepting
a locked vault as "set", `opskit lint` ignoring the env's declared record format,
and scan-time Proxmox enrolment.

---

## 2026-08-03 — Two guards that had never guarded anything

PRs open: #88 (unbreak ansible-lint repo-wide + regression guard), #89 (make the
workstation Ansible toolchain playbook actually run). Issues filed: #86 (Proxmox
MCP wiring), #87 (ansible-lint backlog triage). Ledger row 22. This session
touched live systems; operational detail is in the private environment layer.

**Closed out yesterday's open question first: the parallel MCP entry namespaces
correctly, no collision, nothing to disable.** Worth recording the method, since
it cost more than it should have — per-server connect status and the server's
own tool endpoints do *not* include MCP tools, so the only way to enumerate the
resolved tool namespace is to run an actual agent session and ask it. Two
runtime entries whose backing clones or config had never existed were removed.

**`skip_list` contained a rule that cannot be skipped, and so nothing was ever
linted.** `syntax-check` is unskippable; listing it makes ansible-lint abort on
the config instead of skipping that one rule. 13 playbooks and 14 roles, never
checked. The CI step carried the identical bug from a second direction — the
same rule on the command line, with `continue-on-error` swallowing the abort.

**What made it survive is worth generalising: the failure exited non-zero.**
"Lint ran and found problems" and "lint never ran" are the same signal to anyone
skimming, so the breakage was self-camouflaging in the one place a human would
look. This is the same class as 2026-08-02's silent MCP launch failures, and the
third instance in two sessions of *a guard whose own correctness nothing checks*.
The response was a test that fails if the config ever disables linting again —
and it was verified by reintroducing the exact breakage, because a guard that
has never been seen to fail is indistinguishable from one that cannot.

**The toolchain playbook failed twice over, and the second failure was only
reachable by fixing the first.** The reported bug was a module requiring a
newer pipx than the current LTS ships — on the bootstrap playbook, so the
unsupported case was the normal case. Fixing it revealed the collections task
pointed at a requirements path that has never existed in this repo's history.
Both failures sat on the path a fresh workstation takes, which means the
playbook had almost certainly never run to completion anywhere. A third defect
found while reading it: the toolchain-state report's PATH warning was
unreachable, because the check meant to feed it aborted the play first — the
diagnostic was dead exactly when it was needed.

**Pattern across all three:** code that was never executed on the path it exists
to serve. The lint config, the CI lint step, and the bootstrap playbook each
looked maintained and each had never done its job. Tests assert behaviour of
things we run; nothing asserted these ran at all.

Unblocked before triaging #87: local and CI ansible-lint disagree 128 findings
to 2, because CI pins the action five majors behind what a provisioned
workstation installs. Cleaning against one leaves the tree dirty against the
other — a straight #19 parity problem, and the version needs settling first.

---

## 2026-08-02 — Installability, and the wiring nobody was checking

Merged: #79 (workstation install guide + real dependency preflight),
#81 (vault-resolving MCP launcher). Operational detail is in the private
environment layer — this session touched live systems.

**The question that started it was "what do I install on a second machine",
and the honest answer turned out to be "more than this repo knows about".**
A fresh clone passed `install.sh` and then failed at the first playbook run,
the first commit, or the first agent tool call: collections are gitignored,
`core.hooksPath` is per-clone, `gitleaks`/`shellcheck` degrade silently, and
the servers backing the domain subagents are launched by absolute path from
outside the repo. `docs/INSTALL.md` now states each layer and what its absence
disables; `install.sh` checks ~20 dependencies instead of 4 and distinguishes
required from optional-per-capability.

**`AGENTS.md` has instructed every session since the hooks rule landed to run
`bash bin/setup-hooks.sh`. The script did not exist.** Documentation asserted a
tool into being and nothing ever checked. Written now, with a `--check` mode.
Worth noticing as a class: the repo's guards check *content* thoroughly and
*its own claims about itself* not at all.

**The larger instance of the same class:** the agent runtime was launching
older duplicate copies of two MCP servers from a sibling repo. Everything
merged into `mcp/` — an entire expanded tool surface, plus an auth fix — had
never once been reachable from an agent session. The code shipped; the wiring
pointed elsewhere; no test, guard, or review step covers "is the thing we
built the thing that runs". `bin/mcp-run.sh` makes the launch path a
first-class, tested artifact of this repo rather than tribal configuration,
and `--check` exists specifically because the failure is *silent* — a server
that fails to start is indistinguishable from an agent declining to call it.

**Decision (owner, mid-session): add alongside, never cut over.** A parallel
runtime entry now serves the in-repo implementation while the pre-existing one
stays untouched, so the new path can be proven on real work with no moment of
downtime and a one-line revert. A repoint made earlier in the session was
reverted to honour this; the runtime config was verified byte-identical to its
pre-session state before anything was added.

Also learned, generally: adding a parallel MCP entry needs its own permission
rules. Tools are namespaced by server key, so a new entry does *not* inherit
the deny that covers the entry it shadows — it would be more exposed, not
equally exposed.

Threads: retire the duplicate copies once proven; four ledger rows
(#18–21) covering a wiring guard, the retirement, an unrecoverable-environment
check, and credential-documentation drift.

### Continuation, 2026-08-03 — #85, and what linting the new playbook exposed

`uv` was missing, so every `uvx`-distributed MCP server had silently never
started. Installing it turned into an IaC question rather than a one-liner:
`workstation-ansible-toolchain.yml` already states the principle at the top of
the file — *control-node software lands via playbook, not ad-hoc shell* — so
the fix is `workstation-mcp-toolchain.yml`, not a curl-pipe in the docs.

**The playbook takes a `target` override, and that is the interesting part.**
A freshly-provisioned workstation belongs to no inventory group, which is
precisely when a provisioning playbook needs to run. A play hard-bound to
`hosts: workstations` cannot bootstrap the machine it exists to bootstrap.
The first draft had exactly that defect and the documented invocation matched
zero hosts — visible only because it was actually run.

**Two latent defects surfaced while validating one small playbook**, which
says something about how much of the Ansible layer is unexercised:

- **#83 (urgent)** — `.ansible-lint.yml` skips `syntax-check[specific]`, which
  is unskippable, so ansible-lint aborts before evaluating a single rule. *No
  playbook or role in this repo has ever been linted.* It exits non-zero, so
  the breakage reads as "lint found problems" rather than "lint never ran" —
  the same silent-failure shape as the MCP wiring above, and as the
  documented-but-nonexistent script. Third instance this session of a check
  that appears to run and doesn't.
- **#84 (high)** — `community.general.pipx` requires pipx ≥ 1.7.0; the current
  Ubuntu LTS ships 1.4.3. The existing toolchain playbook therefore fails at
  its first task on a stock workstation. The new playbook drives the pipx CLI
  with explicit idempotency guards instead, rather than upgrading pipx as a
  side effect of installing something else.

Order matters: #83 before #84, since unbreaking the linter sweeps all 13
playbooks and 14 roles at once and #84's file is in that sweep.

Session totals: #79, #81, #85 merged; #83, #84 open.

---

## 2026-07-31 — Two execution paths for Frappe; one of them now sanctioned

Session note: `docs/session-notes/2026-07-31-frappe-exec-path-b-wrapper.md`

**Correction to how these defects were first framed.** They are *not* general
Frappe traps. They belong specifically to the SSH + container-exec + `bench`
path ("Path B"). The repo's existing HTTP/REST MCP server ("Path A") is
**structurally immune to all three**, because it speaks JSON in and JSON out:

- `bench execute` **suppresses falsy return values** — a call returning `0`
  prints nothing. Empty output is neither an error nor reliably zero, so
  reading it wrong yields a confidently false answer. A correctness defect,
  not a cosmetic one. (Live contrast: the same count over HTTP returns
  `{"message": 0}`.)
- `bench console` mangles piped multi-line scripts (IPython auto-indent).
- Frappe images exec as a **non-root** user while `docker cp` writes
  **root-owned** files into a sticky `/tmp` — cleanup fails with "Operation not
  permitted" and scripts persist in the container unless `docker exec -u 0` is
  used. (This one bit: a cleanup step was reported done when it had not been.)

**The real problem was that no rule said which path to use**, so the
credential-free `bench` path kept being hand-rolled — six times in one session.
Path A wasn't the default because it authenticated as `Administrator` with a
password from a plaintext `.env`, contradicting
`.opencode/rules/no-plaintext-creds.md`. That auth defect was the actual blocker.

**What shipped:** `bin/frappe-exec.py` as the single sanctioned Path B route,
engineering all three defects out structurally rather than documenting them
again — never `bench console` (venv python over stdin), never `docker cp` (no
file ever written in-container), always one JSON envelope
`{"ok","result","error"}` so falsy and empty can never be confused. Path A's
auth replaced with configurable API-key/secret token auth. New `frappe-access`
skill carries the A-vs-B routing rule; the tools carry the behaviour.

**A fresh adversarial critique before merge caught a high-severity defect the
author pass missed:** `ssh` appends trailing argv into a *single string* that a
remote shell parses, so unquoted interpolation of a container name achieved
arbitrary remote command execution. Fixed with `shlex.quote` plus regression
tests. Worth generalizing — anything building an `ssh` command from
parameters needs quoting, and "it's passed as separate argv elements" is not
protection.

**Key decisions:**
- A documented footgun is not a fixed footgun — make the trap-laden path
  non-default and non-hand-rolled instead of adding footnotes to a skill.
- Tool-placement rule split by *kind* of state: Ansible for system/deployment
  state, MCP tool for application records. The old single rule was genuinely
  ambiguous and stalled a decision twice in one session.
- An "epic" in Frappe Helpdesk is expressed by subject-prefix convention plus
  cross-referencing, not a doctype field — the app has no native parent/epic
  concept and a schema change isn't warranted for grouping tickets.
- `frappe.rename_doc` (the `frappe/__init__.py` wrapper) does **not** accept
  `ignore_permissions`; only `frappe.model.rename_doc.rename_doc` does.

**Path A's record surface was then extended too** (#74 / PR #75): full party
management with a 1:1 invariant that the application cannot enforce itself,
because the bridge between the two customer doctypes is a free-text field
rather than a link — so the tooling owns the invariant, including a drift
check that doubles as its regression test.

**A defect CI structurally could not see.** After that merge, the suite failed
locally while CI reported success on the byte-identical commit — not venv, not
ordering. The server read a **gitignored local config file at import time**, so
CI (which never has one) was permanently green while any developer holding real
config saw 41 failures. Fixed in #76 / PR #77 by making the config path
injectable. Worth internalizing: *"CI is green" is not "the suite passes"* — a
suite that depends on the **absence** of gitignored config is green forever and
wrong for everyone.

**Method note that paid for itself:** every PR was built by one agent and then
critiqued by a **fresh adversarial reviewer**, never the author. Two of three
reviews found real high-severity defects, and in one case the reviewer also
showed the feature's own test could not have caught its bug — a passing test
that proved nothing. Author self-review would have missed both.

**Completed:** issues #70, #71, #74, #76 closed via PRs #72, #73, #75, #77
(all squash-merged). **191 tests green**, verified both with and without local
config present.

**Open threads:** live write-path validation of the party tooling is
deliberately deferred pending a development instance (tracked privately) — the
service account is read-only by design. Idea row 15 logged (site named for a
superseded vhost, forcing a permanent reverse-proxy Host rewrite). A stray
top-level `rules/iac-required.md` still carries pre-split wording — pre-existing
dual-harness drift, tracked in #62. **Issue #69's in-progress worktree targets
the same MCP server file that #73 and #75 substantially rewrote, so it needs
rebase or reassessment before it resumes.**

## 2026-07-27 — Helpdesk ticket tooling: skill + MCP server extension

**Key decisions:** codified a recurring manual pattern (reading/commenting on
live Frappe Helpdesk tickets via SSH + `bench execute`) as a new
`helpdesk-ticket` skill — two footguns had bitten real sessions: trusting a
stale post-migration host copy, and posting to the wrong comment doctype
(invisible in the portal UI). Discovered an existing-but-unconnected
`mcp/erpnext-mcp-server.py` already covered list/get/create/update/reply;
decided to extend and connect it rather than write a parallel script.
Scoped the extension to add true per-agent ticket assignment (Frappe's
standard assign-to/ToDo mechanism, not just bulk agent-group), fix the same
comment-doctype bug in the MCP server's reply tool, generalize the server to
use a configurable low-privilege service-account login instead of a
hardcoded Administrator user, and register the server so it's actually
connected.

**Completed:** issue #67 / PR #68 merged — `helpdesk-ticket` skill added,
registered in AGENTS.md, 115/115 tests green.

**Open threads:** issue #69 (MCP server extension) opened and scoped, work
started in its linked worktree but not yet implemented/committed — pick up
next session. Idea ledger row added for an unrelated small UX gap surfaced
along the way (row referencing a live-helpdesk diagnosis, no client detail).

---

## 2026-07-27 — OpsKit 101 onboarding slide deck

Session note: `docs/session-notes/2026-07-27-opskit-101-onboarding-deck.md`

**Key decisions:** built a self-contained scroll-snap HTML slide deck
(`docs/onboarding/opskit-101.html`) introducing OpsKit to new developers,
styled from the actual Cascade STEAM brand assets rather than guessed colors;
verified rendering with headless system Chrome via Playwright
(`channel: 'chrome'`) since no project skill covers screenshotting a static
page; PR opened without a linked issue (doc-only work, not issue-driven).

**Completed:** PR #66 opened (`docs/opskit-101-onboarding-deck` branch,
reviewer `CascadeSTEAM/technology-support`, self as assignee).

**Open threads:** PR #66 awaiting review/merge; idea ledger row added for a
reusable "screenshot a static/browser-driven page" recipe in the `run` skill.

---

## 2026-07-25 (cont. 2) — wiki-hook fix landed: live patch + image PR

Infra session — operational note in the private env session-notes.

**Key decisions:** kept the Wiki-User auto-role behavior (patched the hook to
re-fetch the doc) instead of following upstream master's hook removal;
validated the Containerfile patch step by building it as a layer on the
current production image before opening the PR (images repo PR #8, closes
issue #7). Patch step is guarded — skips cleanly when upstream drops the hook.

**Open thread:** live containers carry the fix in their writable layers only —
container recreation reverts it until a new image (with PR #8) is tagged,
built, and deployed.

---

## 2026-07-25 (cont.) — ERP outgoing email restored

Infra session — operational note in the private env session-notes.

**Key finding:** the undecryptable-credential problem was NOT a changed site
`encryption_key` — the credential had been migrated from a predecessor host
and was still encrypted under *that* host's key. Fixed surgically by
decrypting with the origin key and re-encrypting under the active site key
(no config change). Lesson for restore/migration runbooks: after moving a
Frappe site between benches, audit `__Auth` decryptability instead of
assuming the key changed.

**Open threads (tracked privately):** plaintext credential file found on the
ERP host; stray half-configured email account; predecessor host still serving
a live copy of the migrated site.

---

## 2026-07-25 — ERP user-creation failure traced to wiki app hook

Infra session — operational note in the private env session-notes.

**Key finding:** the Frappe `wiki` app's `User.after_insert` hook
(`add_wiki_user_role`) re-saves a stale in-memory doc, so on multi-app images
every new-User insert dies with `TimestampMismatchError` and rolls back. Filed
issue #7 on the org's ERP-images repo with fix options (image patch / upstream
bump / hook override); a console workaround unblocked the immediate request.

**Open threads:** two restored-site/credential follow-ups tracked privately;
idea row 11 — `ACTIVE_ENV` race when two concurrent sessions share one clone
(observed live this session: `.env` flipped mid-task by another session).

---

## 2026-07-24 — missing Caddy vhosts for ERP client domain

Infra session — note in private env session-notes.

**Key decision:** Applied `upstream_host` rewrite pattern (apex/www/erp → the
canonical Frappe site name) to Caddy vhost config, reusing the precedent from
earlier host-alias work. Confirmed that the compose template uses
`FRAPPE_SITE_NAME_HEADER: $$host`, requiring a Host-header rewrite to serve
a single Frappe site under multiple hostnames.

**Open thread:** No single Caddy route manifest exists — vhost omissions are
invisible. Consider a route-inventory doc or validation that every DNS record
has a matching Caddy vhost.

---

## 2026-07-24 — cluster-llm fallback plugin setup

Session note: `docs/session-notes/2026-07-24.md`

**Key decisions / completed:**
- Installed `@smart-coders-hq/opencode-model-fallback` plugin for automatic
  inference failover: cluster-llm → BigPickle free → Claude direct.
- cluster-llm remains primary; never modified directly.
- Auto-recovers to cluster-llm after 5-minute cooldown.

---

## 2026-07-23 (cont.) — /gh workflow skill; tool fixes; trusted-tester bring-up

Session note: `docs/session-notes/2026-07-23-gh-skill-and-tool-fixes.md`
(a trusted-tester bring-up this session touched live infra — logged privately).

**Key decisions / completed:**
- Codified the 8-step issue-fix protocol as the **`/gh` skill + `bin/fix-issue.sh`**
  (`setup`/`pr`/`cleanup`/`list`/`search`/`new`/`bump`; guided issue creation with
  native issue **Types** + `priority:*` labels + dedup). Issues #50/#52/#54 →
  PRs #51/#53/#55; dogfooded (opened its own PRs via the script).
- `/gh` review step now uses built-in `/code-review` + `/security-review` (#58).
- Fixes merged: `ap.sh` ANSIBLE_CONFIG for role playbooks (#49); `open-ticket.sh`
  fail-loud instead of silent local-ticket fallback + double-prefix fix (#56);
  ansible collections `requirements.yml` (#48); ansible.cfg yaml callback (#42);
  gitleaks wired into pre-commit + CI (#44). Created `priority:*` labels.

**Open threads:** tooling-consolidation proposal drafted, not filed (self-hosted
GitHub MCP + distributable orchestration skill, merging `/gh` with the ported
`docwright-issue-workflow`); DoD-guard skill-registration substring weakness;
branch-name guard gap (ledger row 7); add `definition-of-done`/`gitleaks` to the
required CI checks; rotate the tester box's PAT (tracked privately).

## 2026-07-23 — Home-env wifi operations (logged privately); ideas captured

Session note: in the relevant environment's private `session-notes/` layer
(live-infrastructure session, no details here per publication policy).

**Tool-development threads:** ideas #8–#10 added to the ledger, including a
defect found in `skills/endsession` (references a `session:end` npm script that
does not exist in this repo — shutdown performed manually per AGENTS.md).
No code changes; an unexplained uncommitted edit to the caddy role template was
found mid-session and deliberately left uncommitted for owner review.

## 2026-07-22 — Recovered dropped baseline work; codified a definition of done

Session note: `docs/session-notes/2026-07-22-baseline-recovery-and-definition-of-done.md`

**Key decisions:**
- A dead OpenCode session had left a half-finished `baseline` tool/skill with
  none of the housekeeping done (untriaged idea, no issue/branch, no tests,
  a stub, dead code, a client-token leak). Reconstructed intent from the
  working tree and finished it properly rather than committing as-was.
- **New hard rule: Definition of Done**, machine-enforced. New `bin/*.py`
  must ship a test, new skills must be registered, no stub markers reach
  committed code — checked by `bin/definition-of-done-guard.py` in both
  pre-commit and CI (same script, can't drift; publication-guard pattern).
  Agent-verified items (idea triaged, issue+branch, docs current, gate green,
  session artifacts) moved into the `endsession` skill checklist.
- Kept feature and governance work as **separate PRs** (baseline #37→PR #38,
  DoD #39→its PR) rather than bundling a feature with CI/hook changes.

**Completed:** PR #38 (baseline) and the #39 PR (DoD enforcement) opened,
reviewer = technology-support, author as assignee; `make test` 90/90 green.

**Open threads:** unrelated `ansible.cfg` yaml-callback change from the dropped
session still uncommitted (needs its own PR); ERP branch work untouched.

---

## 2026-07-21 (evening) — Session-note publication rule; env work logged privately

Operational session notes for this session live in the relevant private
environment layers (per the rule adopted below).

**Key decisions:**
- **New hard rule: public session notes may describe code and tool
  development only — never infrastructure state** (not even the org's
  own). Mixed or operational sessions are logged solely in the private
  env layers; SESSION-LOG entries for them stay terse and state-free.
  Rationale: token/IP guards cannot catch *facts* (topology, outages,
  what runs where), and those are the actual intel.
- Option-A env storage scaled to a second environment (second private
  repo, two-row `.env-remotes`) with zero tooling changes — pattern holds
- `opskit init` + wholesale import from a predecessor repo's layer,
  live-verifying every fact before recording, worked well; `opskit lint`
  passed its first real multi-env exercise
- `.current-ticket` is now gitignored (was guard-only protected)

**Tool issues found:** open-ticket.sh helpdesk API integration fails in
both configured tenants (local fallback works) — needs investigation.

---

## 2026-07-21 — Storage rollout (option A), reviewer team access, lint in CI

Session note: `docs/session-notes/2026-07-21-storage-rollout-and-lint-ci.md`

**Key decisions:**
- Environment storage v1 ships as **option A**: one private GitHub repo per
  environment, mapped in the gitignored `.env-remotes`, synced with
  `bin/env-sync.sh`. Self-hosted Forgejo behind Authentik remains the later
  target (migration = mirror push + one map line). Env-repo access is
  owner-only; the opskit team grant does not extend to env repos.
- Default PR reviewer is now the `CascadeSTEAM/technology-support` team
  (granted push access); named-individual fallback.
- e2e CI now proves the `opskit lint` gate fires (positive + negative test)
  — issue #29 / PR #30.

**Completed:** first real env layer pushed to its private repo; #29 closed;
PR #30 merged; tracker and idea ledger both empty; suite 61/61 green.

**Open threads:** ticketed client session (device YAML, context regen,
semaphore-sync, vault) ending with a real env-sync push; ansible-lint to
enforcing once roles settle; REVIEW.md port.

---

## 2026-07-20 (evening) — Backlog cleared: issues #23 + #24

Session note: `docs/session-notes/2026-07-20-backlog-issues-23-24.md`

**Key decisions:**
- `opskit init` refuses case-insensitive duplicate environment names,
  suggesting the existing env (#23, PR #27); `bin/opskit` gained an
  `OPSKIT_ROOT` test override matching the env-sync.sh pattern
- New `opskit lint` subcommand: inventory host without a device YAML is an
  error, orphan device YAML is a warning (#24, PR #28)
- Idea ledger row 3 captured (not yet triaged): run `opskit lint` in the
  CI e2e job

**Completed:** issues #23, #24 closed; PRs #27, #28 merged; suite 61/61
green; issue tracker empty.

**Open threads:** operator actions from the earlier session (storage host +
`.env-remotes`, scrub follow-through, team repo access); ledger
row 3 awaiting triage; flip ansible-lint to enforcing once roles settle.

---

## 2026-07-20 — Publication hardening, workflow codification, tooling ports

Session note: `docs/session-notes/2026-07-20-policy-hardening-and-tooling.md`

**Key decisions:**
- Workflow hard rules: sync-first sessions, linked branch per issue, full
  `make test` gate, PR closes the issue with a reviewer + author as manager
- The public repo, its issues, PRs, and commit messages must contain zero
  client-identifying information (two history rewrites executed); commit
  messages reference tickets as `TKT-<num>` only
- Publication guards (RFC1918 + client tokens) enforced identically by git
  hooks and CI via `bin/publication-guard.sh`; branch protection requires all
  six CI checks on main
- Environment data lives in one private git repo per environment behind the
  org's SSO, synced via `bin/env-sync.sh`; running the git host itself is out
  of scope for this repo
- Idea ledger + triage, ROLLBACK.md procedures, and local agent-context
  generation methodology adopted from the lilyetibot project

**Completed:** issues #1–#8, #10, #12, #14, #16, #19, #20, #25 closed; PRs
#9, #11, #13, #15, #17, #18, #21, #22, #26 merged; suite 47/47 green.

**Open threads:** #23 (init case-collision guard), #24 (inventory lint);
scrub follow-through (operator, tracked privately); storage
rollout (host choice, per-env repos, `.env-remotes`); grant technology-support
team repo access; flip ansible-lint to enforcing once roles settle.
