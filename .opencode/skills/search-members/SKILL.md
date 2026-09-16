---
name: search-members
description: Reference — search membership/member data across a WordPress/WPDB database and an external CRM/donor API
mode: skill
triggers: search,match,member,search-members,find-user,wp-query,find-member
---

# Search Members

> Reference. Load when searching membership/member data across a WordPress database and an external
> CRM/donor API, or running SQL queries against them.

> Replace every `<...>` below with a value from the active environment's vault / env file. Never
> commit real credentials, hostnames, or paths here.

## Database Access

```bash
# Primary site DB
mysql -h <DB_HOST> -u<DB_USER> -p<DB_PASSWORD> <PRIMARY_DB>

# Members / subsite DB (may be a subdirectory or subsite install, not a subdomain)
mysql -h <DB_HOST> -u<DB_USER> -p<DB_PASSWORD> <MEMBERS_DB>
```

## Key Tables — Members

Membership / user tables, typically `*_users` + `*_usermeta`, plus a subscription/membership table:

| Table | Purpose |
|-------|---------|
| `*_users` | User accounts |
| `*_usermeta` | User metadata |
| `*_mp_subscriptions` (or similar) | Active subscriptions / memberships |

## Key Tables — Primary

| Table | Purpose |
|-------|---------|
| `*_users` | User accounts |
| `*_usermeta` | User metadata |

## Common Queries

```sql
-- Find a user by email
SELECT * FROM <PRIMARY_DB>.wp_users WHERE user_email = '<email>';

-- Active subscriptions, most recent first
SELECT * FROM wp_mp_subscriptions WHERE status = 'active' ORDER BY start_date DESC;

-- New users per day (last 30 days)
SELECT DATE(user_registered) AS day, COUNT(*) AS n
FROM wp_users
GROUP BY day ORDER BY day DESC LIMIT 30;
```

## External CRM / Donor Sync

```bash
cd <PROJECT_ROOT> && source .venv/bin/activate
python manage.py sync_<crm>_people        # exact task name comes from the project; confirm before running
```

## Key Rules

- Never modify original data sources — work on local copies
- Members DB is usually a subdirectory/subsite install, not a subdomain
- Vendor card/member fields (e.g. keycard numbers) are often only available via the API, not the DB
- Match external-API records to WP users by email, not by local IDs
- Use `-h 127.0.0.1` not `localhost` when you need to force a TCP connection
- Prefer read-only queries; get explicit consent and scope before any write
- Related: `AGENTS.md` — research context and CRM mapping goals
