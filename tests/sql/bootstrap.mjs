import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const packageRoot = process.env.PGLITE_PACKAGE_ROOT;
if (!packageRoot) {
  throw new Error('Set PGLITE_PACKAGE_ROOT to the isolated @electric-sql/pglite directory; see tests/sql/README.md.');
}
const { PGlite } = await import(pathToFileURL(path.join(packageRoot, 'dist/index.js')));
const { uuid_ossp } = await import(pathToFileURL(path.join(packageRoot, 'dist/contrib/uuid_ossp.js')));

export async function createDatabase() {
  const db = new PGlite({ extensions: { uuid_ossp } });
  await db.exec(`
    CREATE ROLE anon;
    CREATE ROLE authenticated;
    CREATE ROLE service_role BYPASSRLS;
    CREATE SCHEMA auth;
    CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
      AS 'SELECT NULL::uuid';
  `);
  // Optional baseline path exercises upgrades from an earlier schema snapshot.
  await db.exec(fs.readFileSync(process.argv[2] || 'supabase_schema.sql', 'utf8'));
  return db;
}

export function migrationFiles({ from = '', through = '' } = {}) {
  return fs.readdirSync('migrations')
    .filter((name) => name.endsWith('.sql'))
    .filter((name) => !from || name >= from)
    .filter((name) => !through || name <= through)
    .sort()
    .map((name) => path.join('migrations', name));
}

export async function applyMigrations(db, options = {}) {
  const files = migrationFiles(options);
  for (const file of files) {
    await db.exec(fs.readFileSync(file, 'utf8'));
  }
  return files;
}
