'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = { data: null, requests: [], inspection: null, loadingInspection: false, inspectionSequence: 0, pending: new Set(), refreshing: null, timer: null, operationSignature: '', online: false };
  const activeStates = new Set(['queued', 'claimed', 'starting', 'running', 'finalizing', 'interrupt_requested', 'interruption_requested', 'stopping']);
  const array = value => Array.isArray(value) ? value : [];
  const format = value => value === undefined ? 'Not supplied' : JSON.stringify(value, null, 2);
  const humanize = value => String(value ?? 'Unknown').replace(/[_-]+/g, ' ');
  const node = (tag, className, value) => { const element = document.createElement(tag); if (className) element.className = className; if (value !== undefined) element.textContent = String(value); return element; };
  const text = (id, value) => { $(id).textContent = String(value ?? ''); };
  function status(id, message, error = false) { text(id, message); $(id).classList.toggle('error', error); }
  function notice(message = '') { text('notice', message); $('notice').hidden = !message; }
  function jsonPre(value) { const pre = node('pre', '', format(value)); pre.tabIndex = 0; return pre; }
  function record(title, value, open = false) { const details = node('details', 'record json'); details.open = open; details.append(node('summary', '', title), jsonPre(value)); return details; }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    let data;
    try { data = await response.json(); } catch (_) { throw new Error(`The local server returned an unreadable response (${response.status}).`); }
    if (!response.ok) throw new Error(typeof data?.message === 'string' ? data.message : typeof data?.error === 'string' ? data.error : `The request failed (${response.status}).`);
    return data;
  }
  function mutate(path, payload) {
    if (!state.data?.csrf_token) throw new Error('Reload the workbench before making changes.');
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csrf_token: state.data.csrf_token, ...payload }) });
  }
  function selectOptions(id, items, placeholder, preferred) {
    const select = $(id), previous = preferred === undefined ? select.value : preferred;
    const options = [node('option', '', placeholder)]; options[0].value = '';
    for (const item of array(items)) {
      if (typeof item?.id !== 'string') continue;
      const option = node('option', '', item.label || item.id); option.value = item.id; options.push(option);
    }
    // Retain the existing nodes while polling if choices have not changed.
    const signature = JSON.stringify(options.map(option => [option.value, option.textContent]));
    if (select.dataset.options !== signature) { select.replaceChildren(...options); select.dataset.options = signature; }
    select.value = options.some(option => option.value === previous) ? previous : '';
  }
  function inspectionFromHash() {
    try { return new URLSearchParams(location.hash.slice(1)).get('inspection') || ''; } catch (_) { return ''; }
  }
  function setInspectionHash(id) {
    const hash = id ? '#inspection=' + encodeURIComponent(id) : '';
    if (location.hash !== hash) history.pushState(null, '', location.pathname + location.search + hash);
  }
  function resetAcknowledgments() { $('ack-rules').checked = false; $('ack-inputs').checked = false; }
  function completeInspection(value) {
    const object = item => item !== null && typeof item === 'object' && !Array.isArray(item);
    const inputs = value?.inputs, diffs = value?.diffs;
    return typeof value?.id === 'string' && typeof value?.revision === 'string' && /^[a-f0-9]{64}$/.test(value.inspection_digest || '') && object(inputs) && object(diffs)
      && ['request', 'parameters', 'policy', 'requirements'].every(key => object(inputs[key]))
      && Array.isArray(inputs.source) && inputs.source.length > 0 && inputs.source.every(file => object(file) && typeof file.name === 'string' && /^[a-f0-9]{64}$/.test(file.sha256 || '') && Number.isSafeInteger(file.bytes) && file.bytes >= 0 && (file.text === null || typeof file.text === 'string'))
      && Array.isArray(diffs.source) && diffs.source.every(file => object(file) && typeof file.name === 'string' && [file.before, file.after].every(text => text === null || typeof text === 'string'))
      && ['parameters', 'policy', 'requirements'].every(key => object(diffs[key]) && Object.hasOwn(diffs[key], 'before') && Object.hasOwn(diffs[key], 'after'));
  }
  function selectedOperation() {
    if (!state.inspection) return null;
    return array(state.data?.operations).find(operation => operation.inspection_id === state.inspection.id || operation.revision === state.inspection.revision) || null;
  }
  function inspectionIsCurrent() {
    if (!state.inspection || state.loadingInspection) return false;
    return array(state.data?.inspections).some(item => item.id === state.inspection.id && item.inspection_digest === state.inspection.inspection_digest);
  }
  function controls() {
    const ready = Boolean(state.online && state.data?.csrf_token), busy = state.pending.size > 0;
    $('prepare-brief').disabled = !ready || busy || !$('brief').value.trim();
    $('prepare-request').disabled = !ready || busy || !$('saved-request').value;
    $('saved-request').disabled = !ready || busy || !state.requests.length;
    $('brief').disabled = !ready || busy;
    for (const id of ['handoff', 'proposal', 'policy', 'requirements']) $(id).disabled = !ready || busy;
    $('inspect-submit').disabled = !ready || busy || !$('handoff').value || !$('proposal').value || !$('policy').value;
    $('saved-inspection').disabled = !ready || busy || !array(state.data?.inspections).length;
    $('refresh').disabled = Boolean(state.refreshing) || busy;
    const current = inspectionIsCurrent(), existing = selectedOperation();
    $('ack-rules').disabled = !ready || busy || !current || Boolean(existing);
    $('ack-inputs').disabled = $('ack-rules').disabled;
    $('run').disabled = !ready || busy || !current || Boolean(existing) || !$('ack-rules').checked || !$('ack-inputs').checked;
    text('run', existing ? 'Run already recorded' : state.pending.has('run') ? 'Recording run…' : 'Run inspected candidate');
    text('run-readiness', existing ? `Revision ${existing.revision || state.inspection.revision} already has an operation. See its durable record.` : !current ? 'Select a current inspection before acknowledging its exact inputs.' : !$('ack-rules').checked || !$('ack-inputs').checked ? 'Both acknowledgments are required. No run starts until you click the button.' : 'Ready for your explicit run decision.');
    for (const button of document.querySelectorAll('[data-interrupt]')) button.disabled = !ready || busy;
  }
  function renderRoots() {
    const roots = $('roots-list'); roots.replaceChildren();
    for (const [key, label] of [['handoffs', 'Prepared handoffs'], ['proposals', 'External proposals'], ['rules', 'Policies and requirements']]) roots.append(node('dt', '', label), node('dd', '', state.data?.roots?.[key] || 'Not configured'));
  }
  function requestPreview() {
    const request = state.requests.find(item => item.request_id === $('saved-request').value);
    text('request-preview', request ? `${request.revision_id ? 'Parent revision: ' + request.revision_id + '\n\n' : ''}${request.prompt || 'No prompt recorded.'}` : 'Saved refinements keep their parent revision and original request.');
    controls();
  }
  function renderChoices() {
    const choices = state.data?.choices || {};
    selectOptions('handoff', choices.handoffs, array(choices.handoffs).length ? 'Choose a prepared handoff…' : 'No prepared handoffs found');
    selectOptions('proposal', choices.proposals, array(choices.proposals).length ? 'Choose an external proposal…' : 'No external proposals found');
    selectOptions('policy', choices.rules, array(choices.rules).length ? 'Choose a policy JSON file…' : 'No rule files found');
    selectOptions('requirements', choices.rules, 'Keep project requirements (none for a new project)');
    selectOptions('saved-inspection', [...array(state.data?.inspections)].reverse().map(item => ({ id: item.id, label: `${item.revision || 'Revision pending'} · ${item.id}` })), 'Choose a saved inspection…', state.inspection?.id || inspectionFromHash());
    selectOptions('saved-request', state.requests.map(item => ({ id: item.request_id, label: `${item.revision_id || 'Initial model'} · ${item.prompt || item.request_id}` })), state.requests.length ? 'Choose a saved refinement…' : 'No saved refinements');
  }
  function sourceRecord(source) {
    const details = node('details', 'record'); details.append(node('summary', '', source.name || 'Unnamed source file'));
    const meta = node('div', 'source-meta');
    meta.append(node('div', '', `Size: ${source.bytes === null || source.bytes === undefined ? 'Not supplied' : source.bytes + ' bytes'}`), node('div', 'mono', `SHA-256: ${source.sha256 || 'Not supplied'}`));
    details.append(meta);
    if (typeof source.text === 'string') { const pre = node('pre', '', source.text); pre.tabIndex = 0; details.append(pre); }
    else details.append(node('p', 'source-text-note', 'Binary or unavailable text. Review this asset separately using the exact size and SHA-256 above. A missing text preview is not an empty file.'));
    return details;
  }
  function diffRecord(title, before, after, source = false, metadata = {}) {
    const details = node('details', 'record'), summary = node('summary');
    if (source) {
      const kind = metadata.before_sha256 === null && metadata.after_sha256 ? 'ADDED' : metadata.after_sha256 === null && metadata.before_sha256 ? 'REMOVED' : typeof before !== 'string' || typeof after !== 'string' ? 'TEXT UNAVAILABLE' : before === after ? 'UNCHANGED TEXT' : 'CHANGED TEXT';
      summary.append(node('span', 'file-change' + (kind === 'REMOVED' ? ' removed' : ''), kind));
    }
    summary.append(document.createTextNode(title)); details.append(summary);
    const pair = node('div', 'diff-pair');
    for (const [label, value, afterSide] of [['BEFORE', before, false], ['AFTER', after, true]]) {
      const side = node('div', 'diff-side'); side.append(node('span', 'diff-label' + (afterSide ? ' after' : ''), label));
      if (source) {
        const prefix = afterSide ? 'after' : 'before', hash = metadata[prefix + '_sha256'], bytes = metadata[prefix + '_bytes'];
        const meta = node('div', 'source-meta');
        meta.append(node('div', 'mono', `SHA-256: ${hash === null ? 'File absent' : hash || 'Not supplied'}`), node('div', '', `Size: ${bytes === null ? 'File absent' : bytes === undefined ? 'Not supplied' : bytes + ' bytes'}`)); side.append(meta);
      }
      const content = source ? typeof value === 'string' ? value : 'No text supplied for this side (file absent, binary, or unavailable). Check the full input inventory and snapshot.' : format(value);
      const pre = node('pre', '', content); pre.tabIndex = 0; side.append(pre); pair.append(side);
    }
    details.append(pair); return details;
  }
  function renderInspection(inspection) {
    if (inspection && !completeInspection(inspection)) throw new Error('The inspection does not contain complete inputs, source hashes and sizes, and before / after records. No run can be authorized from this response.');
    resetAcknowledgments(); state.inspection = inspection;
    $('inspection-empty').hidden = Boolean(inspection); $('inspection-content').hidden = !inspection;
    status('run-status', '');
    if (!inspection) { controls(); return; }
    text('inspection-revision', inspection.revision || 'Not supplied'); text('inspection-id', inspection.id);
    text('inspection-summary', format({ inspection_digest: inspection.inspection_digest, summary: inspection.summary }));
    const inputs = inspection.inputs || {}, diffs = inspection.diffs || {};
    const records = $('input-records'); records.replaceChildren();
    for (const [key, label] of [['request', 'Full request'], ['parameters', 'Parameters'], ['policy', 'Independently reviewed policy'], ['requirements', 'Requirements']]) records.append(record(label, inputs[key], key === 'policy' || key === 'requirements'));
    const sources = $('source-records'); sources.replaceChildren();
    for (const source of array(inputs.source)) sources.append(sourceRecord(source));
    if (!array(inputs.source).length) sources.append(node('p', 'empty', 'No source inventory was supplied. This does not establish that the source is safe to run.'));
    text('inputs-json', format(inputs)); text('diffs-json', format(diffs));
    const sourceDiffs = $('source-diffs'); sourceDiffs.replaceChildren();
    for (const diff of array(diffs.source)) sourceDiffs.append(diffRecord(diff.name || 'Unnamed source file', diff.before, diff.after, true, diff));
    if (!array(diffs.source).length) sourceDiffs.append(node('p', 'empty', 'No source diff records supplied.'));
    const jsonDiffs = $('json-diffs'); jsonDiffs.replaceChildren();
    for (const [key, label] of [['parameters', 'Parameters'], ['policy', 'Policy'], ['requirements', 'Requirements']]) jsonDiffs.append(diffRecord(label, diffs[key]?.before, diffs[key]?.after));
    $('saved-inspection').value = inspection.id; controls();
  }
  async function loadInspection(id, updateHistory = true) {
    const sequence = ++state.inspectionSequence;
    state.loadingInspection = true; renderInspection(null);
    if (updateHistory) setInspectionHash(id);
    if (!id) { state.loadingInspection = false; controls(); return; }
    status('inspect-status', 'Loading the saved exact-input snapshot…');
    try {
      const inspection = await api(`/api/workbench/inspections/${encodeURIComponent(id)}`);
      if (sequence !== state.inspectionSequence) return;
      if (inspection.id !== id || !inspection.inspection_digest || !inspection.inputs || !inspection.diffs) throw new Error('The saved inspection is incomplete or has a different identity. Refresh records before proceeding.');
      state.loadingInspection = false; renderInspection(inspection); status('inspect-status', 'Exact input snapshot loaded. Review its contents before acknowledging.');
    } catch (error) { if (sequence === state.inspectionSequence) { state.loadingInspection = false; renderInspection(null); status('inspect-status', error.message, true); } }
    finally { if (sequence === state.inspectionSequence) controls(); }
  }
  function outcomeRow(label, value, tone = '') { const row = node('div', 'outcome'); row.append(node('span', '', label), node('strong', tone, value)); return row; }
  function renderOperations() {
    const operations = array(state.data?.operations), signature = JSON.stringify(operations);
    text('operation-count', operations.length);
    if (signature === state.operationSignature) return;
    const openIds = new Set([...$('operations').querySelectorAll('details[open]')].map(details => details.dataset.operationId));
    state.operationSignature = signature;
    const container = $('operations'); container.replaceChildren();
    if (!operations.length) { container.append(node('p', 'empty', 'No run has been recorded. Preparing and inspecting do not start one.')); return; }
    for (const operation of [...operations].reverse()) {
      const item = node('article', 'operation'), active = activeStates.has(operation.state), failed = ['failed', 'failed_before_execution', 'error', 'rejected', 'checks_rejected', 'execution_failed', 'interrupted', 'orphaned', 'uncertain', 'unknown'].includes(operation.state);
      const heading = node('div', 'operation-top'); heading.append(node('h3', '', operation.revision || 'Revision pending'), node('span', `status-pill${active ? ' active' : failed ? ' bad' : ''}`, humanize(operation.state))); item.append(heading);
      item.append(node('p', 'operation-id', `Operation ${operation.id}`));
      if (operation.detail) item.append(node('p', 'operation-detail', typeof operation.detail === 'string' ? operation.detail : format(operation.detail)));
      const result = operation.result, verified = result?.report?.machine_verified === true && result?.revision?.machine_verified !== false, accepted = result?.state?.human_accepted === true;
      const outcomes = node('div', 'operation-outcomes');
      outcomes.append(outcomeRow('Machine checks', verified ? 'Verified' : result?.report?.machine_verified === false ? 'Not verified' : active ? 'Pending' : 'No verified evidence', verified ? 'good' : result?.report?.machine_verified === false ? 'bad' : ''), outcomeRow('Human decision', accepted ? 'Accepted separately' : 'Acceptance not recorded', accepted ? 'good' : '')); item.append(outcomes);
      if (result || operation.comparison_url === '/') { const link = node('a', 'button secondary', 'Review model and compare ↗'); link.href = '/'; item.append(link); }
      if (active && operation.can_interrupt === true) {
        const interrupt = node('button', 'button interrupt', 'Request interruption'); interrupt.type = 'button'; interrupt.dataset.interrupt = operation.id;
        interrupt.addEventListener('click', () => interruptOperation(operation.id)); item.append(interrupt);
        item.append(node('p', 'operation-detail', 'Stops only the child owned by this server. Interruption is a request, not proof the process has stopped.'));
      }
      const raw = record('Complete operation record', operation, openIds.has(operation.id)); raw.dataset.operationId = operation.id; item.append(raw); container.append(item);
    }
  }
  function scheduleRefresh() {
    clearTimeout(state.timer);
    if (document.hidden) return;
    const delay = array(state.data?.operations).some(operation => activeStates.has(operation.state)) ? 3000 : 15000;
    state.timer = setTimeout(() => refresh(false), delay);
  }
  async function refresh(includeRequests = true) {
    if (state.refreshing) return state.refreshing;
    state.refreshing = (async () => {
      try {
        const data = await api('/api/workbench');
        if (!data || !Array.isArray(data.operations) || !Array.isArray(data.inspections)) throw new Error('The workbench state is incomplete. No run can be started.');
        state.data = data; state.online = true;
        if (includeRequests) {
          try {
            const requests = await api('/api/requests');
            // The existing review endpoint also includes generated result links.
            // Only its saved 24-character refinement IDs can prepare a handoff.
            state.requests = (Array.isArray(requests) ? requests : array(requests.requests)).filter(item => typeof item.request_id === 'string' && /^[0-9a-f]{24}$/.test(item.request_id) && item.revision_id);
          }
          catch (error) { status('prepare-status', `Saved requests could not be loaded: ${error.message}`, true); }
        }
        text('project-name', data.project_name || 'Your authoring workspace'); renderRoots(); renderChoices(); renderOperations();
        text('sync-status', `Records checked at ${new Date().toLocaleTimeString()}. Read-only refresh.`);
        if (state.inspection && !inspectionIsCurrent()) { resetAcknowledgments(); status('run-status', 'The selected inspection no longer matches the server record. Reload that inspection before proceeding.', true); }
      } catch (error) { state.online = false; text('sync-status', 'Connection unavailable. Displayed records may be stale.'); notice(`${error.message} Mutating controls are disabled until records reconnect. No automatic run retry will occur.`); }
      finally { state.refreshing = null; controls(); scheduleRefresh(); }
    })();
    controls(); return state.refreshing;
  }
  async function reconcile(includeRequests = false) {
    // A GET started before a mutation may still be in flight. Never mistake that
    // old response for reconciliation of a newly created durable record.
    if (state.refreshing) await state.refreshing;
    await refresh(includeRequests);
  }
  async function prepare(kind) {
    if ((kind === 'brief' ? $('prepare-brief') : $('prepare-request')).disabled) return;
    const payload = kind === 'brief' ? { brief: $('brief').value } : { request_id: $('saved-request').value };
    state.pending.add('prepare'); controls(); status('prepare-status', 'Preparing a handoff only. No source execution starts.');
    try {
      const result = await mutate('/api/workbench/prepare', payload);
      text('handoff-json', format(result)); $('handoff-result').hidden = false; $('handoff-result').open = true;
      status('prepare-status', 'Handoff prepared. Give its complete record to the external author, then refresh the proposal choices.');
      await reconcile(true);
      const id = result.handoff_id || result.id || array(state.data?.choices?.handoffs).find(item => item.label === result.label)?.id;
      if (typeof id === 'string' && array(state.data?.choices?.handoffs).some(item => item.id === id)) $('handoff').value = id;
    } catch (error) { status('prepare-status', `${error.message} If the response was lost, refresh records and look for the handoff before preparing again.`, true); await reconcile(true); }
    finally { state.pending.delete('prepare'); controls(); }
  }
  async function inspect() {
    if ($('inspect-submit').disabled) return;
    const payload = { handoff_id: $('handoff').value, proposal_id: $('proposal').value, policy_id: $('policy').value, requirements_id: $('requirements').value || null };
    state.pending.add('inspect'); state.inspectionSequence++; state.loadingInspection = false; renderInspection(null); controls(); status('inspect-status', 'Recording the exact input snapshot. No source execution starts.');
    try {
      const result = await mutate('/api/workbench/inspect', payload);
      await reconcile(false);
      if (typeof result.id !== 'string') throw new Error('No inspection ID was returned. Refresh saved inspections before trying again.');
      if (result.inputs && result.diffs) { setInspectionHash(result.id); renderInspection(result); }
      else await loadInspection(result.id);
      status('inspect-status', 'Inspection saved. Review the exact inputs and before / after changes below.');
    } catch (error) { status('inspect-status', `${error.message} Refresh saved inspections to reconcile a lost response. No run was requested.`, true); await reconcile(false); }
    finally { state.pending.delete('inspect'); controls(); }
  }
  async function run() {
    if ($('run').disabled || !state.inspection) return;
    const inspectionId = state.inspection.id, revision = state.inspection.revision;
    state.pending.add('run'); controls(); status('run-status', `Recording one operation for ${revision}. Keep this inspection selected if the response is lost.`);
    try {
      const result = await mutate('/api/workbench/run', { inspection_id: inspectionId });
      const operation = result.operation || result;
      if (operation.id && state.data) { state.data.operations = [...array(state.data.operations).filter(item => item.id !== operation.id), operation]; renderOperations(); }
      resetAcknowledgments();
      status('run-status', `Run request recorded${operation.id ? ' as ' + operation.id : ''}. Follow the durable operation record. Machine success does not record human acceptance.`);
    } catch (error) { resetAcknowledgments(); status('run-status', `${error.message} The run may already be recorded. Checking durable operations now. Do not prepare a new inspection as a retry; any explicit retry must use this same inspection (${inspectionId}).`, true); }
    finally { await reconcile(false); state.pending.delete('run'); controls(); }
  }
  async function interruptOperation(id) {
    if (state.pending.size || !state.online) return;
    const operation = array(state.data?.operations).find(item => item.id === id);
    if (!operation || !activeStates.has(operation.state) || operation.can_interrupt !== true) return;
    state.pending.add('interrupt'); controls();
    try { await mutate('/api/workbench/interrupt', { operation_id: id }); notice(`Interruption requested for ${id}. The operation record must confirm when it has stopped.`); }
    catch (error) { notice(`${error.message} Interruption is not confirmed. Refresh the operation record before trying again.`); }
    finally { await reconcile(false); state.pending.delete('interrupt'); controls(); }
  }
  $('brief-form').addEventListener('submit', event => { event.preventDefault(); prepare('brief'); });
  $('request-form').addEventListener('submit', event => { event.preventDefault(); prepare('request'); });
  $('inspect-form').addEventListener('submit', event => { event.preventDefault(); inspect(); });
  $('brief').addEventListener('input', controls); $('saved-request').addEventListener('change', requestPreview);
  for (const id of ['handoff', 'proposal', 'policy', 'requirements']) $(id).addEventListener('change', () => {
    state.inspectionSequence++; state.loadingInspection = false; renderInspection(null); $('saved-inspection').value = ''; setInspectionHash(''); status('inspect-status', 'Input selection changed. Inspect this selection before running.'); controls();
  });
  $('saved-inspection').addEventListener('change', () => loadInspection($('saved-inspection').value));
  for (const id of ['ack-rules', 'ack-inputs']) $(id).addEventListener('change', controls);
  $('run').addEventListener('click', run);
  $('refresh').addEventListener('click', async () => { notice(); await refresh(true); requestPreview(); });
  for (const [button, other, show, hide] of [['show-inputs', 'show-diffs', 'inputs-panel', 'diffs-panel'], ['show-diffs', 'show-inputs', 'diffs-panel', 'inputs-panel']]) $(button).addEventListener('click', () => { $(button).setAttribute('aria-pressed', 'true'); $(other).setAttribute('aria-pressed', 'false'); $(show).hidden = false; $(hide).hidden = true; });
  window.addEventListener('popstate', () => loadInspection(inspectionFromHash(), false));
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(state.timer); else refresh(false); });
  window.addEventListener('pageshow', event => { if (event.persisted) { resetAcknowledgments(); refresh(true); } });
  async function start() { await refresh(true); const id = inspectionFromHash(); if (id) await loadInspection(id, false); controls(); }
  start();
})();
