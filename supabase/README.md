# supabase

Database migrations, seed data and database checks for the shared Supabase project.

| Path | Contents |
|---|---|
| `config.toml` | Supabase CLI settings |
| `migrations/` | SQL files named `<YYYYMMDDHHMMSS>_<short_name>.sql`. They run in filename order. |
| `seed/` | Fictional demo data. Safe to run more than once. No passwords. |
| `tests/` | SQL checks for sign-up, privileges and organisation isolation |

How to apply migrations, load demo data and run the checks:
[docs/development-guide.md](../docs/development-guide.md#6-database).

Rules (full detail in [docs/database-schema.md](../docs/database-schema.md)):

1. Never edit a migration that has been merged. Add a new one.
2. One owner per table. Do not create a second version of a table someone else owns.
3. Every table has Row Level Security enabled, and explicit grants, in the same migration that creates it.
