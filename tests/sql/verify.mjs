import { createDatabase } from './bootstrap.mjs';
import fs from 'node:fs';
import assert from 'node:assert/strict';

const db = await createDatabase();
const migration = fs.readFileSync('migrations/20260915_a2_engine_integration.sql', 'utf8');
const passed = [];
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const scalar = async (sql, args = []) => Object.values((await query(sql, args))[0])[0];
try {
  await db.exec(migration);
  await db.exec(migration);
  assert.equal(await scalar("SELECT count(*)::int FROM information_schema.tables WHERE table_schema='public'"), 9);
  passed.push('migration applies and reapplies unchanged');

  // Supabase supplies service_role grants on pre-existing public tables.
  await db.exec('GRANT USAGE ON SCHEMA public TO service_role, anon, authenticated; GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;');
  const agency = await scalar("INSERT INTO agencies(name,slug) VALUES ('Test','test') RETURNING id");
  const client = await scalar("INSERT INTO clients(agency_id,name,weekly_focus,weekly_focus_expires_at,generation_error,generation_error_at) VALUES ($1,'Test','focus','2026-09-21','old error',now()) RETURNING id", [agency]);
  const stories = Array.from({length:4}, (_, i) => ({text:`Story ${i+1}`,image_url:`https://edited/${i}`,image_original_url:`https://raw/${i}`,agregar_cta:i===3}));
  const images = Array.from({length:4}, (_, i) => ({drive_file_id:`drive-${i}`,drive_file_name:`image-${i}.jpg`}));
  const rpc = async (week, storyInput=stories, imageInput=images, focus='focus', expiry='2026-09-21', clientId=client) => scalar('SELECT public.persist_generated_thread($1::uuid,$2::date,$2::date,$3::time,$4::jsonb,$5::jsonb,$6::text,$7::date)', [clientId,week,'09:00',JSON.stringify(storyInput),JSON.stringify(imageInput),focus,expiry]);
  await db.exec('SET ROLE service_role');
  const first = await rpc('2026-09-21');
  const rows = await query('SELECT "order",text,image_url,image_original_url,fecha_publicacion::text,estado,agregar_cta FROM stories WHERE story_group_id=$1 ORDER BY "order"',[first]);
  assert.equal(rows.length,4);
  assert.deepEqual(rows.map(x=>x.order),[1,2,3,4]);
  assert.deepEqual(rows.map(x=>x.text),stories.map(x=>x.text));
  assert.ok(rows.every(x=>x.estado==='pendiente' && x.fecha_publicacion==='2026-09-21'));
  assert.deepEqual(rows.map(x=>x.agregar_cta),[false,false,false,true]);
  assert.deepEqual(await query('SELECT weekly_focus,weekly_focus_expires_at,generation_error,generation_error_at FROM clients WHERE id=$1',[client]),[{weekly_focus:null,weekly_focus_expires_at:null,generation_error:null,generation_error_at:null}]);
  assert.equal(await scalar('SELECT count(*)::int FROM client_images WHERE client_id=$1 AND times_used=1 AND last_used_at IS NOT NULL',[client]),4);
  passed.push('service_role RPC persists group/four ordered stories, URLs, CTA, counters and clears consumed focus/error');

  assert.equal(await rpc('2026-09-21'),first);
  assert.equal(await scalar('SELECT count(*)::int FROM story_groups WHERE client_id=$1',[client]),1);
  assert.equal(await scalar('SELECT sum(times_used)::int FROM client_images WHERE client_id=$1',[client]),4);
  passed.push('duplicate weekly invocation returns prior group without duplicate stories/counter increments');

  await query("UPDATE clients SET weekly_focus='replacement',weekly_focus_expires_at='2026-10-01' WHERE id=$1",[client]);
  await rpc('2026-09-28');
  assert.equal(await scalar('SELECT min(times_used)::int FROM client_images WHERE client_id=$1',[client]),2);
  assert.equal(await scalar('SELECT weekly_focus FROM clients WHERE id=$1',[client]),'replacement');
  passed.push('later week increments existing images and preserves concurrently replaced focus');

  await query("UPDATE clients SET weekly_focus='focus',weekly_focus_expires_at='2026-10-01',generation_error='still present' WHERE id=$1",[client]);
  const broken = structuredClone(stories);
  delete broken[3].image_original_url;
  await assert.rejects(rpc('2026-10-05',broken),/Every story requires/);
  assert.equal(await scalar('SELECT count(*)::int FROM story_groups WHERE client_id=$1',[client]),2);
  assert.equal(await scalar('SELECT count(*)::int FROM stories WHERE client_id=$1',[client]),8);
  assert.equal(await scalar('SELECT sum(times_used)::int FROM client_images WHERE client_id=$1',[client]),8);
  assert.equal(await scalar('SELECT generation_error FROM clients WHERE id=$1',[client]),'still present');
  assert.equal(await scalar('SELECT weekly_focus FROM clients WHERE id=$1',[client]),'focus');
  passed.push('late fourth-story failure rolls back partial group/stories and preserves counters/focus/error');

  await rpc('2026-10-05');
  assert.equal(await scalar('SELECT weekly_focus FROM clients WHERE id=$1',[client]),'focus');
  passed.push('same focus text with changed expiration survives');
  await query('UPDATE clients SET weekly_focus_expires_at=NULL WHERE id=$1',[client]);
  await rpc('2026-10-12',stories,images,'focus',null);
  assert.equal(await scalar('SELECT weekly_focus FROM clients WHERE id=$1',[client]),null);
  passed.push('matching focus with NULL expiration clears');

  await assert.rejects(rpc('2026-10-19',stories,[images[0],images[0],images[2],images[3]]),/distinct named Drive/);
  await assert.rejects(rpc('2026-10-19',stories.slice(0,3)),/Expected four/);
  await assert.rejects(rpc('2026-10-19',stories,images,null,null,'00000000-0000-0000-0000-000000000000'),/query returned no rows/);
  await assert.rejects(query("INSERT INTO client_images(client_id,drive_file_id,drive_file_name) VALUES ('00000000-0000-0000-0000-000000000000','missing','missing')"),/foreign key/);
  passed.push('malformed arrays/duplicate images/missing client/FKs rejected');

  await db.exec('RESET ROLE');
  const signature='public.persist_generated_thread(uuid,date,date,time,jsonb,jsonb,text,date)';
  for (const role of ['anon','authenticated']) {
    assert.equal(await scalar('SELECT has_function_privilege($1,$2,\'EXECUTE\')',[role,signature]),false);
    await db.exec(`SET ROLE ${role}`);
    await assert.rejects(rpc('2026-10-19'),/permission denied for function/);
    await db.exec('RESET ROLE');
  }
  assert.equal(await scalar("SELECT has_function_privilege('service_role',$1,'EXECUTE')",[signature]),true);
  passed.push('anon/authenticated execution denied, service_role allowed');
  const secured=await query("SELECT relname,relrowsecurity FROM pg_class WHERE relname IN ('client_images','employee_clients','prompt_history') ORDER BY relname");
  assert.ok(secured.every(x=>x.relrowsecurity));
  passed.push('all new tables have RLS enabled');

  console.log(JSON.stringify({runtime:await scalar('SELECT version()'),checks:passed.length,passed},null,2));
} finally {
  await db.close();
}
