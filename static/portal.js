(() => {
  'use strict';
  const state = { clients: [], client: null, groups: [], driveCount: undefined, editingStory: null, selectedClientId: null, selectionVersion: 0, clientListVersion: 0, teams: [], me: null };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'})[char]);
  function avatarColor(id) { let hash = 0; for (const ch of String(id)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0; return hash % 6; }

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', headers: {'Content-Type':'application/json', ...(options.headers || {})}, ...options});
    if (response.status === 401) { window.location.assign('/login'); throw new Error('Sesión vencida'); }
    if (response.status === 403) { showMessage('No tenés permiso para acceder a este contenido.', true); throw new Error('Acceso denegado'); }
    if (!response.ok) {
      let detail = 'No se pudo completar la operación.';
      try { detail = (await response.json()).detail || detail; } catch (_) { /* no JSON response */ }
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }
  function showMessage(text, error = false) { $('message').textContent = text; $('message').className = `notice${error ? ' error' : ''}`; }
  function clearMessage() { $('message').className = 'notice hidden'; }
  function initials(name) { return String(name || '?').split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase(); }
  function setControlsDisabled(disabled) { ['save-description','save-focus','try-prompt','save-story'].forEach((id) => { $(id).disabled = disabled; }); }
  function driveUrl(folderId) { return folderId ? `https://drive.google.com/drive/folders/${encodeURIComponent(folderId)}` : null; }
  function clearSelection() {
    state.selectionVersion += 1; state.selectedClientId = null; state.client = null; state.groups = []; state.editingStory = null;
    $('client-view').classList.add('hidden'); $('empty').classList.remove('hidden'); $('empty').textContent = 'Seleccioná un cliente para gestionar su contenido.';
    $('header-client').classList.add('hidden'); $('header-default').classList.remove('hidden'); $('drive-link').classList.add('hidden');
  }

  async function loadMeAndTeams() {
    try {
      const [me, teams] = await Promise.all([api('/portal/me'), api('/portal/equipos')]);
      state.me = me; state.teams = teams;
      $('client-team').innerHTML = '<option value="">Sin equipo</option>' + teams.map((team) => `<option value="${escapeHtml(team.id)}">${escapeHtml(team.name)}</option>`).join('');
      $('me-avatar').textContent = initials(me.name || me.email); $('me-name').textContent = me.name || me.email;
      $('me-role').textContent = me.role === 'admin' ? 'Administrador' : 'Empleado'; $('me-card').classList.remove('hidden');
    } catch (error) { /* non-fatal: the sidebar just falls back to a flat, ungrouped list */ }
  }
  function teamName(teamId) { const team = state.teams.find((item) => item.id === teamId); return team ? team.name : 'Sin equipo'; }
  async function createTeam() {
    const name = window.prompt('Nombre del equipo nuevo:');
    if (!name || !name.trim()) return;
    try {
      const team = await api('/portal/equipos', {method:'POST', body:JSON.stringify({name:name.trim()})});
      state.teams.push(team); state.teams.sort((a,b)=>a.name.localeCompare(b.name,'es'));
      $('client-team').innerHTML = '<option value="">Sin equipo</option>' + state.teams.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
      renderClients(); showMessage('Equipo creado.');
    } catch(error) { showMessage(error.message, true); }
  }

  async function loadClients() {
    clearMessage(); $('client-list').textContent = 'Cargando...';
    const listVersion = ++state.clientListVersion;
    const suffix = $('only-mine').checked ? '?solo_mios=true' : '';
    try {
      const clients = await api(`/portal/clientes${suffix}`);
      if (listVersion !== state.clientListVersion) return;
      state.clients = clients; renderClients();
      const selectionStillVisible = state.selectedClientId && clients.some((client) => client.id === state.selectedClientId);
      if (!selectionStillVisible) {
        clearSelection(); renderClients();
        if (clients.length) await selectClient(clients[0].id);
      }
    } catch (error) {
      if (listVersion !== state.clientListVersion) return;
      $('client-list').textContent = 'No se pudieron cargar los clientes.';
      if (!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
    }
  }
  function renderClients() {
    if (!state.clients.length) { $('client-list').textContent = 'No hay clientes disponibles.'; return; }
    const byTeam = new Map();
    for (const client of state.clients) {
      const key = client.team_id || '';
      if (!byTeam.has(key)) byTeam.set(key, []);
      byTeam.get(key).push(client);
    }
    const myTeam = state.me?.team_id || '';
    const keys = [...byTeam.keys()].sort((a, b) => {
      if (a === b) return 0;
      if (myTeam && a === myTeam) return -1;
      if (myTeam && b === myTeam) return 1;
      if (a === '') return 1;
      if (b === '') return -1;
      return teamName(a).localeCompare(teamName(b), 'es');
    });
    $('client-list').innerHTML = keys.map((key) => {
      const cards = byTeam.get(key).map((client) => {
        const active = state.client?.id === client.id;
        const count = client.stories_count ?? 0;
        const countLabel = `${count} historia${count === 1 ? '' : 's'}${active ? ' · Esta semana' : ''}`;
        return `<button class="client-item${active ? ' active' : ''}" data-client-id="${escapeHtml(client.id)}"><span class="avatar avatar-${avatarColor(client.id)}">${escapeHtml(initials(client.name))}</span><span class="meta"><span class="name">${escapeHtml(client.name)}</span><span class="count">${escapeHtml(countLabel)}</span></span></button>`;
      }).join('');
      return `<div class="team-group"><h4 class="team-label">${escapeHtml(key ? teamName(key) : 'Sin equipo')}</h4>${cards}</div>`;
    }).join('');
  }
  async function selectClient(clientId) {
    const selectionVersion = ++state.selectionVersion;
    state.selectedClientId = clientId; state.client = null; state.groups = []; state.editingStory = null; setControlsDisabled(true);
    if ($('story-dialog').open) $('story-dialog').close();
    clearMessage(); $('empty').classList.add('hidden'); $('client-view').classList.remove('hidden');
    $('header-default').classList.add('hidden'); $('header-client').classList.remove('hidden');
    $('client-name').textContent = 'Cargando...'; $('stories').textContent = 'Cargando...'; $('week-badge').classList.add('hidden');
    $('activity-list').innerHTML = ''; $('activity-summary').innerHTML = ''; $('header-tags').innerHTML = ''; $('drive-link').classList.add('hidden');
    $('plan-panel').classList.add('hidden'); state.driveCount = undefined;
    try {
      const [client, groups, driveInfo] = await Promise.all([
        api(`/portal/clientes/${encodeURIComponent(clientId)}`),
        api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`),
        api(`/portal/clientes/${encodeURIComponent(clientId)}/drive-info`).catch(() => ({count: null})),
      ]);
      if (selectionVersion !== state.selectionVersion || clientId !== state.selectedClientId) return;
      state.client = client; state.groups = groups; state.driveCount = driveInfo?.count ?? null;
      renderClients(); renderClient();
    } catch (error) {
      if (selectionVersion === state.selectionVersion) {
        $('stories').textContent = '';
        if (!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
      }
    } finally {
      if (selectionVersion === state.selectionVersion) setControlsDisabled(false);
    }
  }
  function setFieldMode(name, editing) {
    $(`${name}-view`).classList.toggle('hidden', editing);
    $(`${name}-edit`).classList.toggle('hidden', !editing);
    $(`${name}-view-actions`).classList.toggle('hidden', editing);
    $(`${name}-edit-actions`).classList.toggle('hidden', !editing);
  }
  function updateFieldView(name, value, emptyPlaceholder) {
    $(`${name}-text`).textContent = value || emptyPlaceholder;
    $(`${name}-view`).classList.toggle('empty', !value);
  }
  function renderClient() {
    $('client-name').textContent = state.client.name; $('client-avatar').textContent = initials(state.client.name);
    $('business-description').value = state.client.business_description || ''; $('weekly-focus').value = state.client.weekly_focus || '';
    $('desc-count').textContent = String($('business-description').value.length); $('focus-count').textContent = String($('weekly-focus').value.length);
    updateFieldView('description', state.client.business_description, 'Todavía no hay descripción. Hacé click en Editar para agregarla.');
    updateFieldView('focus', state.client.weekly_focus, 'Sin enfoque puntual para esta semana.');
    setFieldMode('description', false); setFieldMode('focus', false);
    $('client-team').value = state.client.team_id || '';
    $('gen-dot').className = `gen-dot${state.client.generation_error ? ' warn' : ''}`;
    $('header-tags').innerHTML = (state.client.topics || []).slice(0, 4).map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join('');
    const url = driveUrl(state.client.drive_folder_id);
    if (url) { $('drive-link').href = url; $('drive-link').classList.remove('hidden'); $('qa-drive').href = url; $('qa-drive').classList.remove('hidden'); }
    else { $('drive-link').classList.add('hidden'); $('qa-drive').classList.add('hidden'); }
    $('prompt-preview').classList.add('hidden'); renderStories(); renderPlan(); renderActivity(); loadCalendar();
  }
  function dayLabel(isoDate) {
    return isoDate ? new Intl.DateTimeFormat('es-AR', {weekday:'short', day:'numeric', timeZone:'UTC'}).format(new Date(`${isoDate}T00:00:00Z`)) : '';
  }
  function activeGroup() {
    // The nearest upcoming group by date (state.groups is date-sorted by the
    // backend) — used only for the week-badge/activity summary.
    return state.groups[0];
  }
  function activeDates() {
    // Every date covered by the nearest group, plus any date the employee has
    // clicked on the calendar this session — these render as editable rows in
    // "Historias generadas". Everything else is just "scheduled" and shows as
    // a compact preview in "Plan de la próxima semana" instead.
    const dates = new Set();
    const group = state.groups[0];
    if (group) {
      for (const story of (group.stories || [])) if (story.fecha_publicacion) dates.add(story.fecha_publicacion);
      if (!dates.size && group.scheduled_date) dates.add(group.scheduled_date);
    }
    for (const iso of draftDates) dates.add(iso);
    return dates;
  }
  function renderPlan() {
    $('plan-panel').classList.remove('hidden');
    const active = activeDates();
    const items = [];
    for (const group of state.groups) {
      for (const story of (group.stories || [])) if (story.fecha_publicacion && !active.has(story.fecha_publicacion)) items.push(story);
    }
    items.sort((a,b) => a.fecha_publicacion.localeCompare(b.fecha_publicacion) || String(a.hora_publicacion||'').localeCompare(String(b.hora_publicacion||'')));
    if (!items.length) {
      $('plan-range').textContent = '';
      $('plan-days').innerHTML = '<div class="empty">No hay más publicaciones programadas todavía.</div>';
      return;
    }
    const first = items[0].fecha_publicacion, last = items[items.length - 1].fecha_publicacion;
    $('plan-range').textContent = first === last ? dayLabel(first) : `${dayLabel(first)} – ${dayLabel(last)}`;
    $('plan-days').innerHTML = items.map((story) => {
      const title = story.text || 'Sin texto todavía';
      const shortTitle = title.length > 40 ? title.slice(0, 37) + '…' : title;
      const hora = story.hora_publicacion ? String(story.hora_publicacion).slice(0,5) : '';
      return `<div class="plan-chip" data-story-id="${escapeHtml(story.id)}"><span class="grip">⠿</span><span class="thumb">${story.image_url ? `<img src="${escapeHtml(story.image_url)}" alt="">` : '🖼'}</span><div class="plan-chip-body"><div class="date">${escapeHtml(dayLabel(story.fecha_publicacion))}${hora ? ' · ' + hora : ''}</div><div class="title">${escapeHtml(shortTitle)}</div><div class="type">Story única</div></div><div class="plan-chip-actions"><button class="icon-btn" data-action="edit" aria-label="Editar">✎</button><button class="icon-btn" data-action="delete" aria-label="Eliminar">×</button></div></div>`;
    }).join('');
  }
  function groupDate(group) {
    const raw = group.scheduled_date || group.generation_week;
    return raw ? new Intl.DateTimeFormat('es-AR', {dateStyle:'long', timeZone:'UTC'}).format(new Date(`${raw}T00:00:00Z`)) : 'Sin fecha';
  }
  function renderStories() {
    // One row per date: every date is its own horizontal strip of cards ending
    // in a "+" tile, so any day can hold as many images as needed — never just one.
    const active = activeDates();
    const byDate = new Map();
    const manualDates = new Set(); // dates with a manual (non-AI) group — their time is editable inline
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        if (!story.fecha_publicacion || !active.has(story.fecha_publicacion)) continue;
        if (!byDate.has(story.fecha_publicacion)) byDate.set(story.fecha_publicacion, []);
        byDate.get(story.fecha_publicacion).push(story);
        if (!group.generation_week) manualDates.add(story.fecha_publicacion);
      }
    }
    for (const iso of active) if (!byDate.has(iso)) byDate.set(iso, []);
    const dates = [...byDate.keys()].sort();
    if (!dates.length) {
      $('stories').innerHTML = '<div class="empty">No hay historias próximas para este cliente. Clickeá un día del calendario para agregar una.</div>';
      $('week-badge').classList.add('hidden');
      return;
    }
    const first = dates[0], last = dates[dates.length - 1];
    $('week-badge').textContent = first === last ? dayLabel(first) : `${dayLabel(first)} – ${dayLabel(last)}`;
    $('week-badge').classList.remove('hidden');
    const rows = dates.map((iso) => {
      const stories = byDate.get(iso).sort((a,b) => a.order - b.order);
      const cards = stories.map((story,index) => storyCard(story,index,stories.length)).join('');
      const allApproved = stories.length > 0 && stories.every((s) => s.aprobado);
      const statusBadge = allApproved ? '<span class="badge">Agendado</span>' : '';
      const timeEditable = !stories.length || manualDates.has(iso);
      const timeValue = stories.length && stories[0].hora_publicacion ? String(stories[0].hora_publicacion).slice(0,5) : '09:00';
      const timeInput = `<input type="time" class="day-time" data-time-for="${escapeHtml(iso)}" value="${escapeHtml(timeValue)}" ${timeEditable ? '' : 'disabled title="Este día usa el horario de Editar ritmo"'}>`;
      return `<div class="day-row" data-date="${escapeHtml(iso)}"><div class="day-row-head"><span class="section-title">${escapeHtml(dayLabel(iso))}</span>${statusBadge}${timeInput}</div><div class="day-row-cards">${cards}<div class="story add-placeholder" data-add-date="${escapeHtml(iso)}"><span class="add-icon">+</span></div></div></div>`;
    }).join('');
    $('stories').innerHTML = `<section class="group">${rows}</section>`;
  }
  function renderActivity() {
    const next = activeGroup();
    const activeCount = next ? (next.stories || []).length : 0;
    const rows = [];
    if (next) {
      rows.push(`<div class="activity-item"><span class="dot">✓</span><div><div>${activeCount} historia${activeCount===1?'':'s'} lista${activeCount===1?'':'s'}</div><div class="sub">Generadas con la dirección actual</div></div></div>`);
    } else {
      rows.push(`<div class="activity-item"><span class="dot">–</span><div><div>Sin historias programadas</div><div class="sub">Todavía no se generó contenido para este cliente</div></div></div>`);
    }
    if (state.driveCount !== null && state.driveCount !== undefined) {
      rows.push(`<div class="activity-item"><span class="dot">📁</span><div><div>${state.driveCount} imagen${state.driveCount===1?'':'es'} disponible${state.driveCount===1?'':'s'} en Drive</div><div class="sub">De la carpeta del cliente</div></div></div>`);
    }
    if (next) rows.push(`<div class="activity-item"><span class="dot">📅</span><div><div>Próxima publicación: ${escapeHtml(groupDate(next))}${next.scheduled_time ? ' · ' + next.scheduled_time.slice(0,5) + 'hs' : ''}</div><div class="sub">Según el plan generado</div></div></div>`);
    $('activity-list').innerHTML = rows.join('');
    $('activity-summary').innerHTML = state.client.generation_error
      ? `<div class="status-card warn"><span>⚠️</span><div><strong>Necesita atención</strong><p>${escapeHtml(state.client.generation_error)}</p></div></div>`
      : `<div class="status-card ok"><span>✓</span><div><strong>Todo en orden</strong><p>No hay errores de generación pendientes.</p></div></div>`;
  }
  function storyCard(story, index, total, showMove = true) {
    const dateBadge = story.fecha_publicacion ? `<span class="story-date">${escapeHtml(dayLabel(story.fecha_publicacion))}</span>` : '';
    const moveButtons = showMove ? `<button class="icon-btn" data-action="move-left" ${index===0?'disabled':''} aria-label="Mover a la izquierda">←</button><button class="icon-btn" data-action="move-right" ${index===total-1?'disabled':''} aria-label="Mover a la derecha">→</button>` : '';
    const approvedClass = story.aprobado ? ' approved' : '';
    const approvedBadge = story.aprobado ? '<span class="approved-badge" title="Aprobada">✓</span>' : '';
    return `<article class="story${approvedClass}" data-story-id="${escapeHtml(story.id)}">${story.image_url ? `<img src="${escapeHtml(story.image_url)}" alt="Historia ${index+1}">` : ''}<span class="story-num">${index+1}</span>${dateBadge}${approvedBadge}<div class="story-actions">${moveButtons}<button class="icon-btn" data-action="edit" aria-label="Editar">✎</button><button class="icon-btn" data-action="delete" aria-label="Eliminar">×</button></div><div class="story-overlay"><p class="story-text">${escapeHtml(story.text || 'Sin texto todavía')}</p></div></article>`;
  }
  async function saveClientField(field, buttonId) {
    const name = field === 'weekly_focus' ? 'focus' : 'description';
    const button=$(buttonId), input=$(field==='business_description'?'business-description':'weekly-focus'), value=input.value.trim(), clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!clientId) return; button.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}`, {method:'PATCH', body:JSON.stringify({[field]:value || null})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client = updated;
      updateFieldView(name, field==='weekly_focus'?updated.weekly_focus:updated.business_description,
        field==='weekly_focus'?'Sin enfoque puntual para esta semana.':'Todavía no hay descripción. Hacé click en Editar para agregarla.');
      setFieldMode(name, false);
      showMessage(field==='weekly_focus'?'Enfoque semanal guardado.':'Descripción guardada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) button.disabled=false; }
  }
  async function saveClientTeam() {
    const select=$('client-team'), clientId=state.client?.id, selectionVersion=state.selectionVersion, teamId=select.value || null;
    if (!clientId || teamId === (state.client?.team_id || null)) return; select.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/equipo`, {method:'PATCH', body:JSON.stringify({team_id:teamId})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client.team_id = updated.team_id; renderClients(); showMessage('Equipo actualizado.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) { showMessage(error.message,true); select.value = state.client?.team_id || ''; } }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) select.disabled=false; }
  }
  async function tryPrompt() {
    const button=$('try-prompt'), preview=$('prompt-preview'), clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!clientId) return; button.disabled=true; preview.classList.remove('hidden'); preview.textContent='Generando prueba...';
    try {
      const result=await api(`/portal/clientes/${encodeURIComponent(clientId)}/probar-prompt`, {method:'POST'});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      preview.innerHTML=`<ol>${result.historias.map((text)=>`<li>${escapeHtml(text)}</li>`).join('')}</ol>`;
    } catch(error) { if (selectionVersion === state.selectionVersion) { preview.textContent=error.message; preview.classList.add('error'); } }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) button.disabled=false; }
  }
  const CAL_LABELS = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];
  let ritmoDays = []; // [{day, time}], up to 4 — the AI's recurring weekly cadence
  let calMonthOffset = 0;
  let pendingUploadDate = null; // set right before triggering the hidden file input
  let pendingUploadHora = '09:00'; // read from that day's inline time input at the same moment
  let draftDates = new Set(); // ISO dates clicked on the calendar, waiting for an image — shown as empty "+" cards in "Historias generadas"
  function monthBase() { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + calMonthOffset); return d; }
  function isoDate(year, month, day) { return `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`; }
  function renderCalendarMonth() {
    const base = monthBase(), year = base.getFullYear(), month = base.getMonth();
    const monthLabel = base.toLocaleDateString('es-AR', {month:'long', year:'numeric'});
    $('cal-month-label').textContent = monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1);
    const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const cells = Array(firstWeekday).fill(null).concat(Array.from({length: daysInMonth}, (_, i) => i + 1));
    while (cells.length % 7 !== 0) cells.push(null);
    const contentDates = new Set();
    for (const group of state.groups) for (const story of (group.stories || [])) if (story.fecha_publicacion) contentDates.add(story.fecha_publicacion);
    $('calendar-grid').innerHTML = cells.map((day) => {
      if (day === null) return '<div class="cal-cell outside"></div>';
      const iso = isoDate(year, month, day);
      const pending = draftDates.has(iso) && !contentDates.has(iso);
      return `<div class="cal-cell${pending?' pending':''}" data-date="${iso}">${day}${contentDates.has(iso)?'<span class="dot"></span>':''}</div>`;
    }).join('');
  }
  function renderRitmoChips() {
    const activeDays = new Set(ritmoDays.map((e) => e.day));
    $('ritmo-chips').innerHTML = CAL_LABELS.map((label, day) =>
      `<span class="ritmo-chip${activeDays.has(day)?' active':''}" data-day="${day}">${label}</span>`
    ).join('');
  }
  async function loadCalendar() {
    calMonthOffset = 0;
    draftDates = new Set();
    renderCalendarMonth();
    let days = state.client?.publish_days;
    if (!days) { try { days = (await api('/portal/ritmo-default')).publish_days; } catch(_) { days = [{day:0,time:'09:00'},{day:2,time:'09:00'},{day:4,time:'09:00'},{day:6,time:'09:00'}]; } }
    ritmoDays = days.map((d) => ({day: d.day, time: d.time}));
    renderRitmoChips();
  }
  async function toggleRitmoDay(day) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const idx = ritmoDays.findIndex((e) => e.day === day);
    const next = [...ritmoDays];
    if (idx >= 0) next.splice(idx, 1);
    else { if (next.length >= 4) { showMessage('Ya elegiste 4 días — sacá uno para agregar otro.', true); return; } next.push({day, time:'09:00'}); }
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/ritmo`, {method:'PATCH', body:JSON.stringify({publish_days:next})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client.publish_days = updated.publish_days; ritmoDays = updated.publish_days; renderRitmoChips();
      showMessage('Días automáticos actualizados.');
    } catch(error) { showMessage(error.message, true); }
  }
  async function uploadManualImage(iso, hora, file) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(hora)) { showMessage('Hora inválida. Usá el formato HH:MM.', true); return; }
    const formData = new FormData();
    formData.append('fecha_publicacion', iso); formData.append('hora_publicacion', hora); formData.append('image', file);
    try {
      const response = await fetch(`/portal/clientes/${encodeURIComponent(clientId)}/historias/manual`, {method:'POST', credentials:'same-origin', body: formData});
      if (response.status === 401) { window.location.assign('/login'); return; }
      if (!response.ok) { let detail = 'No se pudo subir la imagen.'; try { detail = (await response.json()).detail || detail; } catch(_) {} throw new Error(detail); }
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      const groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.groups = groups; draftDates.add(iso); // keep the row open so more images can be added
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage('Imagen agregada.');
    } catch(error) { showMessage(error.message, true); }
  }
  async function toggleApproval(story) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const next = !story.aprobado;
    try {
      const updated = await api(`/portal/historias/${encodeURIComponent(story.id)}/aprobar`, {method:'PATCH', body:JSON.stringify({aprobado: next})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      Object.assign(story, updated);
      renderStories(); renderPlan();
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true); }
  }
  async function updateDayTime(iso, hhmm) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId || !/^([01]\d|2[0-3]):[0-5]\d$/.test(hhmm)) return;
    const hasStories = state.groups.some((group) => (group.stories||[]).some((story) => story.fecha_publicacion === iso));
    if (!hasStories) return; // empty row: the chosen time is just read from the input at upload time
    try {
      await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias/manual/${encodeURIComponent(iso)}/hora`, {method:'PATCH', body:JSON.stringify({hora_publicacion:hhmm})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      const groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.groups = groups;
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage('Hora actualizada.');
    } catch(error) { showMessage(error.message, true); }
  }
  async function openHistory() {
    const clientId = state.client?.id; if (!clientId) return;
    $('history-list').textContent = 'Cargando...'; $('history-dialog').showModal();
    try {
      const rows = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historial`);
      $('history-list').innerHTML = rows.length ? rows.map((row) => `<div class="history-row"><div class="field">${escapeHtml(row.field)}</div><div class="meta">${row.changed_by_name ? escapeHtml(row.changed_by_name)+' · ' : ''}${new Date(row.changed_at).toLocaleString('es-AR')}</div><div class="diff"><span class="old">${escapeHtml(row.old_value || '(vacío)')}</span><span>${escapeHtml(row.new_value || '(vacío)')}</span></div></div>`).join('') : '<div class="empty">Todavía no hay cambios registrados para este cliente.</div>';
    } catch (error) { $('history-list').textContent = error.message; }
  }
  function findStory(storyId) { for (const group of state.groups) { const story=(group.stories||[]).find((item)=>item.id===storyId); if(story) return {group,story}; } return null; }
  function openStory(story) { state.editingStory=story; $('story-text').value=story.text || ''; $('story-dialog').showModal(); }
  async function saveStory() {
    const button=$('save-story'), textoNuevo=$('story-text').value.trim(), story=state.editingStory, clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if(!textoNuevo || !story || !clientId)return; button.disabled=true;
    try {
      const updated=await api(`/portal/historias/${encodeURIComponent(story.id)}`, {method:'PATCH', body:JSON.stringify({texto_nuevo:textoNuevo})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id || story !== state.editingStory) return;
      Object.assign(story,updated); $('story-dialog').close(); renderStories(); renderPlan(); showMessage('Historia actualizada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
    finally { if (selectionVersion === state.selectionVersion) button.disabled=false; }
  }
  async function moveStory(group, story, direction) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion, stories=[...group.stories].sort((a,b)=>a.order-b.order), index=stories.findIndex((item)=>item.id===story.id), target=index+direction; if(!clientId||target<0||target>=stories.length)return;
    [stories[index],stories[target]]=[stories[target],stories[index]];
    const historias=stories.map((item,position)=>({story_id:item.id,nuevo_order:position+1}));
    try { await api('/portal/historias/reordenar',{method:'PATCH',body:JSON.stringify({historias})}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; stories.forEach((item,position)=>{item.order=position+1;}); group.stories=stories; renderStories(); renderPlan(); showMessage('Orden actualizado.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  async function deleteStory(group, story) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion; if(!clientId||!window.confirm('¿Cancelar esta historia?'))return;
    try { await api(`/portal/historias/${encodeURIComponent(story.id)}`,{method:'DELETE'}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; group.stories=group.stories.filter((item)=>item.id!==story.id); renderStories(); renderPlan(); renderActivity(); showMessage('Historia cancelada.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  $('client-list').addEventListener('click',(event)=>{const item=event.target.closest('[data-client-id]');if(item)selectClient(item.dataset.clientId);});
  $('only-mine').addEventListener('change',loadClients);
  $('save-description').addEventListener('click',()=>saveClientField('business_description','save-description'));
  $('save-focus').addEventListener('click',()=>saveClientField('weekly_focus','save-focus'));
  $('try-prompt').addEventListener('click',tryPrompt);
  $('client-team').addEventListener('change',saveClientTeam);
  $('add-team').addEventListener('click',createTeam);
  $('business-description').addEventListener('input',()=>{$('desc-count').textContent=String($('business-description').value.length);});
  $('weekly-focus').addEventListener('input',()=>{$('focus-count').textContent=String($('weekly-focus').value.length);});
  $('edit-description').addEventListener('click',()=>{setFieldMode('description',true); $('business-description').focus();});
  $('cancel-description').addEventListener('click',()=>{$('business-description').value=state.client?.business_description || ''; $('desc-count').textContent=String($('business-description').value.length); setFieldMode('description',false);});
  $('edit-focus').addEventListener('click',()=>{setFieldMode('focus',true); $('weekly-focus').focus();});
  $('cancel-focus').addEventListener('click',()=>{$('weekly-focus').value=state.client?.weekly_focus || ''; $('focus-count').textContent=String($('weekly-focus').value.length); setFieldMode('focus',false);});
  $('content-panel-toggle').addEventListener('click',()=>$('content-panel').classList.toggle('collapsed'));
  $('qa-history').addEventListener('click',openHistory);
  $('close-history').addEventListener('click',()=>$('history-dialog').close());
  $('close-history-2').addEventListener('click',()=>$('history-dialog').close());
  $('cal-prev').addEventListener('click',()=>{calMonthOffset--; renderCalendarMonth();});
  $('cal-next').addEventListener('click',()=>{calMonthOffset++; renderCalendarMonth();});
  $('calendar-grid').addEventListener('click',(event)=>{
    const cell = event.target.closest('[data-date]'); if (!cell) return;
    const iso = cell.dataset.date;
    if (draftDates.has(iso)) draftDates.delete(iso); else draftDates.add(iso);
    renderStories(); renderPlan(); renderCalendarMonth();
  });
  $('manual-upload-input').addEventListener('change',(event)=>{
    const file = event.target.files[0], iso = pendingUploadDate, hora = pendingUploadHora;
    pendingUploadDate = null; event.target.value = '';
    if (file && iso) uploadManualImage(iso, hora, file);
  });
  $('edit-ritmo').addEventListener('click',()=>$('ritmo-dialog').showModal());
  $('close-ritmo').addEventListener('click',()=>$('ritmo-dialog').close());
  $('close-ritmo-2').addEventListener('click',()=>$('ritmo-dialog').close());
  $('ritmo-chips').addEventListener('click',(event)=>{
    const chip = event.target.closest('[data-day]'); if (!chip) return;
    toggleRitmoDay(Number(chip.dataset.day));
  });
  $('qa-focus').addEventListener('click',()=>{$('content-panel').classList.remove('collapsed'); setFieldMode('description',true); $('business-description').scrollIntoView({behavior:'smooth',block:'center'}); $('business-description').focus();});
  $('stories').addEventListener('click',(event)=>{
    const addCard=event.target.closest('[data-add-date]');
    if (addCard) {
      pendingUploadDate=addCard.dataset.addDate;
      const timeInput=document.querySelector(`.day-time[data-time-for="${CSS.escape(pendingUploadDate)}"]`);
      pendingUploadHora=timeInput ? timeInput.value : '09:00';
      $('manual-upload-input').click();
      return;
    }
    const action=event.target.closest('[data-action]'),card=event.target.closest('[data-story-id]');
    if (!card) return;
    const found=findStory(card.dataset.storyId); if(!found) return;
    if (action) {
      if(action.dataset.action==='edit')openStory(found.story);
      if(action.dataset.action==='delete')deleteStory(found.group,found.story);
      if(action.dataset.action==='move-left')moveStory(found.group,found.story,-1);
      if(action.dataset.action==='move-right')moveStory(found.group,found.story,1);
      return;
    }
    toggleApproval(found.story);
  });
  $('stories').addEventListener('change',(event)=>{
    const timeInput=event.target.closest('[data-time-for]'); if (!timeInput) return;
    updateDayTime(timeInput.dataset.timeFor, timeInput.value);
  });
  $('plan-days').addEventListener('click',(event)=>{const action=event.target.closest('[data-action]'),card=event.target.closest('[data-story-id]');if(!action||!card)return;const found=findStory(card.dataset.storyId);if(!found)return;if(action.dataset.action==='edit')openStory(found.story);if(action.dataset.action==='delete')deleteStory(found.group,found.story);});
  $('save-story').addEventListener('click',saveStory); $('close-story').addEventListener('click',()=>$('story-dialog').close()); $('cancel-story-edit').addEventListener('click',()=>$('story-dialog').close());
  loadMeAndTeams().finally(loadClients);
})();
