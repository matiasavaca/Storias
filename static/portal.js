(() => {
  'use strict';
  const state = { clients: [], client: null, groups: [], editingStory: null, selectedClientId: null, selectionVersion: 0, clientListVersion: 0, teams: [], me: null };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'})[char]);

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
      const cards = byTeam.get(key).map((client) => `<button class="client-item${state.client?.id === client.id ? ' active' : ''}" data-client-id="${escapeHtml(client.id)}"><span class="avatar">${escapeHtml(initials(client.name))}</span><span class="meta"><span class="name">${escapeHtml(client.name)}</span></span></button>`).join('');
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
    try {
      const [client, groups] = await Promise.all([api(`/portal/clientes/${encodeURIComponent(clientId)}`), api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`)]);
      if (selectionVersion !== state.selectionVersion || clientId !== state.selectedClientId) return;
      state.client = client; state.groups = groups;
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
  function renderClient() {
    $('client-name').textContent = state.client.name; $('client-avatar').textContent = initials(state.client.name);
    $('business-description').value = state.client.business_description || ''; $('weekly-focus').value = state.client.weekly_focus || '';
    $('desc-count').textContent = String($('business-description').value.length); $('focus-count').textContent = String($('weekly-focus').value.length);
    $('client-team').value = state.client.team_id || '';
    $('gen-dot').className = `gen-dot${state.client.generation_error ? ' warn' : ''}`;
    $('header-tags').innerHTML = (state.client.topics || []).slice(0, 4).map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join('');
    const url = driveUrl(state.client.drive_folder_id);
    if (url) { $('drive-link').href = url; $('drive-link').classList.remove('hidden'); $('qa-drive').href = url; $('qa-drive').classList.remove('hidden'); }
    else { $('drive-link').classList.add('hidden'); $('qa-drive').classList.add('hidden'); }
    $('prompt-preview').classList.add('hidden'); renderStories(); renderActivity();
  }
  function groupDate(group) {
    const raw = group.scheduled_date || group.generation_week;
    return raw ? new Intl.DateTimeFormat('es-AR', {dateStyle:'long', timeZone:'UTC'}).format(new Date(`${raw}T00:00:00Z`)) : 'Sin fecha';
  }
  function renderStories() {
    if (!state.groups.length) { $('stories').innerHTML = '<div class="empty">No hay historias próximas para este cliente.</div>'; $('week-badge').classList.add('hidden'); return; }
    const next = state.groups[0];
    if (next.scheduled_date) { $('week-badge').textContent = `${groupDate(next)}${next.scheduled_time ? ' · ' + next.scheduled_time.slice(0,5) + 'hs' : ''}`; $('week-badge').classList.remove('hidden'); }
    else $('week-badge').classList.add('hidden');
    $('stories').innerHTML = state.groups.map((group) => {
      const stories = [...(group.stories || [])].sort((a,b) => a.order - b.order);
      return `<section class="group" data-group-id="${escapeHtml(group.id)}"><div class="group-head"><h3>${escapeHtml(groupDate(group))}</h3><span class="badge">${escapeHtml(group.status || 'pending')}</span></div><div class="stories">${stories.map((story,index) => storyCard(story,index,stories.length)).join('')}</div></section>`;
    }).join('');
  }
  function renderActivity() {
    const next = state.groups[0];
    const activeCount = next ? (next.stories || []).length : 0;
    const rows = [];
    if (next) {
      rows.push(`<div class="activity-item"><span class="dot">✓</span><div><div>${activeCount} historia${activeCount===1?'':'s'} lista${activeCount===1?'':'s'}</div><div class="sub">Generadas con la dirección actual</div></div></div>`);
      rows.push(`<div class="activity-item"><span class="dot">📅</span><div><div>Próxima publicación: ${escapeHtml(groupDate(next))}${next.scheduled_time ? ' · ' + next.scheduled_time.slice(0,5) + 'hs' : ''}</div><div class="sub">Según el plan generado</div></div></div>`);
    } else {
      rows.push(`<div class="activity-item"><span class="dot">–</span><div><div>Sin historias programadas</div><div class="sub">Todavía no se generó contenido para este cliente</div></div></div>`);
    }
    $('activity-list').innerHTML = rows.join('');
    $('activity-summary').innerHTML = state.client.generation_error
      ? `<div class="status-card warn"><span>⚠️</span><div><strong>Necesita atención</strong><p>${escapeHtml(state.client.generation_error)}</p></div></div>`
      : `<div class="status-card ok"><span>✓</span><div><strong>Todo en orden</strong><p>No hay errores de generación pendientes.</p></div></div>`;
  }
  function storyCard(story, index, total) {
    return `<article class="story" data-story-id="${escapeHtml(story.id)}">${story.image_url ? `<img src="${escapeHtml(story.image_url)}" alt="Historia ${index+1}">` : ''}<span class="story-num">${index+1}</span><div class="story-actions"><button class="icon-btn" data-action="move-left" ${index===0?'disabled':''} aria-label="Mover a la izquierda">←</button><button class="icon-btn" data-action="move-right" ${index===total-1?'disabled':''} aria-label="Mover a la derecha">→</button><button class="icon-btn" data-action="edit" aria-label="Editar">✎</button><button class="icon-btn" data-action="delete" aria-label="Eliminar">×</button></div><div class="story-overlay"><p class="story-text">${escapeHtml(story.text)}</p></div></article>`;
  }
  async function saveClientField(field, buttonId) {
    const button=$(buttonId), input=$(field==='business_description'?'business-description':'weekly-focus'), value=input.value.trim(), clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!clientId) return; button.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}`, {method:'PATCH', body:JSON.stringify({[field]:value || null})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client = updated; showMessage(field==='weekly_focus'?'Enfoque semanal guardado.':'Descripción guardada.');
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
      Object.assign(story,updated); $('story-dialog').close(); renderStories(); showMessage('Historia actualizada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
    finally { if (selectionVersion === state.selectionVersion) button.disabled=false; }
  }
  async function moveStory(group, story, direction) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion, stories=[...group.stories].sort((a,b)=>a.order-b.order), index=stories.findIndex((item)=>item.id===story.id), target=index+direction; if(!clientId||target<0||target>=stories.length)return;
    [stories[index],stories[target]]=[stories[target],stories[index]];
    const historias=stories.map((item,position)=>({story_id:item.id,nuevo_order:position+1}));
    try { await api('/portal/historias/reordenar',{method:'PATCH',body:JSON.stringify({historias})}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; stories.forEach((item,position)=>{item.order=position+1;}); group.stories=stories; renderStories(); showMessage('Orden actualizado.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  async function deleteStory(group, story) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion; if(!clientId||!window.confirm('¿Cancelar esta historia?'))return;
    try { await api(`/portal/historias/${encodeURIComponent(story.id)}`,{method:'DELETE'}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; group.stories=group.stories.filter((item)=>item.id!==story.id); renderStories(); renderActivity(); showMessage('Historia cancelada.'); }
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
  $('content-panel-toggle').addEventListener('click',()=>$('content-panel').classList.toggle('collapsed'));
  $('qa-history').addEventListener('click',openHistory);
  $('close-history').addEventListener('click',()=>$('history-dialog').close());
  $('close-history-2').addEventListener('click',()=>$('history-dialog').close());
  $('qa-focus').addEventListener('click',()=>{$('content-panel').classList.remove('collapsed'); $('business-description').scrollIntoView({behavior:'smooth',block:'center'}); $('business-description').focus();});
  $('stories').addEventListener('click',(event)=>{const action=event.target.closest('[data-action]'),card=event.target.closest('[data-story-id]');if(!action||!card)return;const found=findStory(card.dataset.storyId);if(!found)return;if(action.dataset.action==='edit')openStory(found.story);if(action.dataset.action==='delete')deleteStory(found.group,found.story);if(action.dataset.action==='move-left')moveStory(found.group,found.story,-1);if(action.dataset.action==='move-right')moveStory(found.group,found.story,1);});
  $('save-story').addEventListener('click',saveStory); $('close-story').addEventListener('click',()=>$('story-dialog').close()); $('cancel-story-edit').addEventListener('click',()=>$('story-dialog').close());
  loadMeAndTeams().finally(loadClients);
})();
