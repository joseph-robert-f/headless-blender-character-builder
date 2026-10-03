'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let data = null, preview = null, busy = false, online = false, sequence = 0;
  const rows = value => Array.isArray(value) ? value : [];
  const message = text => { $('model-status').textContent = text; };
  function options(id, items) {
    const select = $(id), selected = select.value, signature = JSON.stringify(items);
    if (select.dataset.items === signature) return;
    select.dataset.items = signature;
    select.replaceChildren(new Option('Choose an item…', ''));
    for (const item of items) select.add(new Option(item.label, item.id));
    select.value = items.some(item => item.id === selected) ? selected : '';
  }
  function controls() {
    const enabled = online && data?.authoring?.enabled === true && !busy;
    const consumed = preview && rows(data?.authoring?.calls).some(row => row.id === preview.id);
    $('model-handoff').disabled = !enabled;
    $('model-preview').disabled = !enabled || !$('model-handoff').value;
    $('model-saved-preview').disabled = !enabled;
    $('model-consent').disabled = !enabled || !preview || consumed;
    $('model-submit').disabled = !enabled || !preview || consumed || !$('model-consent').checked;
    $('model-submit').textContent = consumed ? 'Request already recorded' : 'Send one model request';
  }
  function clearPreview() {
    preview = null; $('model-consent').checked = false; $('model-preview-record').hidden = true; controls();
  }
  function showPreview(value) {
    if (!value || typeof value.id !== 'string' || !/^[a-f0-9]{64}$/.test(value.digest || '') || !value.outbound || !value.config) throw new Error('Incomplete outbound preview. No approval is available.');
    preview = value; $('model-consent').checked = false;
    $('model-preview-json').textContent = JSON.stringify(value, null, 2);
    $('model-preview-record').hidden = false; $('model-preview-record').open = true; controls();
  }
  async function api(path, payload) {
    const response = await fetch(path, payload === undefined ? { cache: 'no-store', credentials: 'same-origin' } : {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csrf_token: data.csrf_token, ...payload }) });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Local model request failed.');
    return value;
  }
  async function action(name, payload) {
    if (busy || !online) return;
    busy = true; controls();
    try {
      const value = await api('/api/workbench/model/' + name, payload);
      if (name === 'preview') { showPreview(value); message('Review the complete outbound payload. No provider call has been made.'); }
      else { $('model-consent').checked = false; message(name === 'submit' ? 'Request recorded. Follow its durable status. No source execution was requested.' : 'Cancellation requested. Charges may apply.'); }
    } catch (error) { $('model-consent').checked = false; message(error.message + ' Check the durable records before another action. No automatic retry occurs.'); }
    finally { busy = false; controls(); window.dispatchEvent(new Event('workbench-refresh')); }
  }
  function renderCalls() {
    const root = $('model-calls'); root.replaceChildren();
    for (const call of rows(data?.authoring?.calls)) {
      const article = document.createElement('article'); article.className = 'operation';
      const title = document.createElement('h3'); title.textContent = `Model request ${call.id}: ${call.state}`;
      const detail = document.createElement('p'); detail.textContent = call.detail;
      const usage = document.createElement('pre'); usage.textContent = JSON.stringify({ model: call.model, reserved_usd: call.reserved_usd, usage: call.usage, proposal: call.proposal_label }, null, 2);
      article.append(title, detail, usage);
      if (call.can_cancel) { const button = document.createElement('button'); button.type = 'button'; button.className = 'button secondary'; button.textContent = 'Cancel model request'; button.disabled = busy || !online; button.addEventListener('click', () => action('cancel', { call_id: call.id })); article.append(button); }
      root.append(article);
    }
  }
  window.addEventListener('workbench-state', event => {
    data = event.detail; online = true;
    const author = data.authoring;
    $('model-config').textContent = author?.enabled ? `Provider: ${author.config.provider}. Model: ${author.config.model}. Local reservation: $${author.reserved_usd} / $${author.config.budget_usd} USD. Settings are selected at server startup. No credential is entered in this browser.` : 'Direct authoring is disabled. Enable OpenAI and select the model, rates and estimated budget at server startup. External proposals still work.';
    options('model-handoff', rows(data.choices?.handoffs));
    options('model-saved-preview', rows(author?.previews).map(row => ({ id: row.id, label: `${row.handoff_label} · $${row.estimate_usd} USD · ${row.id}` })));
    renderCalls(); controls();
  });
  window.addEventListener('workbench-offline', () => { online = false; $('model-consent').checked = false; controls(); renderCalls(); });
  $('model-handoff').addEventListener('change', () => { sequence++; clearPreview(); });
  $('model-consent').addEventListener('change', controls);
  $('model-preview').addEventListener('click', () => action('preview', { handoff_id: $('model-handoff').value }));
  $('model-submit').addEventListener('click', () => { if (!$('model-submit').disabled) action('submit', { preview_id: preview.id, digest: preview.digest, approve_transmission: true }); });
  $('model-saved-preview').addEventListener('change', async () => {
    const id = $('model-saved-preview').value, own = ++sequence; clearPreview(); if (!id) return;
    busy = true; controls();
    try { const value = await api('/api/workbench/model/previews/' + encodeURIComponent(id)); if (sequence === own) showPreview(value); }
    catch (error) { message(error.message); }
    finally { if (sequence === own) { busy = false; controls(); } }
  });
  for (const name of ['pageshow', 'popstate']) window.addEventListener(name, () => { $('model-consent').checked = false; controls(); });
})();
