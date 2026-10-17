import assert from 'node:assert/strict';
import { applyMigrations, createDatabase } from './bootstrap.mjs';

const db = await createDatabase();
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const scalar = async (sql, args = []) => Object.values((await query(sql, args))[0])[0];
const passed = [];

try {
  const beforeInvariant = await applyMigrations(db, { through: '20260918_a5_story_font_choice.sql' });
  const legacyAgency = await scalar("INSERT INTO agencies(name,slug) VALUES ('Legacy A5','legacy-a5') RETURNING id");
  const legacyClient = await scalar("INSERT INTO clients(agency_id,name) VALUES ($1,'Legacy Client') RETURNING id", [legacyAgency]);
  const legacyCanonical = await scalar(
    "INSERT INTO story_groups(client_id,agency_id,scheduled_date,scheduled_time,status,agendado,descripcion,created_at) VALUES ($1,$2,'2026-09-30','09:00','pending',true,'Canonical','2026-09-01') RETURNING id",
    [legacyClient, legacyAgency],
  );
  const legacyDuplicate = await scalar(
    "INSERT INTO story_groups(client_id,agency_id,scheduled_date,scheduled_time,status,agendado,descripcion,created_at) VALUES ($1,$2,'2026-09-30','18:00','pending',false,'Keep me','2026-09-02') RETURNING id",
    [legacyClient, legacyAgency],
  );
  const legacyStory = await scalar(
    "INSERT INTO stories(story_group_id,client_id,\"order\",text,estado,fecha_publicacion,hora_publicacion) VALUES ($1,$2,1,'Legacy story','pendiente','2026-09-30','18:00') RETURNING id",
    [legacyDuplicate, legacyClient],
  );
  const legacyScheduledStory = await scalar(
    "INSERT INTO stories(story_group_id,client_id,\"order\",text,estado,fecha_publicacion,hora_publicacion) VALUES ($1,$2,1,'Already scheduled','pendiente','2026-09-30','09:00') RETURNING id",
    [legacyCanonical, legacyClient],
  );
  const invariantMigrations = await applyMigrations(db, { from: '20260922_a5_fix_database_invariants.sql' });
  const applied = [...beforeInvariant, ...invariantMigrations];
  assert.ok(applied.some((file) => file.endsWith('20260917_a5_publish_hour.sql')));
  assert.ok(applied.some((file) => file.endsWith('20260917_a5_spread_weekly_stories.sql')));
  assert.ok(applied.some((file) => file.endsWith('20260922_a5_fix_database_invariants.sql')));
  assert.ok(applied.some((file) => file.endsWith('20260923_a5_atomic_manual_group_cleanup.sql')));
  assert.ok(applied.some((file) => file.endsWith('20260924_a5_story_schedule_state.sql')));
  assert.ok(applied.some((file) => file.endsWith('20260928_a6_publish_together.sql')));
  assert.ok(applied.some((file) => file.endsWith('20261002_a18_health_dashboard.sql')));
  passed.push('all migrations apply in lexical order');

  assert.deepEqual(
    await query("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='clients' AND column_name='pool_bajo_at'"),
    [{ column_name: 'pool_bajo_at', data_type: 'timestamp with time zone', is_nullable: 'YES' }],
  );
  passed.push('pool_bajo_at supports the agency health signal');

  assert.deepEqual(
    await query("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='clients' AND column_name='publish_together'"),
    [{ column_name: 'publish_together', data_type: 'boolean', is_nullable: 'NO', column_default: 'false' }],
  );
  assert.equal(await scalar('SELECT publish_together FROM clients WHERE id=$1', [legacyClient]), false);
  passed.push('publish_together is opt-in and defaults existing clients to false');

  assert.deepEqual(
    await query(
      'SELECT id, manual_duplicate_of, scheduled_time::text, descripcion FROM story_groups WHERE id = ANY($1::uuid[]) ORDER BY created_at',
      [[legacyCanonical, legacyDuplicate]],
    ),
    [
      { id: legacyCanonical, manual_duplicate_of: null, scheduled_time: '09:00:00', descripcion: 'Canonical' },
      { id: legacyDuplicate, manual_duplicate_of: legacyCanonical, scheduled_time: '18:00:00', descripcion: 'Keep me' },
    ],
  );
  assert.deepEqual(
    await query('SELECT id, story_group_id, "order", text, estado, fecha_publicacion::text, hora_publicacion::text FROM stories WHERE id=$1', [legacyStory]),
    [{ id: legacyStory, story_group_id: legacyDuplicate, order: 1, text: 'Legacy story', estado: 'pendiente', fecha_publicacion: '2026-09-30', hora_publicacion: '18:00:00' }],
  );
  await assert.rejects(
    query("INSERT INTO story_groups(client_id,agency_id,scheduled_date) VALUES ($1,$2,'2026-09-30')", [legacyClient, legacyAgency]),
    /unique constraint|duplicate key/i,
  );
  passed.push('legacy duplicate manual groups are quarantined without changing stories or metadata');

  assert.equal(await scalar('SELECT agendado FROM stories WHERE id=$1', [legacyScheduledStory]), true);
  assert.equal(await scalar('SELECT agendado FROM stories WHERE id=$1', [legacyStory]), false);
  passed.push('legacy scheduled groups backfill per-story schedule state');

  await db.exec('GRANT USAGE ON SCHEMA public TO service_role; GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;');
  const agency = await scalar("INSERT INTO agencies(name,slug) VALUES ('A5 Test','a5-test') RETURNING id");
  const client = await scalar("INSERT INTO clients(agency_id,name) VALUES ($1,'Client') RETURNING id", [agency]);
  const stories = [
    ['2026-09-21', '08:15'],
    ['2026-09-23', '09:30'],
    ['2026-09-25', '11:45'],
    ['2026-09-27', '18:00'],
  ].map(([fecha_publicacion, hora_publicacion], index) => ({
    text: `Story ${index + 1}`,
    image_url: `https://edited/${index}`,
    image_original_url: `https://raw/${index}`,
    fecha_publicacion,
    hora_publicacion,
  }));
  const images = Array.from({ length: 4 }, (_, index) => ({
    drive_file_id: `drive-${index}`,
    drive_file_name: `image-${index}.jpg`,
  }));

  await db.exec('SET ROLE service_role');
  const group = await scalar(
    'SELECT public.persist_generated_thread($1::uuid,$2::date,$3::date,$4::time,$5::jsonb,$6::jsonb,NULL,NULL)',
    [client, '2026-09-21', '2026-09-21', '09:00', JSON.stringify(stories), JSON.stringify(images)],
  );
  assert.deepEqual(
    await query('SELECT fecha_publicacion::text, hora_publicacion::text, agendado FROM stories WHERE story_group_id=$1 ORDER BY "order"', [group]),
    stories.map((story) => ({ fecha_publicacion: story.fecha_publicacion, hora_publicacion: `${story.hora_publicacion}:00`, agendado: false })),
  );
  passed.push('generated stories preserve each publication date and time');

  const fallbackGroup = await scalar(
    'SELECT public.persist_generated_thread($1::uuid,$2::date,$3::date,$4::time,$5::jsonb,$6::jsonb,NULL,NULL)',
    [client, '2026-09-28', '2026-09-28', '07:20', JSON.stringify(stories.map(({ hora_publicacion, ...story }) => story)), JSON.stringify(images)],
  );
  assert.equal(
    await scalar('SELECT count(*)::int FROM stories WHERE story_group_id=$1 AND hora_publicacion=$2::time', [fallbackGroup, '07:20']),
    4,
  );
  passed.push('missing per-story time falls back to the group schedule');

  const manualGroup = await scalar(
    "INSERT INTO story_groups(client_id,agency_id,scheduled_date) VALUES ($1,$2,'2026-10-01') RETURNING id",
    [client, agency],
  );
  await assert.rejects(
    query("INSERT INTO story_groups(client_id,agency_id,scheduled_date) VALUES ($1,$2,'2026-10-01') RETURNING id", [client, agency]),
    /unique constraint|duplicate key/i,
  );
  assert.ok(manualGroup);
  passed.push('manual groups are unique per client and date');

  const emptyReservation = await scalar(
    "INSERT INTO story_groups(client_id,agency_id,scheduled_date,status) VALUES ($1,$2,'2026-10-02','pending') RETURNING id",
    [client, agency],
  );
  assert.equal(
    await scalar('SELECT public.delete_empty_manual_group($1::uuid)', [emptyReservation]),
    true,
  );
  assert.equal(await scalar('SELECT count(*)::int FROM story_groups WHERE id=$1', [emptyReservation]), 0);

  const occupiedReservation = await scalar(
    "INSERT INTO story_groups(client_id,agency_id,scheduled_date,status) VALUES ($1,$2,'2026-10-03','pending') RETURNING id",
    [client, agency],
  );
  const concurrentStory = await scalar(
    "INSERT INTO stories(story_group_id,client_id,\"order\",text,estado) VALUES ($1,$2,1,'Concurrent story','pendiente') RETURNING id",
    [occupiedReservation, client],
  );
  assert.equal(
    await scalar('SELECT public.delete_empty_manual_group($1::uuid)', [occupiedReservation]),
    false,
  );
  assert.equal(await scalar('SELECT count(*)::int FROM story_groups WHERE id=$1', [occupiedReservation]), 1);
  assert.equal(await scalar('SELECT count(*)::int FROM stories WHERE id=$1', [concurrentStory]), 1);
  passed.push('manual reservation cleanup is atomic and preserves an occupied group');

  for (const [index, lockedState] of ['publicando', 'publicado'].entries()) {
    const publicationDate = `2026-10-${String(5 + index).padStart(2, '0')}`;
    const lockedGroup = await scalar(
      'INSERT INTO story_groups(client_id,agency_id,scheduled_date,generation_week) VALUES ($1,$2,$3,$3) RETURNING id',
      [client, agency, publicationDate],
    );
    const lockedIds = [];
    for (let order = 1; order <= 2; order++) {
      lockedIds.push(await scalar(
        'INSERT INTO stories(story_group_id,client_id,"order",text,estado) VALUES ($1,$2,$3,$4,$5) RETURNING id',
        [lockedGroup, client, order, `Locked ${order}`, order === 1 ? lockedState : 'pendiente'],
      ));
    }
    await assert.rejects(
      query('SELECT public.reorder_stories($1::jsonb)', [JSON.stringify([
        { story_id: lockedIds[0], new_order: 2 },
        { story_id: lockedIds[1], new_order: 1 },
      ])]),
      /cannot be reordered/i,
    );
  }
  passed.push('groups containing publishing or published stories cannot be reordered');

  console.log(JSON.stringify({ checks: passed.length, passed }, null, 2));
} finally {
  await db.close();
}
