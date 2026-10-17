# SQL integration verification

Run from the repository root with Node.js. Install the pinned PostgreSQL WebAssembly
runtime in a temporary directory, outside the project dependency manifests:

```powershell
$sqlRuntime = Join-Path ([System.IO.Path]::GetTempPath()) 'storias-sql-validation'
npm.cmd install --prefix $sqlRuntime --no-package-lock --no-save @electric-sql/pglite@0.5.8
$env:PGLITE_PACKAGE_ROOT = Join-Path $sqlRuntime 'node_modules/@electric-sql/pglite'
node tests/sql/verify.mjs
node tests/sql/verify_portal.mjs
node tests/sql/verify_a5.mjs
```

Success prints a JSON summary and exits with code 0; a failed assertion exits nonzero.

## Coverage

The harness loads the current schema, applies the migration twice, and exercises
the real PL/pgSQL RPC: successful persistence, ordered stories, image counters,
weekly idempotence, focus consumption, concurrent focus replacement preservation,
atomic rollback, input validation, foreign keys, and function permissions.
The A5 regression applies every migration in lexical order and checks per-story
publication dates/times, manual-day uniqueness, and immutable published groups.

To verify an upgrade, pass an original schema snapshot as the first argument:

```powershell
node tests/sql/verify.mjs C:/path/to/original-supabase-schema.sql
```

## Runtime limits

The test database is in memory and is discarded on exit. No production credentials
or external APIs are used. The bootstrap supplies Supabase role names, `auth.uid()`,
and service-role table grants. It does not reproduce Supabase authentication,
PostgREST, or concurrent worker connections; those need deployment-level checks.
