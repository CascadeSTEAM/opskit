# Summary

<!-- What this PR changes and why. Reference the issue it closes: "Closes #NN" -->

## Testing

<!-- What you ran and what it showed. "It should work" is not testing. -->

## Checklist

- [ ] Branch was created from the issue (`gh issue develop <n>`) — not work done on `main`
- [ ] Full test suite green (`pytest tests/`); pre-existing unrelated failures are named above with their issue numbers
- [ ] Touched shell scripts pass `bash -n` / shellcheck
- [ ] Commit messages follow `<TICKET>: <type>: <description>` / conventional-commit format
- [ ] No hardcoded credentials, real hostnames, internal IPs, or environment data (repo is public; only `environments/example/` is committable)
- [ ] Docs/device YAMLs updated in the same PR if infrastructure behavior changed
- [ ] Reviewer other than the author requested; author assigned as PR manager
