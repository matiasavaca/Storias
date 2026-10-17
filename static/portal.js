(() => {
  'use strict';
  const state = { clients: [], client: null, groups: [], driveCount: undefined, editingStory: null, selectedClientId: null, selectionVersion: 0, clientListVersion: 0, homeSummaryVersion: 0, me: null, employees: [], clientSearch: '' };
  const LOCKED_STORY_STATES = new Set(['publicando', 'publicado', 'cancelada']);
  const storyIsLocked = (story) => LOCKED_STORY_STATES.has(story?.estado);
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'})[char]);
  const ICONS = {
    house: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/> <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/> <path d="M16 3.128a4 4 0 0 1 0 7.744"/> <path d="M22 21v-2a4 4 0 0 0-3-3.87"/> <circle cx="9" cy="7" r="4"/>',
    settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/> <circle cx="12" cy="12" r="3"/>',
    bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/> <path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'chevron-right': '<path d="m9 18 6-6-6-6"/>',
    calendar: '<path d="M8 2v3"/> <path d="M16 2v3"/> <rect x="3" y="3" width="18" height="18" rx="2"/> <path d="M3 9h18"/>',
    clock: '<circle cx="12" cy="12" r="10"/> <path d="M12 6v6l4 2"/>',
    pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/> <path d="m15 5 4 4"/>',
    mail: '<path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/> <rect x="2" y="4" width="20" height="16" rx="2"/>',
    trash: '<path d="M10 11v6"/> <path d="M14 11v6"/> <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/> <path d="M3 6h18"/> <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    'rotate-cw': '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/> <path d="M21 3v5h-5"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/> <circle cx="9" cy="9" r="2"/> <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/> <path d="M12 9v4"/> <path d="M12 17h.01"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/> <circle cx="12" cy="12" r="3"/>',
    'calendar-check': '<path d="M8 2v3"/> <path d="M16 2v3"/> <rect x="3" y="3" width="18" height="18" rx="2"/> <path d="M3 9h18"/> <path d="m9 15 2 2 4-4"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/> <path d="m21.854 2.147-10.94 10.939"/>',
    'check-check': '<path d="M18 6 7 17l-5-5"/> <path d="m22 10-7.5 7.5L13 16"/>',
    sparkles: '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/> <path d="M20 2v4"/> <path d="M22 4h-4"/> <circle cx="4" cy="20" r="2"/>',
    'grip-vertical': '<circle cx="9" cy="12" r="1"/> <circle cx="9" cy="5" r="1"/> <circle cx="9" cy="19" r="1"/> <circle cx="15" cy="12" r="1"/> <circle cx="15" cy="5" r="1"/> <circle cx="15" cy="19" r="1"/>',
  };
  function icon(name, size = 16) {
    return `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  }
  function hydrateIcons() {
    document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon, Number(el.dataset.size) || 16); });
  }
  function avatarColor(id) { let hash = 0; for (const ch of String(id)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0; return hash % 12; }
  let fontFacesInjected = false;
  function injectFontFaces(fonts) {
    // Lets the <option> list below render each font's name IN that font,
    // so an employee can eyeball how it looks before picking it.
    if (fontFacesInjected) return; fontFacesInjected = true;
    const style = document.createElement('style');
    style.textContent = fonts.map((font) =>
      `@font-face{font-family:'sf-${font.key}';src:url('/fonts/${encodeURIComponent(font.file)}');font-display:swap;}`
    ).join('');
    document.head.appendChild(style);
  }

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
  let toastTimer = null;
  function showMessage(text, error = false) {
    const toast = $('toast');
    const duration = error ? 7000 : 4000;
    $('toast-text').textContent = text;
    $('toast-icon').innerHTML = icon(error ? 'triangle-alert' : 'check', 18);
    toast.className = 'toast hidden';
    void toast.offsetWidth; // reinicia la animación si ya había un aviso en pantalla
    toast.style.setProperty('--toast-ms', `${duration}ms`);
    toast.setAttribute('role', error ? 'alert' : 'status');
    toast.className = `toast${error ? ' error' : ''}`;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(clearMessage, duration);
  }
  function clearMessage() {
    $('toast').className = 'toast hidden';
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
  }
  function confirmDialog(text, {okLabel = 'Confirmar', danger = false} = {}) {
    return new Promise((resolve) => {
      const dialog = $('confirm-dialog');
      $('confirm-text').textContent = text;
      $('confirm-ok').textContent = okLabel;
      $('confirm-ok').className = `btn primary${danger ? ' danger' : ''}`;
      const settle = (value) => { dialog.close(); resolve(value); };
      const onOk = () => { cleanup(); settle(true); };
      const onCancel = () => { cleanup(); settle(false); };
      function cleanup() {
        $('confirm-ok').removeEventListener('click', onOk);
        $('confirm-cancel').removeEventListener('click', onCancel);
        $('confirm-close').removeEventListener('click', onCancel);
        dialog.removeEventListener('cancel', onCancel);
      }
      $('confirm-ok').addEventListener('click', onOk);
      $('confirm-cancel').addEventListener('click', onCancel);
      $('confirm-close').addEventListener('click', onCancel);
      dialog.addEventListener('cancel', onCancel); // Esc key
      dialog.showModal();
    });
  }
  function initials(name) { return String(name || '?').split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase(); }
  function avatarContent(client) {
    return client.avatar_url ? `<img src="${escapeHtml(client.avatar_url)}" alt="">` : escapeHtml(initials(client.name));
  }
  function setControlsDisabled(disabled) {
    ['save-description','save-focus','save-topics','try-prompt','save-story','generate-weekly','client-pm','client-font','client-instagram','client-whatsapp','client-email','client-avatar-upload'].forEach((id) => { $(id).disabled = disabled; });
    $('generate-weekly').disabled = disabled || ritmoSaving || weeklyGenerating;
  }
  function driveUrl(folderId) { return folderId ? `https://drive.google.com/drive/folders/${encodeURIComponent(folderId)}` : null; }
  function clearSelection() {
    state.selectionVersion += 1; state.selectedClientId = null; state.client = null; state.groups = []; state.editingStory = null;
    $('client-view').classList.add('hidden'); $('empty').classList.remove('hidden'); $('empty').textContent = 'Seleccioná un cliente para gestionar su contenido.';
    $('header-client').classList.add('hidden'); $('header-default').classList.remove('hidden'); $('drive-link').classList.add('hidden');
    $('home-view').classList.add('hidden'); $('nav-home').classList.remove('active'); $('nav-clients').classList.add('active');
  }
  function homeAvatar(clientId, name) {
    const client = state.clients.find((item) => item.id === clientId) || {id: clientId, name};
    return `<span class="avatar avatar-sm${client.avatar_url ? ' has-avatar' : ' avatar-' + avatarColor(client.id)}">${avatarContent(client)}</span>`;
  }
  function homeRow({id, name, sub, tone, action}) {
    return `<div class="home-row${tone ? ' is-' + tone : ''}" data-client-id="${escapeHtml(id)}" role="button" tabindex="0"><span>${homeAvatar(id, name)}</span><div class="home-row-text"><strong>${escapeHtml(name)}</strong><span title="${escapeHtml(sub)}">${escapeHtml(sub)}</span></div>${action || ''}<span class="home-row-go">${icon('chevron-right', 16)}</span></div>`;
  }
  function renderHomeHero(info) {
    const first = String(state.me?.name || '').trim().split(/\s+/)[0];
    $('home-greeting').textContent = first ? `Hola, ${first}` : 'Hola';
    $('home-date').textContent = new Intl.DateTimeFormat('es-AR', {weekday: 'long', day: 'numeric', month: 'long'}).format(new Date());
    if (!info) { $('home-subtitle').textContent = 'Resumen de tus clientes.'; return; }
    const {summary, problems, healthKnown} = info;
    if (problems > 0) {
      $('home-subtitle').textContent = `${problems} cliente${problems === 1 ? ' necesita' : 's necesitan'} tu atención.`;
    } else if (healthKnown && summary) {
      const n = summary.historias_agendadas;
      $('home-subtitle').textContent = `Todo en orden. Hay ${n} historia${n === 1 ? '' : 's'} agendada${n === 1 ? '' : 's'} para subir.`;
    } else {
      $('home-subtitle').textContent = 'Resumen de tus clientes.';
    }
  }
  function renderHomeHealth(health) {
    const checks = [
      {
        title: 'Error de generación', okText: 'Sin errores de generación', items: health.clientes_con_error_generacion || [],
        row: (c) => homeRow({id: c.id, name: c.name, tone: 'danger', sub: `${safeHealthDayLabel(c.generation_error_at, 'Reciente')} · ${c.generation_error || 'Falló la generación'}`}),
      },
      {
        title: 'Pool de imágenes bajo', okText: 'Pool de imágenes al día', items: health.clientes_con_pool_bajo || [],
        row: (c) => homeRow({id: c.id, name: c.name, tone: 'warn', sub: `Quedan pocas imágenes en Drive · ${safeHealthDayLabel(c.pool_bajo_at, 'reciente')}`}),
      },
      {
        title: 'Historias sin publicar por error', okText: 'Sin historias para reintentar', items: health.clientes_con_historias_en_error || [],
        row: (c) => homeRow({id: c.id, name: c.name, tone: 'danger', sub: `${c.historias_en_error} historia${c.historias_en_error === 1 ? '' : 's'} sin publicar${c.fecha_mas_antigua ? ' · desde ' + dayLabel(c.fecha_mas_antigua) : ''}`}),
      },
    ];
    const problemIds = new Set();
    checks.forEach((check) => check.items.forEach((item) => problemIds.add(item.id)));
    const sections = checks.filter((check) => check.items.length).map((check) =>
      `<div class="home-section"><div class="home-section-head"><span>${escapeHtml(check.title)}</span><span class="home-count">${check.items.length}</span></div>${check.items.map(check.row).join('')}</div>`);
    const okChecks = checks.filter((check) => !check.items.length);
    const okList = okChecks.length
      ? `<div class="home-ok-list">${okChecks.map((check) => `<span class="home-ok">${icon('check', 14)}${escapeHtml(check.okText)}</span>`).join('')}</div>`
      : '';
    $('home-health').innerHTML = sections.join('') + okList;
    const pill = $('home-health-pill');
    pill.className = 'home-pill ' + (problemIds.size ? 'danger' : 'success');
    pill.textContent = problemIds.size ? `${problemIds.size} cliente${problemIds.size === 1 ? '' : 's'} con problemas` : 'Todo en orden';
    return problemIds;
  }
  function renderHealthUnavailable() {
    $('home-health').innerHTML = '<div class="home-note">El estado de salud no está disponible en este momento.</div>';
    $('home-health-pill').classList.add('hidden');
  }
  function isoDateInTimeZone(value, timeZone = 'America/Argentina/Buenos_Aires') {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(value);
    const datePart = (type) => parts.find((part) => part.type === type)?.value;
    return [datePart('year'), datePart('month'), datePart('day')].join('-');
  }
  function nextCalendarIso(isoDate) {
    const [year, month, day] = isoDate.split('-').map(Number);
    return new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10);
  }
  function renderHomeUpcoming(items) {
    const panel = $('home-upcoming-panel');
    // Older backend without the field: keep the panel hidden instead of showing a false "nothing scheduled".
    if (!Array.isArray(items)) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    $('home-upcoming-count').textContent = `${items.length} ${items.length === 1 ? 'publicación' : 'publicaciones'}`;
    if (!items.length) { $('home-upcoming').innerHTML = '<div class="home-note">No hay publicaciones programadas para los próximos 7 días.</div>'; return; }
    const todayIso = isoDateInTimeZone(new Date());
    const tomorrowIso = nextCalendarIso(todayIso);
    $('home-upcoming').innerHTML = items.map((item) => {
      const dayText = item.fecha === todayIso ? 'Hoy' : item.fecha === tomorrowIso ? 'Mañana' : dayLabel(item.fecha);
      const pending = item.total - item.aprobadas;
      const detail = `${item.hora ? item.hora + ' hs · ' : ''}${item.total} historia${item.total === 1 ? '' : 's'}`;
      const badge = pending === 0
        ? '<span class="home-state is-ready">Lista</span>'
        : `<span class="home-state is-pending">${pending} sin aprobar</span>`;
      return `<div class="home-row" data-client-id="${escapeHtml(item.client_id)}" role="button" tabindex="0"><span class="home-day${item.fecha === todayIso ? ' is-today' : ''}">${escapeHtml(dayText)}</span><span>${homeAvatar(item.client_id, item.client_name)}</span><div class="home-row-text"><strong>${escapeHtml(item.client_name)}</strong><span>${escapeHtml(detail)}</span></div>${badge}<span class="home-row-go">${icon('chevron-right', 16)}</span></div>`;
    }).join('');
  }
  function renderHomeIdle(summary, problemIds) {
    // A client that already shows up in "Salud" is not repeated here.
    const idle = (summary?.clientes_sin_actividad || []).filter((client) => !problemIds.has(client.id));
    $('home-idle-panel').classList.toggle('hidden', !idle.length);
    $('home-idle-count').textContent = String(idle.length);
    $('home-idle').innerHTML = idle.map((client) => homeRow({
      id: client.id, name: client.name, sub: 'Sin historias próximas',
      action: `<button type="button" class="btn home-row-btn" data-home-generate="${escapeHtml(client.id)}">${icon('sparkles', 13)}Generar semana</button>`,
    })).join('');
  }
  async function loadHomeSummary() {
    const summaryVersion = ++state.homeSummaryVersion;
    renderHomeHero(null);
    ['stat-edicion','stat-agendadas','stat-publicadas','stat-promedio','stat-aprobacion'].forEach((id) => { $(id).textContent = '–'; $(id).closest('.stat-card').classList.remove('is-zero'); });
    $('home-health').innerHTML = loadingMarkup('', {compact: true});
    $('home-health-pill').classList.add('hidden');
    $('home-idle-panel').classList.add('hidden');
    $('home-upcoming-panel').classList.add('hidden');
    const [summaryResult, healthResult] = await Promise.allSettled([api('/portal/resumen'), api('/portal/salud')]);
    // Inicio can be opened twice before its first request returns, or closed
    // while it is in flight. Only the latest visible request may update it.
    if (summaryVersion !== state.homeSummaryVersion || $('home-view').classList.contains('hidden')) return;
    const summary = summaryResult.status === 'fulfilled' ? summaryResult.value : null;
    const health = healthResult.status === 'fulfilled' ? healthResult.value : null;
    if (summary) {
      const setStat = (id, value, isZero) => { $(id).textContent = value; $(id).closest('.stat-card').classList.toggle('is-zero', !!isZero); };
      setStat('stat-edicion', summary.historias_en_edicion, summary.historias_en_edicion === 0);
      setStat('stat-agendadas', summary.historias_agendadas, summary.historias_agendadas === 0);
      setStat('stat-publicadas', summary.historias_publicadas, summary.historias_publicadas === 0);
      setStat('stat-promedio', summary.promedio_por_cliente, summary.promedio_por_cliente === 0);
      setStat('stat-aprobacion', summary.aprobacion_pct === null ? '—' : `${summary.aprobacion_pct}%`, summary.aprobacion_pct === null);
      renderHomeUpcoming(summary.proximas_publicaciones);
    } else {
      const error = summaryResult.reason;
      if (!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
    }
    let problemIds = new Set();
    if (health) problemIds = renderHomeHealth(health); else renderHealthUnavailable();
    renderHomeIdle(summary, problemIds);
    renderHomeHero({summary, problems: problemIds.size, healthKnown: !!health});
  }
  function showHome() {
    $('nav-home').classList.add('active'); $('nav-clients').classList.remove('active');
    $('home-view').classList.remove('hidden'); $('empty').classList.add('hidden'); $('client-view').classList.add('hidden');
    $('header-client').classList.add('hidden'); $('header-default').classList.remove('hidden'); $('drive-link').classList.add('hidden');
    renderClients();
    loadHomeSummary();
  }
  function showClients() {
    $('nav-clients').classList.add('active'); $('nav-home').classList.remove('active');
    $('home-view').classList.add('hidden');
    renderClients();
    if (state.client) {
      $('client-view').classList.remove('hidden'); $('header-default').classList.add('hidden'); $('header-client').classList.remove('hidden');
      if (driveUrl(state.client.drive_folder_id)) $('drive-link').classList.remove('hidden');
    } else {
      $('empty').classList.remove('hidden');
    }
  }

  async function loadMeAndOptions() {
    try {
      const [me, fonts, employees] = await Promise.all([api('/portal/me'), api('/portal/tipografias'), api('/portal/empleados')]);
      state.me = me; state.fontChoices = fonts; state.employees = employees;
      injectFontFaces(fonts);
      const fontOptions = fonts.map((font) => `<option value="${escapeHtml(font.key)}" style="font-family:'sf-${escapeHtml(font.key)}',sans-serif">${escapeHtml(font.label)}</option>`).join('');
      $('client-pm').innerHTML = '<option value="">Sin asignar</option>' + employees.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name || person.email)}</option>`).join('');
      $('client-font').innerHTML = '<option value="">Default</option>' + fontOptions;
      $('story-font').innerHTML = '<option value="">Default del cliente</option>' + fontOptions;
      $('me-avatar').textContent = initials(me.name || me.email); $('me-name').textContent = me.name || me.email;
      $('me-role').textContent = me.role === 'admin' ? 'Administrador' : 'Empleado'; $('me-card').classList.remove('hidden');
      $('me-menu-name').textContent = me.name || me.email; $('me-menu-email').textContent = me.name ? (me.email || '') : '';
      $('add-clients-bulk').classList.toggle('hidden', me.role !== 'admin');
    } catch (error) { /* non-fatal: client loading remains available */ }
  }

  function parseBulkClientsInput(text) {
    return text.split('\n').map((line) => line.trim()).filter(Boolean).map((line, idx) => {
      const [name, drive, businessDescription] = line.split(',').map((part) => (part || '').trim());
      return {fila: idx + 1, name: name || '', drive: drive || '', businessDescription: businessDescription || ''};
    });
  }
  function renderBulkClientsResults(rows) {
    if (!rows.length) { $('bulk-clients-results').innerHTML = ''; return; }
    $('bulk-clients-results').innerHTML = `<div class="idle-list">${rows.map((row) =>
      `<span class="idle-chip${row.status === 'creado' ? ' success' : ''}">Fila ${row.fila} — ${escapeHtml(row.name || '(sin nombre)')}: ${row.status === 'creado' ? 'creado' : escapeHtml(row.motivo)}</span>`
    ).join('')}</div>`;
  }
  async function submitBulkClients() {
    const rows = parseBulkClientsInput($('bulk-clients-input').value);
    if (!rows.length) {
      $('bulk-clients-feedback').textContent = 'Pegá al menos un cliente.';
      $('bulk-clients-feedback').classList.remove('hidden');
      return;
    }
    $('bulk-clients-feedback').classList.add('hidden');
    const localErrors = [];
    const payload = [];
    const payloadRowNumbers = [];
    for (const row of rows) {
      if (!row.name || !row.drive) {
        localErrors.push({fila: row.fila, name: row.name, status: 'error', motivo: 'Faltan columnas obligatorias (nombre y carpeta de Drive).'});
        continue;
      }
      payload.push({name: row.name, drive_folder_id: row.drive, business_description: row.businessDescription || null});
      payloadRowNumbers.push(row.fila);
    }
    $('submit-bulk-clients').disabled = true;
    try {
      let serverResults = [];
      if (payload.length) {
        const response = await api('/portal/clientes/alta-masiva', {method: 'POST', body: JSON.stringify({clientes: payload})});
        serverResults = response.resultados.map((result, i) => ({...result, fila: payloadRowNumbers[i]}));
      }
      const allResults = [...localErrors, ...serverResults].sort((a, b) => a.fila - b.fila);
      renderBulkClientsResults(allResults);
      const createdCount = serverResults.filter((row) => row.status === 'creado').length;
      if (createdCount) {
        showMessage(`${createdCount} cliente${createdCount === 1 ? '' : 's'} creado${createdCount === 1 ? '' : 's'}.`);
        loadClients();
      }
    } catch (error) {
      $('bulk-clients-feedback').textContent = error.message;
      $('bulk-clients-feedback').classList.remove('hidden');
    } finally {
      $('submit-bulk-clients').disabled = false;
    }
  }

  function loadingMarkup(label, options = {}) {
    const text = label ? `<p>${escapeHtml(label)}</p>` : '';
    return `<div class="loading-state${options.compact ? ' compact' : ''}" role="status" aria-label="${escapeHtml(options.aria || label || 'Cargando')}"><span class="spinner"></span>${text}</div>`;
  }
  function listEmptyMarkup(title, hint, withRetry) {
    return `<div class="list-empty"><span class="list-empty-icon">${icon('users', 18)}</span><p class="list-empty-title">${escapeHtml(title)}</p>${hint ? `<p class="list-empty-hint">${escapeHtml(hint)}</p>` : ''}${withRetry ? '<button type="button" class="btn list-empty-retry" data-client-retry>Reintentar</button>' : ''}</div>`;
  }
  async function loadClients() {
    clearMessage(); $('client-list').innerHTML = loadingMarkup('', {compact: true, aria: 'Cargando clientes'});
    const listVersion = ++state.clientListVersion;
    const suffix = $('client-filter').dataset.value === 'mine' ? '?solo_mios=true' : '';
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
      $('client-list').innerHTML = listEmptyMarkup('No se pudieron cargar', 'Revisá tu conexión e intentá de nuevo.', true);
      const retryButton = $('client-list').querySelector('[data-client-retry]');
      if (retryButton) retryButton.addEventListener('click', (event) => { event.stopPropagation(); loadClients(); });
      if (!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
    }
  }
  function clientStatus(client) {
    if (client.generation_error) return {key: 'error', label: 'Error de generación'};
    const count = client.stories_count ?? 0, pending = client.pending_count ?? 0;
    if (pending > 0) return {key: 'pending', label: `${pending} sin aprobar`};
    if (count > 0) return {key: 'ready', label: `${count} historia${count === 1 ? '' : 's'} lista${count === 1 ? '' : 's'}`};
    return {key: 'idle', label: 'Sin historias'};
  }
  const STATUS_ORDER = {error: 0, pending: 1, ready: 2, idle: 3};
  function renderClients() {
    $('client-count').textContent = 'Clientes';
    if (!state.clients.length) {
      $('client-list').innerHTML = $('client-filter').dataset.value === 'mine'
        ? listEmptyMarkup('Sin clientes asignados', 'Cuando te asignen uno, aparece acá.')
        : listEmptyMarkup('Todavía no hay clientes', 'Cuando se den de alta, aparecen acá.');
      return;
    }
    const query = (state.clientSearch || '').trim().toLocaleLowerCase('es');
    const visibleClients = query ? state.clients.filter((client) => client.name.toLocaleLowerCase('es').includes(query)) : state.clients;
    $('client-count').textContent = `${visibleClients.length} cliente${visibleClients.length === 1 ? '' : 's'}`;
    if (!visibleClients.length) { $('client-list').innerHTML = listEmptyMarkup('Sin resultados', 'Probá con otro nombre.'); return; }
    const sorted = visibleClients.map((client) => ({client, status: clientStatus(client)}))
      .sort((a, b) => STATUS_ORDER[a.status.key] - STATUS_ORDER[b.status.key] || a.client.name.localeCompare(b.client.name, 'es'));
    $('client-list').innerHTML = sorted.map(({client, status}) => {
      const active = $('home-view').classList.contains('hidden') && state.client?.id === client.id;
      return `<button class="client-item${active ? ' active' : ''}" data-client-id="${escapeHtml(client.id)}" title="${escapeHtml(client.name)}"><span class="avatar${client.avatar_url ? ' has-avatar' : ' avatar-' + avatarColor(client.id)}">${avatarContent(client)}</span><span class="meta"><span class="name">${escapeHtml(client.name)}</span><span class="count is-${status.key}">${escapeHtml(status.label)}</span></span><span class="status-dot is-${status.key}" aria-hidden="true"></span></button>`;
    }).join('');
  }
  async function selectClient(clientId) {
    const selectionVersion = ++state.selectionVersion;
    state.selectedClientId = clientId; state.client = null; state.groups = []; state.editingStory = null; draftDates = new Set(); setControlsDisabled(true);
    if ($('story-dialog').open) $('story-dialog').close();
    clearMessage(); $('empty').classList.add('hidden'); $('client-view').classList.remove('hidden');
    $('home-view').classList.add('hidden'); $('nav-home').classList.remove('active'); $('nav-clients').classList.add('active');
    $('header-default').classList.add('hidden'); $('header-client').classList.remove('hidden');
    $('client-name').textContent = 'Cargando...'; $('stories').innerHTML = loadingMarkup('Cargando historias...'); $('week-badge').classList.add('hidden');
    $('activity-list').innerHTML = ''; $('activity-summary').innerHTML = ''; updateContactLinks(); $('drive-link').classList.add('hidden');
    $('plan-panel').classList.add('hidden'); $('historico-panel').classList.add('hidden'); $('historico-list').innerHTML = ''; state.driveCount = undefined;
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
  function enterFieldEdit(name, inputId) {
    setFieldMode(name, true);
    $(inputId).focus();
  }
  function exitFieldEdit(name) {
    setFieldMode(name, false);
    $(`${name}-view`).focus();
  }
  function bindFieldViewEdit(viewId, name, inputId) {
    const view = $(viewId);
    const enterEdit = () => enterFieldEdit(name, inputId);
    view.addEventListener('click', enterEdit);
    view.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      enterEdit();
    });
  }
  function updateFieldView(name, value, emptyPlaceholder) {
    $(`${name}-text`).textContent = value || emptyPlaceholder;
    $(`${name}-view`).classList.toggle('empty', !value);
  }
  function renderTopicsView(topics) {
    const values = Array.isArray(topics) ? topics : [];
    $('topics-text').innerHTML = values.length
      ? values.map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join('')
      : '<p class="field-text">Todavía no hay temas. Hacé click acá para agregarlos.</p>';
    $('topics-view').classList.toggle('empty', !values.length);
  }
  function renderClient() {
    $('client-name').textContent = state.client.name;
    $('client-avatar').innerHTML = avatarContent(state.client);
    $('client-avatar').classList.toggle('has-avatar', !!state.client.avatar_url);
    $('client-avatar-preview').innerHTML = avatarContent(state.client);
    $('client-avatar-preview').classList.toggle('has-avatar', !!state.client.avatar_url);
    $('client-workspace-title').textContent = `${state.client.name} · contenido de la próxima semana`;
    $('client-workspace-subtitle').textContent = state.client.weekly_focus
      ? 'La dirección semanal está cargada. Revisá las historias y dejalas listas para publicar.'
      : 'Definí una dirección, revisá las historias y dejalas listas para publicar.';
    $('business-description').value = state.client.business_description || ''; $('weekly-focus').value = state.client.weekly_focus || ''; $('client-topics').value = (state.client.topics || []).join('\n');
    $('desc-count').textContent = String($('business-description').value.length); $('focus-count').textContent = String($('weekly-focus').value.length); $('topics-count').textContent = String((state.client.topics || []).length);
    updateFieldView('description', state.client.business_description, 'Todavía no hay descripción. Hacé click acá para agregarla.');
    updateFieldView('focus', state.client.weekly_focus, 'Sin enfoque puntual para esta semana.');
    renderTopicsView(state.client.topics);
    setFieldMode('description', false); setFieldMode('focus', false); setFieldMode('topics', false);
    $('client-pm').value = state.client.assigned_employee_id || '';
    $('client-font').value = state.client.font_choice || '';
    $('client-instagram').value = state.client.instagram_profile_url || '';
    $('client-whatsapp').value = state.client.whatsapp_contact || '';
    $('client-email').value = state.client.contact_email || '';
    updateContactLinks();
    $('gen-dot').className = `gen-dot${state.client.generation_error ? ' warn' : ''}`;
    const url = driveUrl(state.client.drive_folder_id);
    if (url) { $('drive-link').href = url; $('drive-link').classList.remove('hidden'); }
    else { $('drive-link').classList.add('hidden'); }
    $('prompt-preview').classList.add('hidden'); renderStories(); renderPlan(); renderActivity(); loadCalendar();
  }
  function instagramHref(value) {
    if (!value) return null;
    return /^https?:\/\//i.test(value) ? value : `https://instagram.com/${value.replace(/^@/, '')}`;
  }
  function whatsappHref(value) {
    if (!value) return null;
    const digits = value.replace(/\D/g, '');
    return digits ? `https://wa.me/${digits}` : null;
  }
  function updateContactLinks() {
    const ig = instagramHref(state.client?.instagram_profile_url);
    $('qa-instagram').href = ig || '#';
    $('qa-instagram').classList.toggle('hidden', !ig);
    const wa = whatsappHref(state.client?.whatsapp_contact);
    $('qa-whatsapp').href = wa || '#';
    $('qa-whatsapp').classList.toggle('hidden', !wa);
    const email = state.client?.contact_email;
    $('client-email-open').href = email ? `mailto:${encodeURIComponent(email)}` : '#';
    $('client-email-open').classList.toggle('hidden', !email);
  }
  function dayLabel(isoDate) {
    return isoDate ? new Intl.DateTimeFormat('es-AR', {weekday:'short', day:'numeric', timeZone:'UTC'}).format(new Date(`${isoDate}T00:00:00Z`)) : '';
  }
  function safeHealthDayLabel(value, fallback) {
    const isoDate = typeof value === 'string' ? value.slice(0, 10) : '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return fallback;
    const date = new Date(`${isoDate}T00:00:00Z`);
    if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== isoDate) return fallback;
    return dayLabel(isoDate) || fallback;
  }
  function activeGroup() {
    // Prefer the nearest group still awaiting confirmation; if everything is
    // already scheduled, keep showing the nearest confirmed publication.
    return state.groups.find((group) => (group.stories || []).some((story) => !storyIsScheduled(story, group))) || state.groups[0];
  }
  function storyIsScheduled(story, group) {
    // story.agendado is the per-date source of truth.  The group fallback
    // keeps records created before the per-story migration readable.
    return story.agendado === true || (story.agendado === undefined && group.agendado === true);
  }
  function activeDates() {
    // Every date covered by every not-yet-agendado group, plus any date the
    // employee has clicked on the calendar this session. It is valid to have
    // a manual upload and the weekly AI batch awaiting confirmation together;
    // neither may disappear from the editable area.
    const dates = new Set();
    const agendadoDates = new Set();
    for (const g of state.groups) {
      let groupHasDate = false;
      for (const story of (g.stories || [])) {
        if (!story.fecha_publicacion) continue;
        if (storyIsScheduled(story, g)) agendadoDates.add(story.fecha_publicacion);
        else if (story.estado !== 'publicado') { // ya publicada → va al Histórico, no abre una fila de día
          dates.add(story.fecha_publicacion);
          groupHasDate = true;
        }
      }
      if (!groupHasDate && !(g.stories || []).length && !g.agendado && g.scheduled_date) dates.add(g.scheduled_date);
    }
    for (const iso of draftDates) if (!agendadoDates.has(iso)) dates.add(iso);
    return dates;
  }
  function planItemsByDate() {
    // Only confirmed groups belong in Plan. Pending AI and manual groups stay
    // in "Historias generadas" until the employee schedules them.
    const byDate = new Map();
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        if (story.estado === 'publicado') continue;
        if (!story.fecha_publicacion) continue;
        if (!storyIsScheduled(story, group)) continue;
        if (!byDate.has(story.fecha_publicacion)) byDate.set(story.fecha_publicacion, {stories: [], descripcion: null});
        const entry = byDate.get(story.fecha_publicacion);
        entry.stories.push(story);
        if (!entry.descripcion && group.descripcion) entry.descripcion = group.descripcion;
      }
    }
    return byDate;
  }
  function renderPlan() {
    $('plan-panel').classList.remove('hidden');
    const byDate = planItemsByDate();
    const dates = [...byDate.keys()].sort();
    if (!dates.length) {
      $('plan-range').textContent = ''; $('plan-range').classList.add('hidden');
      $('plan-days').innerHTML = '<div class="empty">No hay más publicaciones programadas todavía.</div>';
      return;
    }
    $('plan-range').classList.remove('hidden');
    $('plan-range').textContent = dates.length === 1 ? dayLabel(dates[0]) : `${dayLabel(dates[0])} – ${dayLabel(dates[dates.length - 1])}`;
    $('plan-days').innerHTML = dates.map((iso) => {
      const entry = byDate.get(iso);
      const stories = [...entry.stories].sort((a,b) => a.order - b.order);
      const first = stories[0];
      const title = entry.descripcion || stories.map((s) => s.text).find(Boolean) || 'Sin texto todavía';
      const shortTitle = title.length > 40 ? title.slice(0, 37) + '…' : title;
      const hora = first.hora_publicacion ? String(first.hora_publicacion).slice(0,5) : '';
      const count = stories.length;
      const hasFailedStory = stories.some((story) => story.estado === 'error');
      const retryBlocked = stories.some((story) => story.estado === 'publicando');
      const canRetry = hasFailedStory && !retryBlocked;
      const retryButton = canRetry ? `<button class="icon-btn plan-chip-retry" data-plan-retry="${escapeHtml(iso)}" aria-label="Reintentar publicación fallida" title="Reintentar la publicación fallida de este día">${icon('rotate-cw', 13)}</button>` : '';
      const canDelete = stories.every((story) => !storyIsLocked(story));
      const deleteButton = canDelete ? `<button class="icon-btn plan-chip-delete" data-plan-delete="${escapeHtml(iso)}" aria-label="Eliminar toda la publicación de este día">${icon('trash', 13)}</button>` : '';
      return `<div class="plan-chip" data-plan-date="${escapeHtml(iso)}"><span class="grip">${icon('grip-vertical', 14)}</span><span class="thumb">${first.image_url ? `<img src="${escapeHtml(first.image_url)}" alt="">` : icon('image', 16)}</span><div class="plan-chip-body"><div class="date">${escapeHtml(dayLabel(iso))}${hora ? ' · ' + hora : ''}</div><div class="title">${escapeHtml(shortTitle)}</div><div class="type">${count} historia${count===1?'':'s'}</div></div>${retryButton}${deleteButton}</div>`;
    }).join('');
  }
  function groupDate(group) {
    const raw = group.scheduled_date || group.generation_week;
    return raw ? new Intl.DateTimeFormat('es-AR', {dateStyle:'long', timeZone:'UTC'}).format(new Date(`${raw}T00:00:00Z`)) : 'Sin fecha';
  }
  function publishedDateIso(story) {
    // "Publicar ahora" puede subir una historia mucho antes (o después) de su
    // fecha_publicacion planeada — el Histórico tiene que agruparla por cuándo
    // se publicó DE VERDAD, no por esa fecha planeada. published_at es un
    // timestamp UTC; lo convertimos al día calendario de Argentina (el mismo
    // huso que usa el resto del sistema) para que coincida con lo que el
    // empleado espera ver. Las filas viejas sin published_at (publicadas antes
    // de que esta columna se empezara a llenar) caen de vuelta a fecha_publicacion.
    if (!story.published_at) return story.fecha_publicacion;
    return isoDateInTimeZone(new Date(story.published_at));
  }
  function historicoItemsByDate() {
    const byDate = new Map();
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        if (story.estado !== 'publicado') continue;
        const iso = publishedDateIso(story);
        if (!iso) continue;
        if (!byDate.has(iso)) byDate.set(iso, []);
        byDate.get(iso).push(story);
      }
    }
    return byDate;
  }
  function renderHistorico(byDate) {
    const panel = $('historico-panel');
    const dates = [...byDate.keys()].sort().reverse();
    if (!dates.length) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    $('historico-list').innerHTML = dates.map((iso) => {
      const stories = [...byDate.get(iso)].sort((a, b) => a.order - b.order);
      const first = stories[0];
      const title = stories.map((s) => s.text).find(Boolean) || 'Sin texto todavía';
      const shortTitle = title.length > 28 ? title.slice(0, 25) + '…' : title;
      const count = stories.length;
      return `<div class="historico-chip" data-historico-date="${escapeHtml(iso)}"><span class="thumb">${first.image_url ? `<img src="${escapeHtml(first.image_url)}" alt="">` : icon('image', 14)}</span><div class="historico-chip-body"><div class="date">${escapeHtml(dayLabel(iso))}</div><div class="title">${escapeHtml(shortTitle)}</div><div class="type">${count} historia${count === 1 ? '' : 's'}</div></div></div>`;
    }).join('');
  }
  function renderStories() {
    // One row per date: every date is its own horizontal strip of cards ending
    // in a "+" tile, so any day can hold as many images as needed — never just one.
    const active = activeDates();
    const byDate = new Map();
    const manualGroupByDate = new Map(); // date -> its manual (non-AI) group, if any
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        if (story.estado === 'publicado') continue; // ya publicada — va al Histórico, lo arma historicoItemsByDate()
        if (storyIsScheduled(story, group)) continue; // confirmed date lives in Plan
        if (!story.fecha_publicacion || !active.has(story.fecha_publicacion)) continue;
        if (!byDate.has(story.fecha_publicacion)) byDate.set(story.fecha_publicacion, []);
        byDate.get(story.fecha_publicacion).push({group, story});
        if (!group.generation_week) manualGroupByDate.set(story.fecha_publicacion, group);
      }
    }
    for (const iso of active) if (!byDate.has(iso)) byDate.set(iso, []);
    const dates = [...byDate.keys()].sort();
    renderHistorico(historicoItemsByDate());
    if (!dates.length) {
      $('stories').innerHTML = '<div class="empty-state"><span class="empty-state-icon">' + icon('image', 34) + '</span><p class="empty-state-text">No hay historias próximas para este cliente.</p><p class="empty-state-hint">Clickeá un día del calendario para agregar una a mano, o generá la semana completa ahora.</p><button type="button" class="btn primary" data-empty-cta>' + icon('sparkles', 14) + 'Generar historias para este cliente</button></div>';
      $('week-badge').classList.add('hidden');
      return;
    }
    const first = dates[0], last = dates[dates.length - 1];
    $('week-badge').textContent = first === last ? dayLabel(first) : `${dayLabel(first)} – ${dayLabel(last)}`;
    $('week-badge').classList.remove('hidden');
    const rows = dates.map((iso) => {
      const entries = byDate.get(iso);
      const stories = entries.map(({story}) => story);
      const batches = new Map();
      for (const {group, story} of entries) {
        if (!batches.has(group.id)) batches.set(group.id, {group, stories: []});
        batches.get(group.id).stories.push(story);
      }
      const batchRows = [...batches.values()].map(({group, stories: batchStories}) => {
        batchStories.sort((a,b) => a.order - b.order);
        const label = group.generation_week ? 'Generación IA' : 'Carga manual';
        // The database rejects reordering a group once any story is locked.
        // Reflect that constraint in the UI instead of offering a drag that
        // can only fail.
        const batchReorderable = (group.stories || []).every((story) => !storyIsLocked(story));
        const cards = batchStories.map((story,index) => storyCard(story,index,group.id,batchReorderable)).join('');
        return `<div class="story-batch" data-story-group-id="${escapeHtml(group.id)}"><div class="story-batch-label">${label}</div><div class="day-row-cards">${cards}</div></div>`;
      }).join('');
      const manualGroup = manualGroupByDate.get(iso);
      // A day publishes once — AI batch and manual uploads sharing a date are
      // one publication, so "listo para agendar" only needs everything for
      // that date approved, regardless of which group(s) contributed it.
      const actionableStories = stories.filter((story) => !storyIsLocked(story));
      const readyToSchedule = actionableStories.length > 0 && actionableStories.every((story) => story.aprobado);
      const retryableStories = stories.filter((story) => story.estado === 'pendiente' || story.estado === 'error');
      const publishNowBlocked = stories.some((story) => story.estado === 'publicando');
      const readyToPublishNow = retryableStories.length > 0 && !publishNowBlocked && retryableStories.every((story) => story.aprobado);
      const unapprovedActionable = actionableStories.filter((story) => !story.aprobado);
      const approveAllBtn = unapprovedActionable.length > 1 ? `<button class="badge approve-all-btn" data-approve-all-date="${escapeHtml(iso)}">${icon('check-check', 12)}Aprobar todas (${unapprovedActionable.length})</button>` : '';
      const scheduleBtn = readyToSchedule ? `<button class="badge schedule-btn" data-schedule-date="${escapeHtml(iso)}">${icon('calendar-check', 12)}Agendar</button>` : '';
      const publishNowBtn = readyToPublishNow ? `<button class="badge publish-now-btn" data-publish-now-date="${escapeHtml(iso)}">${icon('send', 12)}Publicar ahora</button>` : '';
      const dayLocked = stories.some((story) => storyIsLocked(story));
      const timeSource = actionableStories[0] || stories[0];
      const timeValue = timeSource?.hora_publicacion ? String(timeSource.hora_publicacion).slice(0,5) : '09:00';
      const timeInput = `<input type="time" class="day-time" data-time-for="${escapeHtml(iso)}" value="${escapeHtml(timeValue)}"${dayLocked ? ' disabled title="La publicación de este día ya está en curso o finalizada"' : ''}>`;
      const descInput = manualGroup ? `<input type="text" class="day-desc" data-desc-for="${escapeHtml(iso)}" maxlength="200" value="${escapeHtml(manualGroup.descripcion || '')}" placeholder="Descripción interna (opcional) — ¿de qué van estas historias?"${dayLocked ? ' disabled' : ''}>` : '';
      const addRow = dayLocked ? '' : `<div class="day-row-cards"><div class="story add-placeholder" data-add-date="${escapeHtml(iso)}"><span class="add-icon">+</span><span class="add-label">Subir imagen</span></div><div class="story add-placeholder add-placeholder-ai" data-generate-date="${escapeHtml(iso)}"><span class="add-icon">IA</span><span class="add-label">Generar con IA</span></div></div>`;
      return `<div class="day-row" data-date="${escapeHtml(iso)}"><div class="day-row-head"><div class="day-row-top"><span class="section-title">${escapeHtml(dayLabel(iso))}</span>${approveAllBtn}${scheduleBtn}${publishNowBtn}${timeInput}</div>${descInput}</div><div class="story-batches">${batchRows}${addRow}</div></div>`;
    }).join('');
    $('stories').innerHTML = `<section class="group">${rows}</section>`;
  }
  function renderActivity() {
    const next = activeGroup();
    const activeCount = next ? (next.stories || []).length : 0;
    const rows = [];
    if (next) {
      // "generadas", no "listas" — este número incluye historias todavía sin
      // aprobar (incluso con error), no solo las ya resueltas. El ✓ daba a
      // entender que ya estaban aprobadas.
      rows.push(`<div class="activity-item"><span class="dot">${icon('image', 12)}</span><div><div>${activeCount} historia${activeCount===1?'':'s'} generada${activeCount===1?'':'s'}</div><div class="sub">Generadas con la dirección actual</div></div></div>`);
    } else {
      rows.push(`<div class="activity-item"><span class="dot">–</span><div><div>Sin historias programadas</div><div class="sub">Todavía no se generó contenido para este cliente</div></div></div>`);
    }
    if (state.driveCount !== null && state.driveCount !== undefined) {
      rows.push(`<div class="activity-item"><span class="dot">${icon('folder', 12)}</span><div><div>${state.driveCount} imagen${state.driveCount===1?'':'es'} disponible${state.driveCount===1?'':'s'} en Drive</div><div class="sub">De la carpeta del cliente</div></div></div>`);
    }
    // Solo mostrar esto si hay una historia REALMENTE agendada en algún lado —
    // antes aparecía con cualquier lote recién generado sin agendar nada,
    // porque activeGroup() cae de vuelta a state.groups[0] igual. planItemsByDate
    // ya filtra por storyIsScheduled (y excluye publicadas), así que es la
    // fuente correcta de "qué hay realmente agendado" — y de paso, al recorrer
    // todos los grupos en vez de solo `next`, muestra la fecha agendada más
    // próxima de verdad, no la del primer grupo de la lista.
    const scheduledDates = [...planItemsByDate().keys()].sort();
    if (scheduledDates.length) {
      const nextDate = scheduledDates[0];
      const dayStories = planItemsByDate().get(nextDate).stories;
      const first = [...dayStories].sort((a, b) => a.order - b.order)[0];
      const hora = first?.hora_publicacion ? ' · ' + String(first.hora_publicacion).slice(0, 5) + 'hs' : '';
      rows.push(`<div class="activity-item"><span class="dot">${icon('calendar', 12)}</span><div><div>Próxima publicación: ${escapeHtml(dayLabel(nextDate))}${hora}</div><div class="sub">Según el plan generado</div></div></div>`);
    }
    $('activity-list').innerHTML = rows.join('');
    $('activity-summary').innerHTML = state.client.generation_error
      ? `<div class="status-card warn"><span>${icon('triangle-alert', 16)}</span><div><strong>Necesita atención</strong><p>${escapeHtml(state.client.generation_error)}</p></div></div>`
      : `<div class="status-card ok"><span>${icon('check', 16)}</span><div><strong>Todo en orden</strong><p>No hay errores de generación pendientes.</p></div></div>`;
  }
  function storyCard(story, index, groupId, batchReorderable = true) {
    const dateBadge = story.fecha_publicacion ? `<span class="story-date">${escapeHtml(dayLabel(story.fecha_publicacion))}</span>` : '';
    const approvedClass = story.aprobado ? ' approved' : '';
    const approvedBadge = story.aprobado ? '<span class="approved-badge" title="Aprobada">' + icon('check', 12) + '</span>' : '';
    const locked = storyIsLocked(story);
    const reorderable = batchReorderable && !locked;
    const mutationActions = locked ? '' : '<button class="icon-btn" data-action="edit" aria-label="Editar">' + icon('pencil', 13) + '</button><button class="icon-btn" data-action="delete" aria-label="Eliminar">×</button>';
    return `<article class="story${approvedClass}${locked ? ' read-only' : ''}" draggable="${reorderable ? 'true' : 'false'}" data-reorderable="${reorderable ? 'true' : 'false'}" data-story-id="${escapeHtml(story.id)}" data-story-group-id="${escapeHtml(groupId)}">${story.image_url ? `<img src="${escapeHtml(story.image_url)}" alt="Historia ${index+1}">` : ''}<span class="story-num">${index+1}</span>${dateBadge}${approvedBadge}<div class="story-actions"><button class="icon-btn" data-action="preview" aria-label="Ver en grande">${icon('eye', 14)}</button>${mutationActions}</div><div class="story-overlay"><p class="story-text">${escapeHtml(story.text || 'Sin texto todavía')}</p></div></article>`;
  }
  async function saveClientField(field, buttonId) {
    const name = field === 'weekly_focus' ? 'focus' : field === 'topics' ? 'topics' : 'description';
    const button=$(buttonId), input=$(field==='business_description'?'business-description':field==='weekly_focus'?'weekly-focus':'client-topics'), value=field === 'topics' ? input.value.split(/\r?\n/).map((topic) => topic.trim()).filter(Boolean) : input.value.trim(), clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!clientId) return; button.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}`, {method:'PATCH', body:JSON.stringify({[field]:field === 'topics' ? value : value || null})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client = updated;
      if (field === 'topics') {
        $('client-topics').value = (updated.topics || []).join('\n');
        $('topics-count').textContent = String((updated.topics || []).length);
        renderTopicsView(updated.topics);
      } else {
        updateFieldView(name, field==='weekly_focus'?updated.weekly_focus:updated.business_description,
          field==='weekly_focus'?'Sin enfoque puntual para esta semana.':'Todavía no hay descripción. Hacé click acá para agregarla.');
      }
      exitFieldEdit(name);
      showMessage(field==='weekly_focus'?'Enfoque semanal guardado.':field==='topics'?'Temas guardados.':'Descripción guardada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) button.disabled=false; }
  }
  async function saveClientPm() {
    const select=$('client-pm'), clientId=state.client?.id, selectionVersion=state.selectionVersion, employeeId=select.value || null;
    if (!clientId || employeeId === (state.client?.assigned_employee_id || null)) return; select.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/pm`, {method:'PATCH', body:JSON.stringify({employee_id:employeeId})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client.assigned_employee_id = updated.employee_id; showMessage(updated.employee_id ? 'PM asignado.' : 'Cliente sin PM asignado.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) { showMessage(error.message,true); select.value = state.client?.assigned_employee_id || ''; } }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) select.disabled=false; }
  }
  async function saveClientFont() {
    const select=$('client-font'), clientId=state.client?.id, selectionVersion=state.selectionVersion, fontChoice=select.value || null;
    if (!clientId || fontChoice === (state.client?.font_choice || null)) return; select.disabled=true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/tipografia`, {method:'PATCH', body:JSON.stringify({font_choice:fontChoice})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client.font_choice = updated.font_choice; showMessage('Tipografía actualizada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) { showMessage(error.message,true); select.value = state.client?.font_choice || ''; } }
    finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) select.disabled=false; }
  }
  async function saveClientContact(field, inputId) {
    const input=$(`${inputId}`), clientId=state.client?.id, selectionVersion=state.selectionVersion, value=input.value.trim() || null;
    if (!clientId || value === (state.client?.[field] || null)) return;
    input.disabled = true;
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/contacto`, {method:'PATCH', body:JSON.stringify({[field]: value})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client[field] = updated[field] ?? value;
      updateContactLinks();
      showMessage('Contacto actualizado.');
    } catch(error) {
      if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) {
        showMessage(error.message, true);
        input.value = state.client?.[field] || '';
      }
    } finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) input.disabled = false; }
  }
  async function uploadClientAvatar(file) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const button = $('client-avatar-upload'); button.disabled = true;
    const formData = new FormData(); formData.append('image', file);
    try {
      const response = await fetch(`/portal/clientes/${encodeURIComponent(clientId)}/avatar`, {method:'POST', credentials:'same-origin', body: formData});
      if (response.status === 401) { window.location.assign('/login'); return; }
      if (!response.ok) { let detail = 'No se pudo subir el avatar.'; try { detail = (await response.json()).detail || detail; } catch(_) {} throw new Error(detail); }
      const updated = await response.json();
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client.avatar_url = updated.avatar_url; state.client.avatar_public_id = updated.avatar_public_id;
      $('client-avatar').innerHTML = avatarContent(state.client); $('client-avatar').classList.add('has-avatar');
      $('client-avatar-preview').innerHTML = avatarContent(state.client); $('client-avatar-preview').classList.add('has-avatar');
      const listed = state.clients.find((client) => client.id === clientId);
      if (listed) { listed.avatar_url = updated.avatar_url; listed.avatar_public_id = updated.avatar_public_id; }
      renderClients();
      showMessage('Avatar actualizado.');
    } catch(error) {
      if (selectionVersion === state.selectionVersion) showMessage(error.message, true);
    } finally { if (selectionVersion === state.selectionVersion && clientId === state.client?.id) button.disabled = false; }
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
  let ritmoDays = []; // [{day, time, count}], 1–4 days whose counts always total four stories
  let ritmoLoading = false;
  let ritmoSaving = false;
  let weeklyGenerating = false;
  let calMonthOffset = 0;
  let pendingUploadDate = null; // set right before triggering the hidden file input
  let pendingUploadHora = '09:00'; // read from that day's inline time input at the same moment
  const dayTimeSaving = new Set(); // one serialized save loop per client selection and publication date
  const pendingDayTimes = new Map(); // latest value wins within that same scoped save loop
  const publishingDates = new Set(); // block repeated manual publish clicks for the same client selection/date
  const generatingDates = new Set(); // block repeated "generar con IA" clicks for the same client selection/date
  const approvingStoryIds = new Set(); // block a second confirm dialog for the same card while one is already open/in flight
  const approvingDayDates = new Set(); // block a second "aprobar todas" confirm for the same day while one is in flight
  const schedulingPromptDates = new Set(); // only one schedule confirmation per client selection and day at a time
  const schedulingDates = new Set(); // block duplicate scheduling requests for the same client selection and day
  function dayOperationKey(clientId, selectionVersion, iso) {
    return `${selectionVersion}:${clientId}:${iso}`;
  }
  let draftDates = new Set(); // ISO dates clicked on the calendar, waiting for an image — shown as empty "+" cards in "Historias generadas"
  function monthBase() { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + calMonthOffset); return d; }
  function isoDate(year, month, day) { return `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`; }
  function todayIso() { const d = new Date(); return isoDate(d.getFullYear(), d.getMonth(), d.getDate()); }
  function calendarDotClass(story, group) {
    if (story.estado === 'error') return 'dot-error';
    if (story.estado === 'publicado') return 'dot-done';
    if (storyIsScheduled(story, group)) return 'dot-scheduled';
    if (story.aprobado) return 'dot-approved';
    return 'dot-pending';
  }
  function renderCalendarMonth() {
    const base = monthBase(), year = base.getFullYear(), month = base.getMonth();
    const monthLabel = base.toLocaleDateString('es-AR', {month:'long', year:'numeric'});
    $('cal-month-label').textContent = monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1);
    const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const cells = Array(firstWeekday).fill(null).concat(Array.from({length: daysInMonth}, (_, i) => i + 1));
    while (cells.length % 7 !== 0) cells.push(null);
    const dotClassesByDate = new Map();
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        const cls = calendarDotClass(story, group);
        // El punto "publicada" va en el día en que se publicó de verdad; los
        // demás estados siguen marcando fecha_publicacion, el día planeado.
        const iso = cls === 'dot-done' ? publishedDateIso(story) : story.fecha_publicacion;
        if (!iso) continue;
        if (!dotClassesByDate.has(iso)) dotClassesByDate.set(iso, new Set());
        dotClassesByDate.get(iso).add(cls);
      }
    }
    const today = todayIso();
    $('calendar-grid').innerHTML = cells.map((day) => {
      if (day === null) return '<div class="cal-cell outside"></div>';
      const iso = isoDate(year, month, day);
      const isPast = iso < today;
      const dotClasses = dotClassesByDate.get(iso);
      const pending = draftDates.has(iso) && !dotClasses;
      const dots = dotClasses ? `<span class="dots">${[...dotClasses].map((cls) => `<span class="dot ${cls}"></span>`).join('')}</span>` : '';
      return `<div class="cal-cell${pending?' pending':''}${isPast?' past':''}${iso===today?' today':''}" data-date="${iso}">${day}${dots}</div>`;
    }).join('');
  }
  function renderRitmoChips() {
    const activeDays = new Set(ritmoDays.map((e) => e.day));
    $('ritmo-chips').innerHTML = CAL_LABELS.map((label, day) =>
      `<span class="ritmo-chip${activeDays.has(day)?' active':''}" data-day="${day}">${label}</span>`
    ).join('');
  }
  function evenSplitCounts(n) {
    const counts = Array(n).fill(0);
    for (let i = 0; i < 4; i++) counts[(i * n) / 4 | 0]++;
    return counts;
  }
  function normalizeRitmoDays(days, publishTogether=false) {
    const sorted = (Array.isArray(days) ? days : [])
      .map((entry) => ({day:Number(entry.day), time:String(entry.time || '09:00'), count:entry.count}))
      .sort((a,b) => a.day - b.day);
    const explicit = sorted.length > 0 && sorted.every((entry) => Number.isInteger(entry.count) && entry.count >= 1 && entry.count <= 4)
      && sorted.reduce((sum, entry) => sum + entry.count, 0) === 4;
    if (explicit) return sorted;
    if (publishTogether && sorted.length) return [{...sorted[0], count:4}];
    const counts = evenSplitCounts(sorted.length);
    return sorted.map((entry, index) => ({...entry, count:counts[index]}));
  }
  function ritmoDetailEntries() {
    return [...document.querySelectorAll('#ritmo-days-detail .ritmo-day-detail')].map((row) => ({
      day:Number(row.dataset.day),
      time:row.querySelector('[data-ritmo-time]').value,
      count:Number(row.querySelector('[data-ritmo-count]').value),
    }));
  }
  function refreshRitmoDetailTotal() {
    const entries = ritmoDetailEntries();
    const valid = entries.length > 0 && entries.every((entry) => /^\d{2}:\d{2}$/.test(entry.time)
      && Number.isInteger(entry.count) && entry.count >= 1 && entry.count <= 4);
    const total = entries.reduce((sum, entry) => sum + (Number.isFinite(entry.count) ? entry.count : 0), 0);
    $('ritmo-count-total').textContent = `Total: ${total} / 4 historias`;
    $('save-ritmo-detail').disabled = ritmoSaving || weeklyGenerating || !valid || total !== 4;
    return {entries, valid, total};
  }
  function renderRitmoDaysDetail() {
    ritmoDays.sort((a,b) => a.day - b.day);
    $('ritmo-days-detail').innerHTML = ritmoDays.map((entry) => `
      <div class="ritmo-day-detail" data-day="${entry.day}">
        <strong>${CAL_LABELS[entry.day]}</strong>
        <label>Hora <input type="time" data-ritmo-time data-day="${entry.day}" value="${escapeHtml(entry.time)}"></label>
        <label>Historias <input type="number" min="1" max="4" data-ritmo-count data-day="${entry.day}" value="${entry.count}"></label>
      </div>`).join('');
    refreshRitmoDetailTotal();
  }
  function showRitmoDetailMessage(message, isError=false) {
    const feedback = $('ritmo-detail-message');
    feedback.textContent = message;
    feedback.classList.toggle('hidden', !message);
    feedback.classList.toggle('success', Boolean(message) && !isError);
  }
  function refreshRitmoControls() {
    const rhythmControlsBlocked = ritmoLoading || ritmoSaving || weeklyGenerating;
    $('ritmo-chips').classList.toggle('is-saving', rhythmControlsBlocked);
    $('ritmo-chips').setAttribute('aria-disabled', String(rhythmControlsBlocked));
    document.querySelectorAll('#ritmo-days-detail input').forEach((input) => { input.disabled = rhythmControlsBlocked; });
    refreshRitmoDetailTotal();
    $('generate-weekly').disabled = rhythmControlsBlocked || !state.client;
  }
  function setRitmoSaving(saving) {
    ritmoSaving = saving;
    refreshRitmoControls();
  }
  async function loadCalendar() {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    ritmoLoading = true;
    ritmoDays = [];
    renderRitmoChips();
    renderRitmoDaysDetail();
    refreshRitmoControls();
    calMonthOffset = 0;
    draftDates = new Set();
    renderCalendarMonth();
    let days = state.client?.publish_days;
    try {
      if (!days) { try { days = (await api('/portal/ritmo-default')).publish_days; } catch(_) { days = [{day:0,time:'09:00',count:1},{day:2,time:'09:00',count:1},{day:4,time:'09:00',count:1},{day:6,time:'09:00',count:1}]; } }
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      ritmoDays = normalizeRitmoDays(days, Boolean(state.client?.publish_together));
      renderRitmoChips();
      renderRitmoDaysDetail();
    } finally {
      if (selectionVersion === state.selectionVersion && clientId === state.client?.id) {
        ritmoLoading = false;
        refreshRitmoControls();
      }
    }
  }
  async function toggleRitmoDay(day) {
    if (ritmoSaving || weeklyGenerating) return;
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const renderedTimes = new Map(ritmoDetailEntries().map((entry) => [entry.day, entry.time]));
    ritmoDays = ritmoDays.map((entry) => ({
      ...entry,
      time:renderedTimes.has(entry.day) ? renderedTimes.get(entry.day) : entry.time,
    }));
    const idx = ritmoDays.findIndex((e) => e.day === day);
    const next = ritmoDays.map((entry) => ({...entry}));
    if (idx >= 0) {
      if (next.length === 1) { showMessage('Elegí al menos un día de publicación.', true); return; }
      next.splice(idx, 1);
    }
    else { if (next.length >= 4) { showMessage('Ya elegiste 4 días — sacá uno para agregar otro.', true); return; } next.push({day, time:'09:00', count:1}); }
    next.sort((a,b) => a.day - b.day);
    const counts = evenSplitCounts(next.length);
    next.forEach((entry, index) => { entry.count = counts[index]; });
    setRitmoSaving(true);
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/ritmo`, {method:'PATCH', body:JSON.stringify({publish_days:next})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client = {...state.client, ...updated}; ritmoDays = normalizeRitmoDays(updated.publish_days); renderRitmoChips(); renderRitmoDaysDetail();
      showMessage('Días automáticos actualizados.');
    } catch(error) { showMessage(error.message, true); }
    finally { setRitmoSaving(false); }
  }
  function openRitmoDialog() {
    if (ritmoLoading || !state.client) return;
    const feedback = $('ritmo-generation-message');
    feedback.textContent = '';
    feedback.classList.add('hidden');
    showRitmoDetailMessage('');
    renderRitmoDaysDetail();
    $('ritmo-dialog').showModal();
  }
  async function saveRitmoDetail() {
    if (ritmoSaving || weeklyGenerating) return;
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const {entries, valid, total} = refreshRitmoDetailTotal();
    if (!valid || total !== 4) {
      showRitmoDetailMessage('Los conteos deben sumar exactamente 4 y cada horario debe ser válido.', true);
      return;
    }
    showRitmoDetailMessage('');
    setRitmoSaving(true);
    try {
      const updated = await api(`/portal/clientes/${encodeURIComponent(clientId)}/ritmo`, {method:'PATCH', body:JSON.stringify({publish_days:entries})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.client = {...state.client, ...updated};
      ritmoDays = normalizeRitmoDays(updated.publish_days);
      renderRitmoChips(); renderRitmoDaysDetail();
      showRitmoDetailMessage('Días y horarios guardados.');
    } catch(error) {
      showRitmoDetailMessage(error.message, true);
    } finally {
      setRitmoSaving(false);
    }
  }
  async function generateWeeklyNow() {
    if (ritmoSaving || weeklyGenerating) return;
    const button = $('generate-weekly'), feedback = $('ritmo-generation-message');
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const previousLabel = button.textContent;
    feedback.textContent = ''; feedback.classList.add('hidden');
    weeklyGenerating = true; refreshRitmoControls(); button.textContent = 'Generando...';
    try {
      const result = await api(`/portal/clientes/${encodeURIComponent(clientId)}/generar-semana`, {method:'POST'});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      $('ritmo-dialog').close();
      await selectClient(clientId);
      showMessage(result.detail);
    } catch(error) {
      if (selectionVersion === state.selectionVersion && clientId === state.client?.id) {
        feedback.textContent = error.message;
        feedback.classList.remove('hidden');
      }
    } finally {
      weeklyGenerating = false; refreshRitmoControls(); button.textContent = previousLabel;
    }
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
      const story = await response.json();
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      // Append locally instead of refetching /historias — with several
      // uploads firing close together, whichever refetch resolved last could
      // clobber state.groups with a snapshot taken before an earlier upload's
      // write had landed, silently dropping it from the screen.
      let group = state.groups.find((g) => g.id === story.story_group_id);
      if (!group) {
        group = {id: story.story_group_id, client_id: clientId, scheduled_date: iso,
          scheduled_time: `${hora}:00`, generation_week: null, agendado: false,
          descripcion: null, stories: []};
        state.groups.push(group);
        state.groups.sort((a,b) => String(a.scheduled_date||'').localeCompare(String(b.scheduled_date||'')));
      }
      group.stories = [...(group.stories || []), story];
      draftDates.add(iso); // keep the row open so more images can be added
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage('Imagen agregada.');
    } catch(error) { showMessage(error.message, true); }
  }
  async function generateStoryForDay(iso) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    if (generatingDates.has(operationKey)) return;
    generatingDates.add(operationKey);
    const timeInput = document.querySelector(`.day-time[data-time-for="${CSS.escape(iso)}"]`);
    const hora = timeInput ? timeInput.value : '09:00';
    const tile = document.querySelector(`[data-generate-date="${CSS.escape(iso)}"]`);
    if (tile) { tile.classList.add('loading'); const label = tile.querySelector('.add-label'); if (label) label.textContent = 'Generando...'; }
    try {
      const story = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias/generar`, {method:'POST', body:JSON.stringify({fecha_publicacion:iso, hora_publicacion:hora})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      let group = state.groups.find((g) => g.id === story.story_group_id);
      if (!group) {
        group = {id: story.story_group_id, client_id: clientId, scheduled_date: iso,
          scheduled_time: `${hora}:00`, generation_week: null, agendado: false,
          descripcion: null, stories: []};
        state.groups.push(group);
        state.groups.sort((a,b) => String(a.scheduled_date||'').localeCompare(String(b.scheduled_date||'')));
      }
      group.stories = [...(group.stories || []), story];
      draftDates.add(iso);
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage('Historia generada con IA.');
    } catch(error) {
      if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
    } finally {
      generatingDates.delete(operationKey);
      if (selectionVersion === state.selectionVersion) {
        const currentTile = document.querySelector(`[data-generate-date="${CSS.escape(iso)}"]`);
        if (currentTile) { currentTile.classList.remove('loading'); const label = currentTile.querySelector('.add-label'); if (label) label.textContent = 'Generar'; }
      }
    }
  }
  async function toggleApproval(story) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    let previous;
    let approvedForScheduling = false;
    if (!clientId || storyIsLocked(story)) return;
    if (approvingStoryIds.has(story.id)) return;
    approvingStoryIds.add(story.id);
    try {
      const next = !story.aprobado;
      const confirmed = await confirmDialog(
        next
          ? '¿Aprobar esta historia? Quedará lista para agendar su publicación.'
          : '¿Quitar la aprobación de esta historia? Volverá a quedar pendiente de revisión.',
        {okLabel: next ? 'Aprobar' : 'Quitar aprobación'}
      );
      if (!confirmed || selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      previous = story.aprobado;
      story.aprobado = next; // optimistic — feels instant, reverted below on failure
      renderStories(); renderPlan();
      const updated = await api(`/portal/historias/${encodeURIComponent(story.id)}/aprobar`, {method:'PATCH', body:JSON.stringify({aprobado: next})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      Object.assign(story, updated);
      renderStories(); renderPlan();
      approvedForScheduling = next && story.fecha_publicacion;
    } catch(error) {
      if (previous !== undefined) story.aprobado = previous;
      if (selectionVersion === state.selectionVersion) {
        if (previous !== undefined) { renderStories(); renderPlan(); }
        if (!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
      }
    } finally {
      approvingStoryIds.delete(story.id);
      // Release this card before checking the whole day: the last approval
      // to settle is the one allowed to open the scheduling confirmation.
      if (approvedForScheduling) maybePromptSchedule(approvedForScheduling);
    }
  }
  async function approveAllForDay(iso) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    if (approvingDayDates.has(operationKey)) return;
    approvingDayDates.add(operationKey);
    const stories = [];
    const batchStories = [];
    let approvedForScheduling = false;
    try {
      for (const group of state.groups) {
        for (const story of (group.stories || [])) {
          if (story.fecha_publicacion === iso && !storyIsScheduled(story, group) && !storyIsLocked(story) && !story.aprobado && !approvingStoryIds.has(story.id)) stories.push(story);
        }
      }
      if (stories.length < 2) return;
      const confirmed = await confirmDialog(`¿Aprobar las ${stories.length} historias del ${dayLabel(iso)}?`, {okLabel:'Aprobar todas'});
      if (!confirmed || selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      batchStories.push(...stories.filter((story) => !approvingStoryIds.has(story.id)));
      if (!batchStories.length) return;
      for (const story of batchStories) approvingStoryIds.add(story.id); // block individual card clicks on these while the batch is in flight
      const results = await Promise.allSettled(batchStories.map((story) =>
        api(`/portal/historias/${encodeURIComponent(story.id)}/aprobar`, {method:'PATCH', body:JSON.stringify({aprobado: true})})
      ));
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      let failed = 0;
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') Object.assign(batchStories[index], result.value);
        else failed++;
      });
      renderStories(); renderPlan();
      if (failed) showMessage(`Se aprobaron ${batchStories.length - failed} de ${batchStories.length}. ${failed} fallaron, probá de nuevo.`, true);
      else showMessage('Historias aprobadas.');
      approvedForScheduling = batchStories.length - failed > 0;
    } finally {
      approvingDayDates.delete(operationKey);
      for (const story of batchStories) approvingStoryIds.delete(story.id);
      // Like individual approval, only prompt after this batch has released
      // its own locks; another finishing approval will do the same check.
      if (approvedForScheduling) maybePromptSchedule(iso);
    }
  }
  async function maybePromptSchedule(iso) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    if (schedulingPromptDates.has(operationKey)) return;
    // A day publishes once — every story dated iso (AI batch, manual upload,
    // or both) counts toward "ready", from any group not already agendado.
    const dayStories = [];
    for (const group of state.groups) {
      for (const story of (group.stories || [])) {
        if (!storyIsScheduled(story, group) && story.fecha_publicacion === iso) {
          if (storyIsLocked(story)) continue;
          if (approvingStoryIds.has(story.id)) return;
          dayStories.push(story);
        }
      }
    }
    if (!dayStories.length || !dayStories.every((s) => s.aprobado)) return;
    schedulingPromptDates.add(operationKey);
    try {
      const confirmed = await confirmDialog(`Se aprobaron todas las historias del ${dayLabel(iso)}. ¿Agendar la publicación para ese día?`, {okLabel:'Agendar'});
      if (confirmed && selectionVersion === state.selectionVersion && clientId === state.client?.id) scheduleDay(iso);
    } finally {
      schedulingPromptDates.delete(operationKey);
    }
  }
  async function scheduleDay(iso) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    if (schedulingDates.has(operationKey)) return;
    schedulingDates.add(operationKey);
    try {
      await api(`/portal/clientes/${encodeURIComponent(clientId)}/dias/${encodeURIComponent(iso)}/agendar`, {method:'PATCH'});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      const groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.groups = groups;
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage('Publicación agendada.');
    } catch(error) { showMessage(error.message, true); }
    finally { schedulingDates.delete(operationKey); }
  }
  async function publishDayNow(iso) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    if (publishingDates.has(operationKey)) return;
    const confirmed = await confirmDialog(
      `Esto publica de verdad en Instagram ahora mismo, sin esperar a la fecha agendada. ¿Confirmás para el ${dayLabel(iso)}?`,
      {okLabel:'Publicar ahora', danger:true});
    if (!confirmed) return;
    if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
    if (publishingDates.has(operationKey)) return; // another confirmation won the race
    publishingDates.add(operationKey);
    const button = document.querySelector(`[data-publish-now-date="${CSS.escape(iso)}"], [data-plan-retry="${CSS.escape(iso)}"]`);
    const previousLabel = button ? button.textContent : null;
    if (button) { button.disabled = true; button.textContent = 'Publicando...'; }
    let result = null;
    try {
      try {
        result = await api(`/portal/clientes/${encodeURIComponent(clientId)}/dias/${encodeURIComponent(iso)}/publicar-ahora`, {method:'POST'});
      } catch(error) {
        if (selectionVersion === state.selectionVersion && clientId === state.client?.id) showMessage(error.message, true);
        return;
      }
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      let groups;
      try {
        groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      } catch(refreshError) {
        showMessage(`Publicadas: ${result.publicadas}. Fallidas: ${result.fallidas}. La publicación se realizó, pero no se pudo actualizar la pantalla: ${refreshError.message}`, true);
        return;
      }
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.groups = groups;
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      showMessage(`Publicadas: ${result.publicadas}. Fallidas: ${result.fallidas}.`, result.fallidas > 0);
    } finally {
      publishingDates.delete(operationKey);
      if (button && previousLabel !== null && button.isConnected) {
        button.disabled = false; button.textContent = previousLabel;
      }
    }
  }
  async function updateDayTime(iso, hhmm, input) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId || !/^([01]\d|2[0-3]):[0-5]\d$/.test(hhmm)) return;
    const operationKey = dayOperationKey(clientId, selectionVersion, iso);
    const storiesForDay = state.groups.flatMap((group) => (group.stories||[]).filter((story) => story.fecha_publicacion === iso));
    const hasStories = storiesForDay.length > 0;
    if (!hasStories) return; // empty row: the chosen time is just read from the input at upload time
    if (storiesForDay.some((story) => storyIsLocked(story))) return;
    if (dayTimeSaving.has(operationKey)) {
      pendingDayTimes.set(operationKey, hhmm);
      return;
    }
    dayTimeSaving.add(operationKey);
    let nextValue = hhmm;
    let saveError = null;
    let groups = null;
    let retryValue = null;
    try {
      while (true) {
        await api(`/portal/clientes/${encodeURIComponent(clientId)}/dias/${encodeURIComponent(iso)}/hora`, {method:'PATCH', body:JSON.stringify({hora_publicacion:nextValue})});
        nextValue = pendingDayTimes.get(operationKey) || null;
        pendingDayTimes.delete(operationKey);
        if (nextValue) continue;
        groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
        // A change that arrived while reloading must still be persisted. Check
        // before rendering; no event can interleave between this check and the
        // synchronous cleanup below.
        nextValue = pendingDayTimes.get(operationKey) || null;
        pendingDayTimes.delete(operationKey);
        if (!nextValue) break;
      }
    } catch(error) {
      saveError = error;
      retryValue = pendingDayTimes.get(operationKey) || null;
      pendingDayTimes.delete(operationKey);
      // Always reload, including after an error: an earlier queued write may
      // already have succeeded, so local rollback alone can be stale.
      try {
        groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      } catch(refreshError) {
        saveError = saveError || refreshError;
      }
    }
    try {
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      if (groups) state.groups = groups;
      renderStories(); renderPlan(); renderCalendarMonth(); renderActivity();
      if (saveError) showMessage(saveError.message, true);
      else showMessage('Hora actualizada.');
    } finally {
      dayTimeSaving.delete(operationKey);
      const queued = pendingDayTimes.get(operationKey) || retryValue;
      pendingDayTimes.delete(operationKey);
      if (queued && selectionVersion === state.selectionVersion && clientId === state.client?.id) {
        updateDayTime(iso, queued, input);
      }
    }
  }
  async function updateDayDescription(iso, descripcion) {
    const clientId = state.client?.id, selectionVersion = state.selectionVersion;
    if (!clientId) return;
    const storiesForDay = state.groups.flatMap((group) => (group.stories||[]).filter((story) => story.fecha_publicacion === iso));
    if (storiesForDay.some((story) => storyIsLocked(story))) return;
    try {
      await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias/manual/${encodeURIComponent(iso)}/descripcion`, {method:'PATCH', body:JSON.stringify({descripcion})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      const groups = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historias`);
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id) return;
      state.groups = groups;
      renderStories(); renderPlan();
      showMessage('Descripción guardada.');
    } catch(error) { showMessage(error.message, true); }
  }
  async function openHistory() {
    const clientId = state.client?.id; if (!clientId) return;
    $('history-list').innerHTML = loadingMarkup('Cargando historial...', {compact: true}); $('history-dialog').showModal();
    try {
      const rows = await api(`/portal/clientes/${encodeURIComponent(clientId)}/historial`);
      $('history-list').innerHTML = rows.length ? rows.map((row) => `<div class="history-row"><div class="field">${escapeHtml(row.field)}</div><div class="meta">${row.changed_by_name ? escapeHtml(row.changed_by_name)+' · ' : ''}${new Date(row.changed_at).toLocaleString('es-AR')}</div><div class="diff"><span class="old">${escapeHtml(row.old_value || '(vacío)')}</span><span>${escapeHtml(row.new_value || '(vacío)')}</span></div></div>`).join('') : '<div class="empty">Todavía no hay cambios registrados para este cliente.</div>';
    } catch (error) { $('history-list').textContent = error.message; }
  }
  function openSettings() { $('settings-dialog').showModal(); }
  function findStory(storyId) { for (const group of state.groups) { const story=(group.stories||[]).find((item)=>item.id===storyId); if(story) return {group,story}; } return null; }
  function openStory(story, group) {
    if (storyIsLocked(story)) return;
    state.editingStory=story; $('story-text').value=story.text || '';
    $('story-edit-img').src = story.image_url || '';
    // Only offer AI-generated text for manually-uploaded stories — never for
    // an AI-thread story, whose text is already carefully written per-slot.
    const isManual = !!group && !group.generation_week;
    $('generate-ai-text').classList.toggle('hidden', !isManual);
    $('generate-ai-text').textContent = story.text ? 'Generar otra vez' : 'Generar con IA';
    // Changing the font recomposes the existing text onto the image, so it
    // only makes sense once the story actually has text saved.
    $('story-font').value = story.font_choice || '';
    $('story-font').disabled = !story.text;
    $('story-dialog').showModal();
  }
  async function saveStoryFont() {
    const select=$('story-font'), story=state.editingStory, clientId=state.client?.id, selectionVersion=state.selectionVersion, fontChoice=select.value || null;
    if (!story || storyIsLocked(story) || !clientId || fontChoice === (story.font_choice || null)) return;
    select.disabled=true;
    try {
      const updated = await api(`/portal/historias/${encodeURIComponent(story.id)}/tipografia`, {method:'PATCH', body:JSON.stringify({font_choice:fontChoice})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id || story !== state.editingStory) return;
      Object.assign(story, updated);
      $('story-edit-img').src = updated.image_url || '';
      renderStories(); renderPlan();
      showMessage('Tipografía actualizada.');
    } catch(error) {
      if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) { showMessage(error.message,true); select.value = story?.font_choice || ''; }
    }
    finally { if (selectionVersion === state.selectionVersion && story === state.editingStory) select.disabled=false; }
  }
  async function generateStoryText() {
    const button=$('generate-ai-text'), story=state.editingStory, clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!story || storyIsLocked(story) || !clientId) return;
    const previousLabel = button.textContent;
    button.disabled=true; button.textContent='Generando...';
    try {
      const updated = await api(`/portal/historias/${encodeURIComponent(story.id)}/generar-texto`, {method:'POST'});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id || story !== state.editingStory) return;
      Object.assign(story, updated);
      $('story-text').value = updated.text || '';
      $('story-edit-img').src = updated.image_url || '';
      $('story-font').value = updated.font_choice || ''; $('story-font').disabled = false;
      button.textContent = 'Generar otra vez';
      renderStories(); renderPlan();
      showMessage('Texto generado con IA.');
    } catch(error) {
      button.textContent = previousLabel;
      if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message, true);
    }
    finally { button.disabled=false; }
  }
  let previewStories = [], previewIndex = 0;
  function renderPreviewBars() {
    // Only stories already passed are filled — like Instagram, the one
    // currently showing starts empty rather than already complete.
    $('ig-preview-bars').innerHTML = previewStories.map((_, i) => `<span class="ig-bar${i<previewIndex?' filled':''}"></span>`).join('');
  }
  function showPreviewStory() {
    const story = previewStories[previewIndex];
    // The text is already baked into the composed image itself — no
    // separate caption overlay, or it would show up twice.
    $('ig-preview-img').src = story.image_url || '';
    const locked = storyIsLocked(story);
    $('ig-preview-edit').classList.toggle('hidden', locked);
    $('ig-preview-delete').classList.toggle('hidden', locked);
    renderPreviewBars();
  }
  function openPreview(stories) {
    previewStories = stories; previewIndex = 0;
    showPreviewStory();
    $('ig-preview-dialog').showModal();
  }
  function previewNext() { if (previewIndex < previewStories.length - 1) { previewIndex++; showPreviewStory(); } else { $('ig-preview-dialog').close(); } }
  function previewPrev() { if (previewIndex > 0) { previewIndex--; showPreviewStory(); } }
  async function saveStory() {
    const button=$('save-story'), textoNuevo=$('story-text').value.trim(), story=state.editingStory, clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if(!textoNuevo || !story || storyIsLocked(story) || !clientId)return; button.disabled=true;
    try {
      const updated=await api(`/portal/historias/${encodeURIComponent(story.id)}`, {method:'PATCH', body:JSON.stringify({texto_nuevo:textoNuevo})});
      if (selectionVersion !== state.selectionVersion || clientId !== state.client?.id || story !== state.editingStory) return;
      Object.assign(story,updated); $('story-dialog').close(); renderStories(); renderPlan(); showMessage('Historia actualizada.');
    } catch(error) { if (selectionVersion === state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
    finally { if (selectionVersion === state.selectionVersion) button.disabled=false; }
  }
  async function reorderStory(group, draggedId, targetId) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion;
    if (!clientId || draggedId === targetId) return;
    if ((group.stories || []).some((story) => storyIsLocked(story))) return;
    const stories=[...group.stories].sort((a,b)=>a.order-b.order);
    const fromIndex=stories.findIndex((item)=>item.id===draggedId), toIndex=stories.findIndex((item)=>item.id===targetId);
    if (fromIndex<0 || toIndex<0) return;
    const [moved]=stories.splice(fromIndex,1); stories.splice(toIndex,0,moved);
    const historias=stories.map((item,position)=>({story_id:item.id,nuevo_order:position+1}));
    try { await api('/portal/historias/reordenar',{method:'PATCH',body:JSON.stringify({historias})}); if(selectionVersion!==state.selectionVersion||clientId!==state.client?.id)return; stories.forEach((item,position)=>{item.order=position+1;}); group.stories=stories; renderStories(); renderPlan(); showMessage('Orden actualizado.'); }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); }
  }
  async function deleteStory(group, story) {
    const clientId=state.client?.id, selectionVersion=state.selectionVersion; if(!clientId || storyIsLocked(story))return false;
    const confirmed = await confirmDialog('¿Cancelar esta historia? Esta acción no se puede deshacer.', {okLabel:'Sí, cancelar', danger:true});
    if (!confirmed || selectionVersion!==state.selectionVersion || clientId!==state.client?.id) return false;
    try {
      await api(`/portal/historias/${encodeURIComponent(story.id)}`,{method:'DELETE'});
      if (selectionVersion!==state.selectionVersion||clientId!==state.client?.id) return false;
      group.stories=group.stories.filter((item)=>item.id!==story.id);
      renderStories(); renderPlan(); renderActivity(); showMessage('Historia cancelada.');
      return true;
    }
    catch(error) { if (selectionVersion===state.selectionVersion&&!['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true); return false; }
  }
  async function deletePlanDay(iso) {
    // Bulk-delete every story making up this day's already-scheduled
    // publication (AI + manual groups combined), same "in case something
    // wrong got uploaded" escape hatch deleteStory gives for one image.
    const clientId=state.client?.id, selectionVersion=state.selectionVersion;
    const entry = planItemsByDate().get(iso);
    if (!clientId || !entry || !entry.stories.length) return;
    if (entry.stories.some((story) => storyIsLocked(story))) return;
    const count = entry.stories.length;
    const confirmed = await confirmDialog(
      `¿Eliminar ${count === 1 ? 'esta publicación' : `las ${count} historias`} del ${dayLabel(iso)}? Esta acción no se puede deshacer.`,
      {okLabel:'Sí, eliminar', danger:true});
    if (!confirmed || selectionVersion!==state.selectionVersion || clientId!==state.client?.id) return;
    const ids = entry.stories.map((story) => story.id);
    try {
      await Promise.all(ids.map((id) => api(`/portal/historias/${encodeURIComponent(id)}`,{method:'DELETE'})));
      if (selectionVersion!==state.selectionVersion||clientId!==state.client?.id) return;
      const idSet = new Set(ids);
      for (const group of state.groups) group.stories = (group.stories||[]).filter((story) => !idSet.has(story.id));
      renderStories(); renderPlan(); renderActivity();
      showMessage('Publicación eliminada.');
    } catch(error) {
      if (selectionVersion===state.selectionVersion && !['Acceso denegado','Sesión vencida'].includes(error.message)) showMessage(error.message,true);
    }
  }
  function editPreviewStory() {
    const story = previewStories[previewIndex];
    if (!story || storyIsLocked(story)) return;
    const found = findStory(story.id);
    $('ig-preview-dialog').close();
    openStory(story, found ? found.group : null);
  }
  async function deletePreviewStory() {
    const story = previewStories[previewIndex];
    if (!story || storyIsLocked(story)) return;
    const found = story && findStory(story.id);
    if (!found) return;
    const deleted = await deleteStory(found.group, story);
    if (!deleted) return;
    previewStories = previewStories.filter((item) => item.id !== story.id);
    if (!previewStories.length) { $('ig-preview-dialog').close(); return; }
    if (previewIndex >= previewStories.length) previewIndex = previewStories.length - 1;
    showPreviewStory();
  }
  $('nav-home').addEventListener('click',showHome);
  $('nav-clients').addEventListener('click',showClients);
  $('home-view').addEventListener('click',(event)=>{
    const generate = event.target.closest('[data-home-generate]');
    if (generate) {
      const clientId = generate.dataset.homeGenerate;
      selectClient(clientId).then(() => { if (state.client?.id === clientId) openRitmoDialog(); });
      return;
    }
    const chip = event.target.closest('[data-client-id]'); if (!chip) return;
    selectClient(chip.dataset.clientId);
  });
  $('home-view').addEventListener('keydown',(event)=>{
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('.home-row');
    if (!row || event.target !== row) return;
    event.preventDefault(); row.click();
  });
  $('client-list').addEventListener('click',(event)=>{const item=event.target.closest('[data-client-id]');if(item)selectClient(item.dataset.clientId);});
  $('client-filter').addEventListener('click',(event)=>{
    const btn = event.target.closest('[data-filter]');
    if (!btn || btn.dataset.filter === $('client-filter').dataset.value) return;
    $('client-filter').dataset.value = btn.dataset.filter;
    $('client-filter').querySelectorAll('.seg-btn').forEach((el)=>{
      const selected = el === btn;
      el.classList.toggle('active', selected);
      el.setAttribute('aria-pressed', String(selected));
    });
    loadClients();
  });
  $('client-search').addEventListener('input',()=>{state.clientSearch=$('client-search').value;$('client-search-clear').classList.toggle('hidden',!$('client-search').value);renderClients();});
  $('client-search-clear').addEventListener('click',()=>{$('client-search').value='';state.clientSearch='';$('client-search-clear').classList.add('hidden');renderClients();$('client-search').focus();});
  $('save-description').addEventListener('click',()=>saveClientField('business_description','save-description'));
  $('save-focus').addEventListener('click',()=>saveClientField('weekly_focus','save-focus'));
  $('save-topics').addEventListener('click',()=>saveClientField('topics','save-topics'));
  $('try-prompt').addEventListener('click',tryPrompt);
  $('client-pm').addEventListener('change',saveClientPm);
  $('client-font').addEventListener('change',saveClientFont);
  $('client-instagram').addEventListener('change',()=>saveClientContact('instagram_profile_url','client-instagram'));
  $('client-whatsapp').addEventListener('change',()=>saveClientContact('whatsapp_contact','client-whatsapp'));
  $('client-email').addEventListener('change',()=>saveClientContact('contact_email','client-email'));
  $('client-avatar-upload').addEventListener('click',()=>$('client-avatar-input').click());
  $('client-avatar-input').addEventListener('change',()=>{
    const file = $('client-avatar-input').files[0]; $('client-avatar-input').value = '';
    if (file) uploadClientAvatar(file);
  });
  $('add-clients-bulk').addEventListener('click', () => {
    $('bulk-clients-input').value = ''; $('bulk-clients-feedback').classList.add('hidden'); $('bulk-clients-results').innerHTML = '';
    $('bulk-clients-dialog').showModal();
  });
  $('close-bulk-clients').addEventListener('click', () => $('bulk-clients-dialog').close());
  $('close-bulk-clients-2').addEventListener('click', () => $('bulk-clients-dialog').close());
  $('submit-bulk-clients').addEventListener('click', submitBulkClients);
  $('business-description').addEventListener('input',()=>{$('desc-count').textContent=String($('business-description').value.length);});
  $('weekly-focus').addEventListener('input',()=>{$('focus-count').textContent=String($('weekly-focus').value.length);});
  $('client-topics').addEventListener('input',()=>{$('topics-count').textContent=String($('client-topics').value.split(/\r?\n/).map((topic) => topic.trim()).filter(Boolean).length);});
  $('cancel-description').addEventListener('click',()=>{$('business-description').value=state.client?.business_description || ''; $('desc-count').textContent=String($('business-description').value.length); exitFieldEdit('description');});
  $('cancel-focus').addEventListener('click',()=>{$('weekly-focus').value=state.client?.weekly_focus || ''; $('focus-count').textContent=String($('weekly-focus').value.length); exitFieldEdit('focus');});
  bindFieldViewEdit('description-view', 'description', 'business-description');
  bindFieldViewEdit('focus-view', 'focus', 'weekly-focus');
  bindFieldViewEdit('topics-view', 'topics', 'client-topics');
  $('cancel-topics').addEventListener('click',()=>{$('client-topics').value=(state.client?.topics || []).join('\n'); $('topics-count').textContent=String((state.client?.topics || []).length); exitFieldEdit('topics');});
  $('content-panel-toggle').addEventListener('click',()=>$('content-panel').classList.toggle('collapsed'));
  $('plan-panel-toggle').addEventListener('click',()=>$('plan-panel').classList.toggle('collapsed'));
  $('historico-panel-toggle').addEventListener('click',()=>$('historico-panel').classList.toggle('collapsed'));
  $('qa-history').addEventListener('click',openHistory);
  $('close-history').addEventListener('click',()=>$('history-dialog').close());
  $('close-history-2').addEventListener('click',()=>$('history-dialog').close());
  $('qa-settings').addEventListener('click',openSettings);
  $('close-settings').addEventListener('click',()=>$('settings-dialog').close());
  $('close-settings-2').addEventListener('click',()=>$('settings-dialog').close());
  $('cal-prev').addEventListener('click',()=>{calMonthOffset--; renderCalendarMonth();});
  $('cal-next').addEventListener('click',()=>{calMonthOffset++; renderCalendarMonth();});
  $('calendar-grid').addEventListener('click',(event)=>{
    const cell = event.target.closest('[data-date]'); if (!cell) return;
    const iso = cell.dataset.date;
    if (iso < todayIso()) return; // past dates are view-only — the dot still shows what ran that day
    if (draftDates.has(iso)) draftDates.delete(iso); else draftDates.add(iso);
    renderStories(); renderPlan(); renderCalendarMonth();
  });
  $('manual-upload-input').addEventListener('change',(event)=>{
    const file = event.target.files[0], iso = pendingUploadDate, hora = pendingUploadHora;
    pendingUploadDate = null; event.target.value = '';
    if (file && iso) uploadManualImage(iso, hora, file);
  });
  $('open-ritmo-hero').addEventListener('click',openRitmoDialog);
  $('close-ritmo').addEventListener('click',()=>$('ritmo-dialog').close());
  $('close-ritmo-2').addEventListener('click',()=>$('ritmo-dialog').close());
  $('generate-weekly').addEventListener('click',generateWeeklyNow);
  $('save-ritmo-detail').addEventListener('click',saveRitmoDetail);
  $('ritmo-days-detail').addEventListener('input',refreshRitmoDetailTotal);
  $('ig-preview-close').addEventListener('click',()=>$('ig-preview-dialog').close());
  $('ig-preview-prev').addEventListener('click',previewPrev);
  $('ig-preview-next').addEventListener('click',previewNext);
  $('ritmo-chips').addEventListener('click',(event)=>{
    const chip = event.target.closest('[data-day]'); if (!chip) return;
    toggleRitmoDay(Number(chip.dataset.day));
  });
  $('qa-focus').addEventListener('click',()=>{$('content-panel').classList.remove('collapsed'); setFieldMode('description',true); $('business-description').scrollIntoView({behavior:'smooth',block:'center'}); $('business-description').focus();});
  $('stories').addEventListener('click',(event)=>{
    const emptyCta=event.target.closest('[data-empty-cta]');
    if (emptyCta) { openRitmoDialog(); return; }
    const approveAllBtn=event.target.closest('[data-approve-all-date]');
    if (approveAllBtn) { approveAllForDay(approveAllBtn.dataset.approveAllDate); return; }
    const scheduleBtn=event.target.closest('[data-schedule-date]');
    if (scheduleBtn) { scheduleDay(scheduleBtn.dataset.scheduleDate); return; }
    const publishNowBtn=event.target.closest('[data-publish-now-date]');
    if (publishNowBtn) { publishDayNow(publishNowBtn.dataset.publishNowDate); return; }
    const addCard=event.target.closest('[data-add-date]');
    if (addCard) {
      pendingUploadDate=addCard.dataset.addDate;
      const timeInput=document.querySelector(`.day-time[data-time-for="${CSS.escape(pendingUploadDate)}"]`);
      pendingUploadHora=timeInput ? timeInput.value : '09:00';
      $('manual-upload-input').click();
      return;
    }
    const generateCard=event.target.closest('[data-generate-date]');
    if (generateCard) { generateStoryForDay(generateCard.dataset.generateDate); return; }
    const action=event.target.closest('[data-action]'),card=event.target.closest('[data-story-id]');
    if (!card) return;
    const found=findStory(card.dataset.storyId); if(!found) return;
    if (action) {
      if(action.dataset.action==='preview')openPreview([found.story]);
      if(storyIsLocked(found.story)) return;
      if(action.dataset.action==='edit')openStory(found.story,found.group);
      if(action.dataset.action==='delete')deleteStory(found.group,found.story);
      return;
    }
    if (storyIsLocked(found.story)) return;
    toggleApproval(found.story);
  });
  let draggedStoryId = null;
  let draggedStoryGroupId = null;
  $('stories').addEventListener('dragstart',(event)=>{
    const card=event.target.closest('.story[data-story-id]'); if(!card)return;
    const found=findStory(card.dataset.storyId);
    if(card.dataset.reorderable!=='true' || !found || storyIsLocked(found.story)) { event.preventDefault(); return; }
    draggedStoryId=card.dataset.storyId;
    draggedStoryGroupId=card.dataset.storyGroupId;
    event.dataTransfer.effectAllowed='move';
    card.classList.add('dragging');
  });
  $('stories').addEventListener('dragend',(event)=>{
    const card=event.target.closest('.story[data-story-id]'); if(card)card.classList.remove('dragging');
    document.querySelectorAll('#stories .drag-over').forEach((el)=>el.classList.remove('drag-over'));
    draggedStoryId=null;
    draggedStoryGroupId=null;
  });
  $('stories').addEventListener('dragover',(event)=>{
    const card=event.target.closest('.story[data-story-id]'); if(!card||!draggedStoryId)return;
    if (card.dataset.reorderable !== 'true') return;
    if (card.dataset.storyGroupId !== draggedStoryGroupId) return;
    event.preventDefault();
    if (card.dataset.storyId!==draggedStoryId) card.classList.add('drag-over');
  });
  $('stories').addEventListener('dragleave',(event)=>{
    const card=event.target.closest('.story[data-story-id]'); if(card)card.classList.remove('drag-over');
  });
  $('stories').addEventListener('drop',(event)=>{
    const card=event.target.closest('.story[data-story-id]'); if(!card||!draggedStoryId)return;
    if (card.dataset.reorderable !== 'true') return;
    if (card.dataset.storyGroupId !== draggedStoryGroupId) return;
    event.preventDefault(); card.classList.remove('drag-over');
    const targetId=card.dataset.storyId; if(targetId===draggedStoryId)return;
    const found=findStory(draggedStoryId); if(found && !storyIsLocked(found.story))reorderStory(found.group,draggedStoryId,targetId);
  });
  $('stories').addEventListener('change',(event)=>{
    const timeInput=event.target.closest('[data-time-for]');
    if (timeInput) { updateDayTime(timeInput.dataset.timeFor, timeInput.value, timeInput); return; }
    const descInput=event.target.closest('[data-desc-for]');
    if (descInput) updateDayDescription(descInput.dataset.descFor, descInput.value.trim());
  });
  $('plan-days').addEventListener('click',(event)=>{
    const retryBtn = event.target.closest('[data-plan-retry]');
    if (retryBtn) { event.stopPropagation(); publishDayNow(retryBtn.dataset.planRetry); return; }
    const deleteBtn = event.target.closest('[data-plan-delete]');
    if (deleteBtn) { event.stopPropagation(); deletePlanDay(deleteBtn.dataset.planDelete); return; }
    const chip = event.target.closest('[data-plan-date]'); if (!chip) return;
    const entry = planItemsByDate().get(chip.dataset.planDate);
    if (entry && entry.stories.length) openPreview([...entry.stories].sort((a,b) => a.order - b.order));
  });
  $('historico-list').addEventListener('click',(event)=>{
    const chip = event.target.closest('[data-historico-date]'); if (!chip) return;
    const stories = historicoItemsByDate().get(chip.dataset.historicoDate);
    if (stories && stories.length) openPreview([...stories].sort((a,b) => a.order - b.order));
  });
  $('save-story').addEventListener('click',saveStory); $('close-story').addEventListener('click',()=>$('story-dialog').close()); $('cancel-story-edit').addEventListener('click',()=>$('story-dialog').close());
  $('generate-ai-text').addEventListener('click',generateStoryText);
  $('story-font').addEventListener('change',saveStoryFont);
  $('ig-preview-edit').addEventListener('click',editPreviewStory);
  $('ig-preview-delete').addEventListener('click',deletePreviewStory);
  $('toast-close').addEventListener('click',clearMessage);
  function setSidebarCollapsed(collapsed) {
    document.documentElement.classList.toggle('sidebar-collapsed', collapsed);
    try { localStorage.setItem('storias.sidebarCollapsed', collapsed ? '1' : '0'); } catch (_) {}
    const label = collapsed ? 'Expandir menú' : 'Plegar menú';
    $('sidebar-toggle').title = label; $('sidebar-toggle').setAttribute('aria-label', label);
  }
  function setMobileMenu(open) { document.documentElement.classList.toggle('mobile-menu-open', open); }
  function closeUserMenu() { $('me-menu').classList.add('hidden'); $('me-card').setAttribute('aria-expanded', 'false'); }
  $('sidebar-toggle').addEventListener('click', () => {
    closeUserMenu();
    setSidebarCollapsed(!document.documentElement.classList.contains('sidebar-collapsed'));
  });
  $('sidebar-menu').addEventListener('click', () => setMobileMenu(true));
  $('sidebar-scrim').addEventListener('click', () => setMobileMenu(false));
  $('client-list').addEventListener('click', () => setMobileMenu(false));
  $('nav-home').addEventListener('click', () => setMobileMenu(false));
  $('nav-clients').addEventListener('click', () => setMobileMenu(false));
  $('me-card').addEventListener('click', (event) => {
    event.stopPropagation();
    const open = !$('me-menu').classList.toggle('hidden');
    $('me-card').setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (event) => { if (!$('me-menu').contains(event.target)) closeUserMenu(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { closeUserMenu(); setMobileMenu(false); } });
  setSidebarCollapsed(document.documentElement.classList.contains('sidebar-collapsed'));
  hydrateIcons();
  loadMeAndOptions().finally(loadClients);
})();
