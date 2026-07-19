# Rule: Frontmatter Validation

All markdown files in proposals/, plans/, and docs/ MUST have valid YAML frontmatter.

## Required Fields

| Directory | Required |
|-----------|----------|
| proposals/ | title, author, created, tags, approved, created_by, assigned_to |
| proposals/approved/ | title, author, created, tags, approved: true, priority, created_by, assigned_to |
| plans/ | title, status, author, created, tags, proposal_source, priority, automated, assigned_to |
| plans/completed/ (completed) | title, status: completed, author, created, completed_date, proposal_source |
| plans/completed/ (canceled) | title, status: canceled, canceled_date, cancellation_reason |
| docs/ | title, status, completed_date, author, created, tags |
| docs/SOPs/ | title, category, created, reviewed_by, status |

## Validation
- Pre-commit hook checks frontmatter on commit
- Missing or invalid frontmatter = commit rejected
