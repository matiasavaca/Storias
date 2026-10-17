import { createDatabase } from './bootstrap.mjs';
import fs from 'node:fs';
import assert from 'node:assert/strict';

const db = await createDatabase();
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const scalar = async (sql, args = []) => Object.values((await query(sql, args))[0])[0];
try {
  await db.exec(fs.readFileSync('migrations/20260915_a2_engine_integration.sql', 'utf8'));
  const migration = fs.readFileSync('migrations/20260915_a4_portal_cancelled_stories.sql', 'utf8');
  await db.exec(migration);
  await db.exec(migration);
  await db.exec('GRANT USAGE ON SCHEMA public TO service_role; GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;');
  const agency = await scalar("INSERT INTO agencies(name,slug) VALUES ('Test','portal-test') RETURNING id");
  const employee = await scalar("INSERT INTO employees(agency_id,email,name) VALUES ($1,'pm@example.com','PM') RETURNING id", [agency]);
  const client = await scalar("INSERT INTO clients(agency_id,name,business_description,topics) VALUES ($1,'Client','old','[\"old\"]') RETURNING id", [agency]);
  const group = await scalar("INSERT INTO story_groups(client_id,agency_id,scheduled_date) VALUES ($1,$2,'2026-09-22') RETURNING id", [client, agency]);
  const ids = [];
  for (let order = 1; order <= 3; order++) {
    ids.push(await scalar('INSERT INTO stories(story_group_id,client_id,"order",text,estado) VALUES ($1,$2,$3,$4,\'pendiente\') RETURNING id', [group, client, order, `Story ${order}`]));
  }
  // Cancelling the middle item leaves a hidden order gap. Reordering the two
  // visible stories must resequence the cancelled row after them atomically.
  await query("UPDATE stories SET estado='cancelada' WHERE id=$1", [ids[1]]);
  assert.equal(await scalar('SELECT estado FROM stories WHERE id=$1', [ids[1]]), 'cancelada');
  await db.exec('SET ROLE service_role');
  const changed = await scalar('SELECT public.update_client_prompt($1::uuid,$2::uuid,$3::uuid,$4::jsonb)', [
    client, employee, agency, JSON.stringify({business_description: 'new', topics: ['new']}),
  ]);
  assert.equal(changed.business_description, 'new');
  assert.deepEqual(await query('SELECT field,old_value,new_value FROM prompt_history WHERE client_id=$1 ORDER BY field', [client]), [
    {field: 'business_description', old_value: 'old', new_value: 'new'},
    {field: 'topics', old_value: '["old"]', new_value: '["new"]'},
  ]);
  await query('SELECT public.reorder_stories($1::jsonb)', [JSON.stringify([
    {story_id: ids[0], new_order: 2}, {story_id: ids[2], new_order: 1},
  ])]);
  assert.deepEqual(await query('SELECT id,"order" FROM stories ORDER BY "order"'), [
    {id: ids[2], order: 1}, {id: ids[0], order: 2}, {id: ids[1], order: 3},
  ]);
  await db.exec('RESET ROLE');
  assert.equal(await scalar("SELECT has_function_privilege('authenticated','public.reorder_stories(jsonb)','EXECUTE')"), false);
  assert.equal(await scalar("SELECT has_function_privilege('authenticated','public.update_client_prompt(uuid,uuid,uuid,jsonb)','EXECUTE')"), false);
  console.log(JSON.stringify({checks: 4, passed: ['cancelled state', 'atomic prompt update/audit', 'atomic swap', 'RPC permissions']}, null, 2));
} finally {
  await db.close();
}
