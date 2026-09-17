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
  function clearSelection() {
    state.selectionVersion += 1; state.selectedClientId = null; state.client = null; state.groups = []; state.editingStory = null;
    $('client-view').classList.add('hidden'); $('empty').classList.remove('hidden'); $('empty').textContent = 'Seleccioná un cliente para gestionar su contenido.';
  }

  async function loadMeAndTeams() {
    try {
      const [me, teams] = await Promise.all([api('/portal/me'), api('/portal/equipos')]);
      state.me = me; state.teams = teams;
      $('client-team').innerHTML = '<option value="">Sin equipo</option>' + teams.map((team) => `<option value="${escapeHtml(team.id)}">${escapeHtml(team.name)}</option>`).join('');
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
      const cards = byTeam.get(key).map((client) => `<button class="client-item${state.client?.id === client.id ? ' active' : ''}" data-client-id="${escapeHtml(client.id)}"><span class="avatar">${escapeHtml(initials(client.name))}</span><span>${escapeHtml(client.name)}</span></button>`).join('');
      return `<div class="team-group"><h4 class="team-label">${escapeHtml(key ? teamName(key) : 'Sin equipo')}</h4>${cards}</div>`;
    }).join('');
  }
  async function selectClient(clientId) {
    const selectionVersion = ++state.selectionVersion;
    state.selectedClientId = clientId; state.client = null; state.groups = []; state.editingStory = null; setControlsDisabled(true);
    if ($('story-dialog').open) $('story-dialog').close();
    clearMessage(); $('empty').classList.add('hidden'); $('client-view').classList.remove('hidden'); $('client-name').textContent = 'Cargando...'; $('stories').textContent = 'Cargando...'; $('calendar').textContent = 'Cargando...';
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
    $('client-team').value = state.client.team_id || '';
    $('prompt-preview').classList.add('hidden'); renderStories(); renderCalendar();
  }
  function groupDate(group) {
    const raw = group.scheduled_date || group.generation_week;
    return raw ? new Intl.DateTimeFormat('es-AR', {dateStyle:'long', timeZone:'UTC'}).format(new Date(`${raw}T00:00:00Z`)) : 'Sin fecha';
  }
  function renderStories() {
    if (!state.groups.length) { $('stories').innerHTML = '<div class="empty">No hay historias próximas para este cliente.</div>'; return; }
    $('stories').innerHTML = state.groups.map((group) => {
      const stories = [...(group.stories || [])].sort((a,b) => a.order - b.order);
      return `<section class="group" data-group-id="${escapeHtml(group.id)}"><div class="group-head"><h3>${escapeHtml(groupDate(group))}</h3><span class="badge">${escapeHtml(group.status || 'pending')}</span></div><div class="stories">${stories.map((story,index) => storyCard(story,index,stories.length)).join('')}</div></section>`;
    }).join('');
  }
  function renderCalendar() {
    const scheduled = state.groups.filter((group) => group.scheduled_date || group.generation_week);
    $('calendar').innerHTML = scheduled.length ? scheduled.map((group) => `<div class="calendar-item"><div class="calendar-date">${escapeHtml(groupDate(group))}</div><div class="calendar-count">${(group.stories || []).length} historias</div></div>`).join('') : '<div class="hint">Sin fechas programadas.</div>';
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
    if (!clientId) return; select.disabled=true;
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
    try { await api('/portal/historias/reordenar',{method:'PATCH',body:JSON.stringify({historias})}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; stories.forEach((item,position)=>{item.order=position+1;}); group.stories=stories; renderStories(); renderCalendar(); showMessage('Orden actualizado.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  async function deleteStory(group, story) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion; if(!clientId||!window.confirm('¿Cancelar esta historia?'))return;
    try { await api(`/portal/historias/${encodeURIComponent(story.id)}`,{method:'DELETE'}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; group.stories=group.stories.filter((item)=>item.id!==story.id); renderStories(); renderCalendar(); showMessage('Historia cancelada.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  $('client-list').addEventListener('click',(event)=>{const item=event.target.closest('[data-client-id]');if(item)selectClient(item.dataset.clientId);});
  $('only-mine').addEventListener('change',loadClients); $('save-description').addEventListener('click',()=>saveClientField('business_description','save-description')); $('save-focus').addEventListener('click',()=>saveClientField('weekly_focus','save-focus')); $('try-prompt').addEventListener('click',tryPrompt); $('client-team').addEventListener('change',saveClientTeam); $('add-team').addEventListener('click',createTeam);
  $('stories').addEventListener('click',(event)=>{const action=event.target.closest('[data-action]'),card=event.target.closest('[data-story-id]');if(!action||!card)return;const found=findStory(card.dataset.storyId);if(!found)return;if(action.dataset.action==='edit')openStory(found.story);if(action.dataset.action==='delete')deleteStory(found.group,found.story);if(action.dataset.action==='move-left')moveStory(found.group,found.story,-1);if(action.dataset.action==='move-right')moveStory(found.group,found.story,1);});
  $('save-story').addEventListener('click',saveStory); $('close-story').addEventListener('click',()=>$('story-dialog').close()); $('cancel-story-edit').addEventListener('click',()=>$('story-dialog').close()); loadMeAndTeams().finally(loadClients);
})();
