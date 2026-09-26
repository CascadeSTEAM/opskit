---
description: "Vikunja entry point -- routes to the vikunja-ticket skill for tasks/todos or the vikunja-user skill for account management, so there's one command instead of remembering two skill names. Use for: /vikunja, vikunja, vikunja task, vikunja user, vikunja account."
---

Look at `$ARGUMENTS` (and the surrounding conversation if `$ARGUMENTS` is
empty or ambiguous) to decide which of the two Vikunja skills this request
is actually about, then call the skill tool for that one skill and follow
its instructions exactly, passing `$ARGUMENTS` along as the request.

- **Account management** — creating, listing, updating, enabling/disabling,
  deleting, resetting the password of, or promoting/demoting a user: load
  the `vikunja-user` skill. Trigger words: user, account, invite, disable,
  delete, reset password, set-admin, promote, demote.
- **Everything else** — creating or referencing a task/ticket/todo/project
  item: load the `vikunja-ticket` skill. This is the default when the
  request doesn't clearly name an account operation.
- If it's genuinely unclear which one is meant (e.g. bare `/vikunja` with
  no arguments and nothing in context to disambiguate), ask which is
  wanted rather than guessing — the two skills touch very different things
  (a task vs. a real login account) and picking wrong wastes a step.

$ARGUMENTS
