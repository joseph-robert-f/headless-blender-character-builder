'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { project: null, data: null, selected: null, revisionId: null, compare: false, edges: false, loading: false, yaw: -.65, pitch: .48, zoom: 1, request: 0, frame: 0 };
  const preview = { current: null, before: null, bounds: null };
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const text = (id, value) => { $(id).textContent = value; };
  const humanize = value => String(value ?? '').replace(/[_-]+/g, ' ');
  const format = value => value === null || value === undefined ? 'Not provided' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  const date = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(d.valueOf()) ? String(value) : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); };
  function notice(message = '') { text('notice', message); $('notice').hidden = !message; }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    let data; try { data = await response.json(); } catch (_) { throw new Error(`The server returned an unreadable response (${response.status}).`); }
    if (!response.ok) throw new Error(data.message || data.error || `Request failed (${response.status})`);
    return data;
  }
  function artifactUrl(value) {
    if (typeof value !== 'string') return null;
    try { const url = new URL(value, location.origin); return url.origin === location.origin && url.pathname.startsWith('/artifacts/') ? url.href : null; } catch (_) { return null; }
  }
  function statusIcon(id, passed, failed = false) { const node = $(id); node.className = 'milestone-icon' + (passed ? ' pass' : failed ? ' fail' : ''); node.textContent = passed ? '✓' : failed ? '!' : '○'; }
  function renderHistory() {
    const list = $('revision-list'); list.replaceChildren();
    const revisions = [...(state.project?.revisions || [])].reverse(); text('revision-count', revisions.length);
    if (!revisions.length) { list.append(el('p', 'empty', 'No local revisions found. Build a candidate to begin a review.')); return; }
    for (const revision of revisions) {
      const button = el('button', 'revision-item'); button.type = 'button'; button.setAttribute('aria-current', String(revision.id === state.revisionId));
      const failed = revision.status === 'rejected'; button.append(el('span', 'revision-dot' + (revision.machine_verified ? ' pass' : failed ? ' fail' : '')));
      const label = el('span', 'revision-text'); label.append(el('strong', '', revision.id));
      label.append(el('small', '', revision.human_accepted ? 'Human accepted' : revision.machine_verified ? 'Machine verified' : failed ? 'Checks failed' : 'Needs review'));
      button.append(label); button.addEventListener('click', () => loadRevision(revision.id)); list.append(button);
    }
  }
  function renderQueue() {
    const list = $('request-queue'); list.replaceChildren();
    const requests = state.project?.requests; text('queue-count', Array.isArray(requests) ? requests.length : '—');
    if (!Array.isArray(requests)) { list.append(el('p', 'empty', 'Request history is not available from this server.')); return; }
    if (!requests.length) { list.append(el('p', 'empty', 'No saved requests yet.')); return; }
    for (const request of [...requests].reverse()) {
      const item = el('details', 'queue-item'); const heading = el('summary');
      heading.append(el('span', '', `Revision ${request.revision_id}`), el('span', 'status-pill', humanize(request.status || 'Unknown status')));
      item.append(heading, el('p', '', request.prompt || 'No prompt recorded'));
      const meta = el('div', 'queue-meta'); meta.append(el('span', '', date(request.created_at)), el('span', '', request.execution === 'not_started' ? 'Execution not started' : humanize(request.execution || 'Execution unknown')));
      item.append(meta, el('div', 'queue-id', request.request_id || '')); list.append(item);
    }
  }
  function readiness() {
    const data = state.data; const report = data?.report; const rows = report?.requirements || [];
    const verified = report?.machine_verified === true && data?.state?.machine_verified !== false;
    const hardPass = rows.every(row => row.hard === false || row.applicable === false || row.status === 'pass');
    const hasIdentity = Boolean(state.project?.csrf_token && data?.revision?.result_hash && state.revisionId && !state.loading);
    return { verified, hardPass, hasIdentity, accepted: data?.state?.human_accepted === true };
  }
  function updateControls() {
    const { verified, hardPass, hasIdentity, accepted } = readiness();
    $('accept-submit').disabled = !hasIdentity || !verified || !hardPass || accepted;
    $('accept-notes').disabled = $('accept-submit').disabled;
    $('request-prompt').disabled = !hasIdentity; $('request-submit').disabled = !hasIdentity;
    text('accept-submit', accepted ? 'Acceptance recorded' : 'Accept this revision');
  }
  function measurementSummary(row) {
    const m = row.measured || {}, e = row.expected || {};
    const number = value => Number.isFinite(value) ? new Intl.NumberFormat(undefined, { maximumSignificantDigits: 5 }).format(value) : 'not measured';
    if (row.applicable === false) return 'Not applicable to this initial model; no earlier revision exists to compare.';
    if (row.status === 'unknown') return row.evidence?.reason || 'This requirement has not been verified.';
    if (row.kind === 'connected_path') return `${m.connected ? 'A path connects' : 'No path connects'} the selected regions. ${number(m.reachable_vertices || 0)} vertices are reachable; a connected path is required.`;
    if (row.kind === 'clearance_path') return `Smallest sampled clearance: ${number(m.minimum_sampled_clearance)} m; required at least ${number(e.min_clearance)} m. ${m.blocked_segments?.length || 0} of ${number(m.segments)} path segments are blocked.`;
    if (row.kind === 'preserved_region') return `Largest vertex movement: ${number(m.max_vertex_displacement)} m; allowed at most ${number(e.tolerance)} m. Protected surface and material comparison: ${m.contained_triangle_topology_equal && m.part_materials_equal ? 'unchanged' : 'changed'}.`;
    if (row.kind === 'preserved_rays') return `Largest sampled surface movement: ${number(m.maximum_first_hit_displacement)} m; allowed at most ${number(e.tolerance)} m. ${m.missing_hit_rays?.length || 0} missing hits across ${number(m.rays)} rays.`;
    if (row.kind === 'preserved_part') return `Geometry, transform and materials ${Object.values(m).every(Boolean) ? 'match' : 'do not all match'} the accepted parent.`;
    return '';
  }
  function renderRequirements(report) {
    const rows = Array.isArray(report?.requirements) ? report.requirements : [];
    text('requirement-count', rows.length); const list = $('requirements'); list.replaceChildren();
    const counts = { pass: 0, fail: 0, unknown: 0 }; rows.forEach(row => counts[['pass', 'fail'].includes(row.status) ? row.status : 'unknown']++);
    const summary = $('requirement-summary'); summary.replaceChildren();
    for (const [status, label] of [['pass', 'passed'], ['fail', 'failed'], ['unknown', 'unknown']]) if (counts[status]) summary.append(el('span', `status-pill ${status}`, `${counts[status]} ${label}`));
    if (!rows.length) list.append(el('p', 'empty', 'No requirement evidence is available. This does not establish a pass.'));
    for (const row of rows) {
      const status = ['pass', 'fail'].includes(row.status) ? row.status : 'unknown';
      const details = el('details', 'requirement'); const heading = el('summary');
      const icon = el('span', `check-icon ${status}`, status === 'pass' ? '✓' : status === 'fail' ? '×' : '?'); icon.setAttribute('aria-label', status);
      heading.append(icon, el('span', '', row.title || humanize(row.id) || 'Requirement'), el('span', 'chevron', '›')); details.append(heading);
      const content = el('div', 'requirement-details');
      const readable = measurementSummary(row); if (readable) content.append(el('p', 'measurement-summary', readable));
      for (const [label, value] of [['Measured', row.measured], ['Expected', row.expected], ['Evidence', row.evidence], ['Coverage', row.coverage]]) {
        if (value === undefined || value === null) continue;
        const line = el('div', 'evidence-row'); line.append(el('strong', '', label), el(typeof value === 'object' ? 'pre' : 'span', '', format(value))); content.append(line);
      }
      if (!content.childNodes.length) content.append(el('p', '', 'No additional evidence was recorded.'));
      if (row.applicable === false) content.append(el('p', '', 'Not applicable to this revision; excluded from required checks.'));
      if (row.hard === false) content.append(el('p', '', 'Advisory check'));
      details.append(content); if (status !== 'pass') details.open = true; list.append(details);
    }
  }
  function renderState(data) {
    const revision = data.revision || {}; const { verified, accepted, hardPass } = readiness();
    const built = Boolean(data.observation?.parts && Object.keys(data.observation.parts).length);
    text('revision-title', `Revision ${revision.id || state.revisionId}`);
    text('revision-description', revision.parent ? `Compared with ${revision.parent} · Inspection-backed model review` : 'Initial model · Inspection-backed model review');
    text('built-status', built ? 'Inspected geometry available' : 'No inspected geometry'); statusIcon('built-icon', built);
    text('verified-status', verified ? 'Required checks passed' : revision.status === 'rejected' ? 'One or more checks failed' : 'Not established'); statusIcon('verified-icon', verified, revision.status === 'rejected');
    text('accepted-status', accepted ? 'Human decision recorded' : 'Awaiting your decision'); statusIcon('accepted-icon', accepted);
    text('decision-title', accepted ? 'Acceptance recorded' : 'Ready for your review');
    text('decision-copy', accepted ? `Accepted${data.state.accepted_at ? ' ' + date(data.state.accepted_at) : ''}. This record is separate from machine verification.` : !verified || !hardPass ? 'Human acceptance is unavailable until machine verification is established and all required checks pass.' : 'Inspect the model and its evidence before recording your acceptance.');
    $('accept-notes').value = data.state?.notes || ''; updateControls();
  }
  function renderProvenance(data) {
    const list = $('provenance-list'); list.replaceChildren();
    const revision = data.revision || {}; const report = data.report || {};
    for (const [label, value] of [['Revision', revision.id || state.revisionId], ['Parent', revision.parent || 'Initial revision'], ['Result hash', revision.result_hash], ['Build status', revision.status], ['Execution mode', revision.execution_mode || report.execution_mode], ['Security boundary', revision.security_boundary || report.security_boundary], ['Report version', report.schema_version]]) {
      if (value !== undefined) list.append(el('dt', '', label), el('dd', '', format(value)));
    }
  }
  function renderArtifacts(data) {
    const artifacts = data.artifacts || {}; const glb = artifactUrl(artifacts.glb_url); const link = $('download-glb'); link.hidden = !glb; if (glb) link.href = glb; else link.removeAttribute('href');
    const list = $('render-list'); list.replaceChildren();
    for (const view of Array.isArray(artifacts.views) ? artifacts.views : []) {
      const url = artifactUrl(view.url); if (!url) continue;
      const tile = el('a', 'render-tile'); tile.href = url; tile.target = '_blank'; tile.rel = 'noopener';
      const img = el('img'); img.src = url; img.alt = view.label ? `${view.label} inspection render` : 'Inspection render'; img.loading = 'lazy';
      tile.append(img, el('span', '', view.label || 'Inspection view')); list.append(tile);
    }
    $('render-section').hidden = !list.childNodes.length;
  }
  async function loadRevision(id) {
    const request = ++state.request; state.loading = true; state.revisionId = id; state.data = null; updateControls(); renderHistory(); notice(''); renderState({}); renderRequirements(null); renderProvenance({}); renderArtifacts({}); setGeometry({});
    text('revision-title', `Revision ${id}`); text('revision-description', 'Loading inspection evidence…');
    try {
      const data = await api(`/api/revisions/${encodeURIComponent(id)}`); if (request !== state.request) return;
      state.data = data; state.loading = false; renderState(data); renderRequirements(data.report); renderProvenance(data); renderArtifacts(data); setGeometry(data);
      text('request-status', ''); text('accept-status', 'Acceptance records a human decision. It does not change the machine-check result.');
      $('request-prompt').value = '';
    } catch (error) { if (request !== state.request) return; state.loading = false; state.data = null; updateControls(); notice(error.message); text('revision-description', 'Revision evidence could not be loaded'); setGeometry({}); }
  }
  function prepare(observation) {
    const parts = []; let totalTriangles = 0, totalVertices = 0, simplified = false;
    for (const [name, part] of Object.entries(observation?.parts || {})) {
      if (!Array.isArray(part.world_vertices) || !Array.isArray(part.triangle_indices)) continue;
      const vertices = part.world_vertices; const validVertex = v => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
      const triangles = []; const step = Math.max(1, Math.ceil(part.triangle_indices.length / 40000)); simplified ||= step > 1;
      for (let i = 0; i < part.triangle_indices.length; i += step) {
        const ids = part.triangle_indices[i]; if (!Array.isArray(ids) || ids.length !== 3 || !ids.every(j => Number.isInteger(j) && j >= 0 && j < vertices.length && validVertex(vertices[j]))) continue;
        const material = part.materials?.[part.triangle_material_indices?.[i] || 0]; const color = material?.base_color || part.material_color || [.36, .49, .38, 1];
        triangles.push({ points: ids.map(j => vertices[j]), color: color.slice(0, 3).map(c => Number.isFinite(c) ? Math.max(0, Math.min(1, c)) : .5) });
      }
      totalTriangles += part.triangle_indices.length; totalVertices += vertices.length;
      parts.push({ name, triangles, color: part.materials?.[0]?.base_color || part.material_color || [.36, .49, .38] });
    }
    return { parts, totalTriangles, totalVertices, simplified };
  }
  function setGeometry(data) {
    preview.current = prepare(data.observation); preview.before = prepare(data.parent_observation); state.selected = null;
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (const model of [preview.current, preview.before]) for (const part of model.parts) for (const triangle of part.triangles) for (const point of triangle.points) for (let axis = 0; axis < 3; axis++) { min[axis] = Math.min(min[axis], point[axis]); max[axis] = Math.max(max[axis], point[axis]); }
    preview.bounds = Number.isFinite(min[0]) ? { center: min.map((v, i) => (v + max[i]) / 2), radius: Math.max(.001, Math.hypot(...min.map((v, i) => max[i] - v)) / 2), min, max } : null;
    const hasParent = Boolean(preview.before.parts.length); $('compare-mode').disabled = !hasParent; if (!hasParent) state.compare = false;
    text('parent-label', data.revision?.parent || ''); text('current-label', data.revision?.id || state.revisionId || '');
    $('preview-empty').hidden = Boolean(preview.current.parts.length);
    text('geometry-stats', preview.current.parts.length ? `${preview.current.parts.length} parts · ${preview.current.totalTriangles.toLocaleString()} triangles${preview.current.simplified ? ' · Simplified preview' : ''}` : 'No mesh evidence');
    const list = $('part-list'); list.replaceChildren();
    for (const part of preview.current.parts) {
      const button = el('button', 'part-chip'); button.type = 'button'; button.setAttribute('aria-pressed', 'false'); const swatch = el('span', 'part-swatch'); swatch.style.backgroundColor = colorString(part.color, 1);
      button.append(swatch, document.createTextNode(humanize(part.name))); button.addEventListener('click', () => { state.selected = state.selected === part.name ? null : part.name; for (const other of list.children) other.setAttribute('aria-pressed', String(other === button && state.selected !== null)); redraw(); }); list.append(button);
    }
    if (!list.childNodes.length) list.append(el('p', 'empty', 'Parts appear after a successful inspection.'));
    setCompare(state.compare); resetCamera();
  }
  function colorString(color, light) { return `rgb(${color.slice(0, 3).map(v => Math.round(255 * Math.pow(Math.max(0, Math.min(1, v)), 1 / 2.2) * light)).join(',')})`; }
  function draw(canvas, model) {
    const rect = canvas.getBoundingClientRect(); if (!rect.width || !rect.height) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2); const width = rect.width, height = rect.height;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) { canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); }
    const context = canvas.getContext('2d'); context.setTransform(dpr, 0, 0, dpr, 0, 0); context.clearRect(0, 0, width, height);
    if (!preview.bounds) return;
    const { center, radius, min } = preview.bounds; const scale = Math.min(width, height) * .39 / radius * state.zoom;
    const sy = Math.sin(state.yaw), cy = Math.cos(state.yaw), sp = Math.sin(state.pitch), cp = Math.cos(state.pitch);
    const project = point => { const x = point[0] - center[0], y = point[1] - center[1], z = point[2] - center[2]; const depth = sy * x + cy * y; return [width / 2 + (cy * x - sy * y) * scale, height * .53 + (sp * depth - cp * z) * scale, cp * depth + sp * z]; };
    context.lineWidth = .65; context.strokeStyle = '#dfe5d9';
    for (let i = -8; i <= 8; i++) {
      const step = radius / 4; const plane = min[2] - radius * .025;
      for (const line of [[[center[0] + i * step, center[1] - 2 * radius, plane], [center[0] + i * step, center[1] + 2 * radius, plane]], [[center[0] - 2 * radius, center[1] + i * step, plane], [center[0] + 2 * radius, center[1] + i * step, plane]]]) {
        const a = project(line[0]), b = project(line[1]); context.beginPath(); context.moveTo(a[0], a[1]); context.lineTo(b[0], b[1]); context.stroke();
      }
    }
    const facets = [];
    for (const part of model?.parts || []) for (const triangle of part.triangles) {
      const p = triangle.points.map(project); const a = triangle.points[0], b = triangle.points[1], c = triangle.points[2];
      const ab = b.map((v, i) => v - a[i]), ac = c.map((v, i) => v - a[i]); const normal = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]; const length = Math.hypot(...normal) || 1;
      const light = .60 + .35 * Math.abs((normal[0] * -.35 + normal[1] * -.45 + normal[2] * .82) / length);
      facets.push({ p, depth: (p[0][2] + p[1][2] + p[2][2]) / 3, color: triangle.color, light, selected: state.selected === part.name, dim: state.selected && state.selected !== part.name });
    }
    facets.sort((a, b) => a.depth - b.depth);
    for (const facet of facets) {
      context.beginPath(); context.moveTo(facet.p[0][0], facet.p[0][1]); context.lineTo(facet.p[1][0], facet.p[1][1]); context.lineTo(facet.p[2][0], facet.p[2][1]); context.closePath();
      context.globalAlpha = facet.dim ? .23 : 1; context.fillStyle = colorString(facet.color, facet.light); context.fill();
      if (state.edges || facet.selected) { context.strokeStyle = facet.selected ? '#275d46' : '#29483655'; context.lineWidth = facet.selected ? .65 : .35; context.stroke(); }
    }
    context.globalAlpha = 1;
  }
  function redraw() { if (!state.frame) state.frame = requestAnimationFrame(() => { state.frame = 0; draw($('model-canvas'), preview.current); if (state.compare) draw($('before-canvas'), preview.before); }); }
  function resetCamera() { state.yaw = -.65; state.pitch = .48; state.zoom = 1; redraw(); }
  function setCompare(value) { state.compare = value; $('before-pane').hidden = !value; $('canvas-layout').classList.toggle('comparing', value); $('current-mode').setAttribute('aria-pressed', String(!value)); $('compare-mode').setAttribute('aria-pressed', String(value)); redraw(); }
  for (const canvas of [$('model-canvas'), $('before-canvas')]) {
    let pointer = null;
    canvas.addEventListener('pointerdown', event => { if (event.button !== 0) return; pointer = { id: event.pointerId, x: event.clientX, y: event.clientY }; canvas.setPointerCapture(event.pointerId); });
    canvas.addEventListener('pointermove', event => { if (!pointer || pointer.id !== event.pointerId) return; state.yaw += (event.clientX - pointer.x) * .008; state.pitch = Math.max(-1.35, Math.min(1.35, state.pitch + (event.clientY - pointer.y) * .008)); pointer.x = event.clientX; pointer.y = event.clientY; redraw(); });
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(name, () => { pointer = null; });
    canvas.addEventListener('wheel', event => { event.preventDefault(); state.zoom = Math.max(.35, Math.min(5, state.zoom * Math.exp(-event.deltaY * .001))); redraw(); }, { passive: false });
    canvas.addEventListener('keydown', event => { const action = { ArrowLeft: () => state.yaw -= .1, ArrowRight: () => state.yaw += .1, ArrowUp: () => state.pitch = Math.min(1.35, state.pitch + .1), ArrowDown: () => state.pitch = Math.max(-1.35, state.pitch - .1), '+': () => state.zoom = Math.min(5, state.zoom * 1.1), '=': () => state.zoom = Math.min(5, state.zoom * 1.1), '-': () => state.zoom = Math.max(.35, state.zoom / 1.1), '0': resetCamera }[event.key]; if (action) { event.preventDefault(); action(); redraw(); } });
    new ResizeObserver(redraw).observe(canvas);
  }
  $('current-mode').addEventListener('click', () => setCompare(false)); $('compare-mode').addEventListener('click', () => setCompare(true)); $('reset-view').addEventListener('click', resetCamera);
  $('wireframe').addEventListener('click', () => { state.edges = !state.edges; $('wireframe').setAttribute('aria-pressed', String(state.edges)); redraw(); });
  $('accept-form').addEventListener('submit', async event => {
    event.preventDefault(); if ($('accept-submit').disabled) return;
    const revisionId = state.revisionId; const payload = { csrf_token: state.project.csrf_token, expected_result_hash: state.data.revision.result_hash, notes: $('accept-notes').value.trim() };
    $('accept-submit').disabled = true; text('accept-status', 'Recording your decision…');
    try {
      const result = await api(`/api/revisions/${encodeURIComponent(revisionId)}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (revisionId !== state.revisionId) return; state.data.state = { ...state.data.state, ...result }; renderState(state.data); const revision = state.project.revisions.find(item => item.id === revisionId); if (revision) revision.human_accepted = result.human_accepted === true; renderHistory(); text('accept-status', 'Your acceptance is saved against this exact result.');
    } catch (error) { if (revisionId === state.revisionId) { updateControls(); text('accept-status', error.message); } }
  });
  $('request-form').addEventListener('submit', async event => {
    event.preventDefault(); if ($('request-submit').disabled) return;
    const prompt = $('request-prompt').value.trim(); if (!prompt) { $('request-prompt').focus(); return; }
    const revisionId = state.revisionId; const payload = { csrf_token: state.project.csrf_token, revision_id: revisionId, expected_result_hash: state.data.revision.result_hash, prompt };
    $('request-submit').disabled = true; text('request-status', 'Saving request…');
    try {
      const result = await api('/api/requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (revisionId !== state.revisionId) return; $('request-prompt').value = ''; text('request-status', result.message || `Request ${result.request_id || ''} saved (${result.status || 'queued'}).`);
      try { state.project = await api('/api/project'); renderQueue(); renderHistory(); }
      catch (_) { text('request-status', 'Request saved. The queue could not refresh; reload to see its persisted record.'); }
    } catch (error) { if (revisionId === state.revisionId) text('request-status', error.message); }
    finally { if (revisionId === state.revisionId) updateControls(); }
  });
  async function start() {
    try { state.project = await api('/api/project'); text('project-name', state.project.project_name || 'Source modeling'); renderHistory(); renderQueue(); const id = state.project.latest_revision || state.project.revisions?.[0]?.id; if (id) await loadRevision(id); else { text('revision-title', 'Your model workspace'); text('revision-description', 'No revisions are available to review yet'); setGeometry({}); } }
    catch (error) { notice(error.message); text('revision-title', 'Workspace unavailable'); text('revision-description', 'Check the local server, then reload this page'); $('revision-list').replaceChildren(el('p', 'empty', 'Could not read revision history.')); }
  }
  start();
})();
