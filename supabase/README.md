# supabase

Database migrations and seed data for the shared Supabase project.

- `migrations/` holds SQL files named `<YYYYMMDDHHMMSS>_<short_name>.sql`. They run in filename order.
- `seed/` holds fictional demo data for repeatable testing and demos.

Rules (full detail in [docs/database-schema.md](../docs/database-schema.md)):

1. Never edit a migration that has been merged. Add a new one.
2. One owner per table. Do not create a second version of a table someone else owns.
3. Every table has Row Level Security enabled in the same migration that creates it.
