# supabase

Database migrations, seed data and database checks for the shared Supabase project.

| Path | Contents |
|---|---|
| `config.toml` | Supabase CLI settings |
| `migrations/` | SQL files named `<YYYYMMDDHHMMSS>_<short_name>.sql`. They run in filename order. |
| `seed/` | Fictional demo data for the platform tables. Safe to run more than once. No passwords. Contracts and evidence need stored files, so their demo data is created through the API by `services/api/scripts/seed_demo.py`. |
| `tests/` | SQL checks for sign-up, privileges and organisation isolation, one file per migration |

How to apply migrations, load demo data and run the checks:
[docs/development-guide.md](../docs/development-guide.md#6-database).

Rules (full detail in [docs/database-schema.md](../docs/database-schema.md)):

1. Never edit a migration that has been merged. Add a new one.
2. One owner per table. Do not create a second version of a table someone else owns.
3. Every table has Row Level Security enabled, and explicit grants, in the same migration that creates it.
