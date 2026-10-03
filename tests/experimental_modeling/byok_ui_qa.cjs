/* Offline HTTP-provider fixture through the production adapter and browser.
 * Default mode additionally runs the returned proposal through the real pinned
 * Docker bridge and independent Blender verifier. Explicit fixture-only mode
 * stops at inspection; it never reports synthetic geometry success. */
'use strict';
const { chromium } = require('playwright');
const { waitForLoadedReport } = require('./review_verifier_ui_qa.cjs');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '../..');
const example = path.join(root, 'experimental_modeling/examples/external_lamp');
const output = path.resolve(process.env.MODELING_BYOK_QA_OUTPUT || path.join(os.tmpdir(), 'modeling-byok-ui'));
const fixtureOnly = process.env.MODELING_BYOK_QA_FIXTURE_ONLY === '1';
const image = process.env.MODELING_SANDBOX_IMAGE;
const docker = process.env.MODELING_BYOK_QA_DOCKER;
const socket = process.env.MODELING_BYOK_QA_SOCKET || '/run/docker.sock';
if (!fixtureOnly) {
  assert.match(image || '', /^sha256:[a-f0-9]{64}$/, 'Select an immutable existing local image.');
  assert(docker && path.isAbsolute(docker), 'Select an absolute trusted Docker executable.');
}
assert(!fs.existsSync(output), 'Use a new MODELING_BYOK_QA_OUTPUT directory; evidence is never overwritten.');
fs.mkdirSync(output, { recursive: true });
const python = execFileSync(process.env.PYTHON || 'python3', ['-c', 'import os,sys; print(os.path.realpath(sys.executable))'], { encoding: 'utf8' }).trim();
const summary = { status: 'running', provider: 'offline HTTP fixture through production OpenAI adapter',
  execution: fixtureOnly ? 'not run: explicit fixture-only mode' : 'real pinned Docker required',
  checks: [], screenshots: [] };
const save = () => fs.writeFileSync(path.join(output, 'byok-ui-summary.json'), JSON.stringify(summary, null, 2) + '\n');
save();
let server, browser, page, origin;
const errors = [], mutations = [], externalRequests = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const transportState = () => JSON.parse(fs.readFileSync(path.join(output, 'fixture-transport.json'), 'utf8'));
const transportCalls = () => transportState().calls;
async function state() {
  const response = await page.request.get(origin + '/api/workbench');
  assert.equal(response.status(), 200, await response.text());
  return response.json();
}
async function refresh() {
  await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
  const response = page.waitForResponse(response => response.url() === origin + '/api/workbench' && response.request().method() === 'GET');
  await page.locator('#refresh').click();
  assert.equal((await response).status(), 200);
  await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
}
async function post(route, payload) {
  const current = await state();
  return page.request.post(origin + route, { headers: { Origin: origin, 'Content-Type': 'application/json' },
    data: { csrf_token: current.csrf_token, ...payload } });
}
async function prepare(brief) {
  await page.locator('#brief').fill(brief);
  const response = page.waitForResponse(response => response.url().endsWith('/api/workbench/prepare') && response.request().method() === 'POST');
  await page.locator('#prepare-brief').click();
  const result = await response; assert.equal(result.status(), 200, await result.text());
  const handoff = await result.json();
  await page.waitForFunction(label => [...document.querySelector('#model-handoff').options].some(option => option.textContent === label), handoff.label);
  return handoff;
}
async function preview(handoff) {
  await page.locator('#model-handoff').selectOption({ label: handoff.label });
  const response = page.waitForResponse(response => response.url().endsWith('/api/workbench/model/preview') && response.request().method() === 'POST');
  await page.locator('#model-preview').click();
  const result = await response; assert.equal(result.status(), 200, await result.text());
  const record = await result.json();
  await page.waitForFunction(id => !document.querySelector('#model-consent').disabled && document.querySelector('#model-preview-json').textContent.includes(id), record.id);
  assert.equal(await page.locator('#model-submit').isEnabled(), false);
  assert.equal(await page.locator('#model-consent').isChecked(), false);
  return record;
}
async function loadPreview(record) {
  await page.waitForFunction(id => [...document.querySelector('#model-saved-preview').options].some(option => option.value === id), record.id);
  await page.locator('#model-saved-preview').selectOption(record.id);
  await page.waitForFunction(id => !document.querySelector('#model-preview-record').hidden && document.querySelector('#model-preview-json').textContent.includes(id), record.id);
  assert.equal(await page.locator('#model-consent').isChecked(), false);
  assert.equal(await page.locator('#model-submit').isEnabled(), false);
}
async function waitCall(id, terminal) {
  const deadline = Date.now() + 45000;
  let call;
  while (Date.now() < deadline) {
    call = (await state()).authoring.calls.find(row => row.id === id);
    if (call && terminal.includes(call.state)) { await refresh(); return call; }
    await sleep(200);
  }
  throw new Error(`Model call did not reach ${terminal}: ${JSON.stringify(call)}`);
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  summary.screenshots.push(name);
}
async function acknowledge() {
  await page.waitForFunction(() => !document.querySelector('#ack-rules').disabled);
  assert.equal(await page.locator('#run').isEnabled(), false);
  await page.locator('#ack-rules').check();
  assert.equal(await page.locator('#run').isEnabled(), false);
  await page.locator('#ack-inputs').check();
  assert.equal(await page.locator('#run').isEnabled(), true);
}

(async () => {
  const args = ['tests/experimental_modeling/byok_fixture_server.py', '--output', output];
  if (fixtureOnly) args.push('--fixture-only');
  else args.push('--docker', fs.realpathSync(docker), '--docker-socket', socket, '--sandbox-image', image);
  server = spawn(python, args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  origin = await new Promise((resolve, reject) => {
    let data = ''; const timer = setTimeout(() => reject(new Error('BYOK fixture startup timeout')), 30000);
    server.stdout.on('data', chunk => { data += chunk; fs.appendFileSync(path.join(output, 'server.log'), chunk); const match = data.match(/Offline BYOK fixture: (http:\/\/127\.0\.0\.1:\d+)\/workbench/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.stderr.on('data', chunk => { fs.appendFileSync(path.join(output, 'server.log'), chunk); process.stderr.write(chunk); });
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`BYOK fixture exited before ready (${code})`)); });
  });
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    if (new URL(route.request().url()).origin !== origin) { externalRequests.push(route.request().url()); await route.abort(); }
    else await route.continue();
  });
  page.on('request', request => { if (request.method() === 'POST') mutations.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() }); });
  await page.goto(origin + '/workbench');
  await page.getByText('Offline BYOK browser QA', { exact: true }).waitFor();
  assert.equal(mutations.length, 0);
  assert.equal(transportCalls().length, 0);
  assert.equal((await state()).operations.length, 0);
  assert.equal(await page.locator('#model-submit').isEnabled(), false);
  summary.checks.push('Opening the workbench makes no model call and executes no source');

  const brief = '\n' + JSON.parse(fs.readFileSync(path.join(example, 'handoff/request.json'), 'utf8')).prompt + '\nPreserve this exact Unicode note: 雪.';
  const handoff = await prepare(brief);
  const firstPreview = await preview(handoff);
  const outboundContext = JSON.parse(firstPreview.outbound.input[0].content[0].text);
  assert.equal(outboundContext.request.prompt, brief);
  assert.equal(firstPreview.config.endpoint, 'https://api.openai.com/v1/responses');
  assert.equal(firstPreview.outbound.store, false);
  assert.deepEqual(firstPreview.outbound.tools, []);
  assert.deepEqual(JSON.parse(await page.locator('#model-preview-json').textContent()), firstPreview);
  assert.equal(transportCalls().length, 0, 'Preview must not invoke the injected HTTP transport');
  assert.equal(transportState().credential_reads, 0, 'Preview must not read any credential');
  await screenshot('byok-outbound-preview-desktop.png');
  await page.locator('#model-consent').check();
  assert.equal(await page.locator('#model-submit').isEnabled(), true);
  await page.locator('#model-handoff').selectOption('');
  assert.equal(await page.locator('#model-consent').isChecked(), false);
  assert.equal(await page.locator('#model-submit').isEnabled(), false);
  await loadPreview(firstPreview);
  await page.locator('#model-consent').check();
  await page.reload();
  await loadPreview(firstPreview);
  await page.locator('#model-consent').check();
  await page.locator('.topbar .review-link').click();
  await page.goBack();
  await page.waitForFunction(() => !document.querySelector('#model-saved-preview').disabled);
  assert.equal(await page.locator('#model-consent').isChecked(), false);
  assert.equal(await page.locator('#model-submit').isEnabled(), false);
  const approved = await preview(handoff);
  assert.notEqual(approved.id, firstPreview.id);
  assert.equal(transportCalls().length, 0);
  summary.checks.push('Exact outbound context, endpoint, model, token limit and estimate shown before consent', 'Consent resets on handoff changes, saved-preview selection, reload and back navigation');

  let recordedResponse;
  await page.route(origin + '/api/workbench/model/submit', async route => {
    const response = await route.fetch();
    assert.equal(response.status(), 200, await response.text());
    recordedResponse = await response.json();
    await route.abort('connectionreset');
  }, { times: 1 });
  await page.locator('#model-consent').check();
  await page.locator('#model-submit').evaluate(button => { button.click(); button.click(); });
  const completed = await waitCall(approved.id, ['completed']);
  assert.equal(recordedResponse.id, approved.id);
  assert.equal(transportCalls().length, 1);
  assert.equal(mutations.filter(row => row.path === '/api/workbench/model/submit').length, 1);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(output, 'fixture-request-01.json'), 'utf8')), approved.outbound);
  assert.deepEqual(completed.usage, { input_tokens: 1234, output_tokens: 567, cached_input_tokens: 0 });
  assert.equal(await page.locator('#model-submit').textContent(), 'Request already recorded');
  const repeated = await post('/api/workbench/model/submit', { preview_id: approved.id, digest: approved.digest, approve_transmission: true });
  assert.equal(repeated.status(), 200, await repeated.text());
  assert.equal((await repeated.json()).id, approved.id);
  await page.reload();
  await loadPreview(approved);
  assert.equal(await page.locator('#model-submit').textContent(), 'Request already recorded');
  assert.equal(transportCalls().length, 1);
  let current = await state();
  assert.equal(current.authoring.calls.length, 1);
  assert.equal(current.choices.proposals.length, 1);
  assert.equal(current.operations.length, 0);
  assert.equal(fs.existsSync(path.join(output, 'project/evidence/last_good.json')), false);
  assert.equal(fs.existsSync(path.join(output, 'project/source/builder.py')), false);
  summary.checks.push('One mocked HTTP request despite rapid double click, dropped response, explicit replay and reload', 'Generated proposal and usage recorded without source execution, verification or acceptance');

  await page.locator('#handoff').selectOption({ label: handoff.label });
  await page.locator('#proposal').selectOption({ label: completed.proposal_label });
  await page.locator('#policy').selectOption({ label: 'policy-initial.json' });
  await page.locator('#requirements').selectOption({ label: 'requirements.json' });
  const inspected = page.waitForResponse(response => response.url().endsWith('/api/workbench/inspect') && response.request().method() === 'POST');
  await page.locator('#inspect-submit').click();
  const inspectedResponse = await inspected; assert.equal(inspectedResponse.status(), 200, await inspectedResponse.text());
  const inspection = await inspectedResponse.json();
  await page.waitForFunction(id => document.querySelector('#inspection-id').textContent === id && !document.querySelector('#ack-rules').disabled, inspection.id);
  assert.equal(inspection.inputs.request.prompt, brief);
  for (const source of inspection.inputs.source) {
    const expected = fs.readFileSync(path.join(example, 'proposal/source', source.name));
    assert.equal(source.text, expected.toString('utf8'));
    assert.equal(source.sha256, crypto.createHash('sha256').update(expected).digest('hex'));
    assert.equal(source.bytes, expected.length);
  }
  assert.deepEqual(inspection.inputs.parameters, JSON.parse(fs.readFileSync(path.join(example, 'proposal/params.json'), 'utf8')));
  assert.deepEqual(JSON.parse(await page.locator('#inputs-json').textContent()), inspection.inputs);
  await acknowledge();
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#ack-rules').disabled);
  assert.equal(await page.locator('#ack-rules').isChecked(), false);
  assert.equal(await page.locator('#ack-inputs').isChecked(), false);
  assert.equal(await page.locator('#run').isEnabled(), false);
  summary.checks.push('Generated proposal enters unchanged complete source/hash/params inspection with independently selected rules', 'Separate execution acknowledgments are required and reset on reload');

  for (const scenario of ['refusal', 'invalid', 'cancel']) {
    const otherHandoff = await prepare(`[fixture:${scenario}] Exercise only the offline ${scenario} response.`);
    const otherPreview = await preview(otherHandoff);
    await page.locator('#model-consent').check();
    await page.locator('#model-submit').click();
    if (scenario === 'cancel') {
      await page.getByRole('button', { name: 'Cancel model request', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Cancel model request', exact: true }).click();
    }
    const failed = await waitCall(otherPreview.id, [scenario === 'cancel' ? 'uncertain' : 'failed']);
    assert.equal(failed.proposal_label, null);
    assert.equal(failed.can_cancel, false);
    assert.equal(failed.reserved_usd, otherPreview.estimate_usd);
    current = await state();
    assert.equal(current.choices.proposals.length, 1);
    assert.equal(current.operations.length, 0);
    assert.equal(fs.existsSync(path.join(output, 'escape.py')), false);
    const before = transportCalls().length;
    const replay = await post('/api/workbench/model/submit', { preview_id: otherPreview.id, digest: otherPreview.digest, approve_transmission: true });
    assert.equal(replay.status(), 200, await replay.text());
    assert.equal((await replay.json()).state, failed.state);
    assert.equal(transportCalls().length, before);
  }
  const blockedPreview = await preview(handoff);
  await page.locator('#model-consent').check();
  await page.locator('#model-submit').click();
  await page.getByText(/A model call is active or uncertain/).waitFor();
  assert.equal(await page.locator('#model-consent').isChecked(), false);
  assert.deepEqual(transportCalls().map(row => row.case), ['success', 'refusal', 'invalid', 'cancel']);
  assert.equal((await state()).authoring.calls.length, 4);
  summary.checks.push('Provider refusal, invalid traversal proposal and in-flight cancellation publish no proposal or execution', 'Failure/cancellation reservations retained; uncertain cancellation blocks new model calls and never retries');
  await screenshot('byok-failure-records-desktop.png');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'Mobile page must not overflow horizontally');
  await screenshot('byok-records-mobile.png');
  await page.setViewportSize({ width: 1440, height: 1000 });
  summary.checks.push('Desktop and 390px mobile layout with complete outbound payload and call records');

  if (fixtureOnly) {
    const forbidden = await post('/api/workbench/run', { inspection_id: inspection.id });
    assert.equal(forbidden.status(), 409);
    assert.match((await forbidden.json()).error, /Fixture-only QA cannot execute/);
    assert.equal((await state()).operations.length, 0);
    assert.equal(fs.existsSync(path.join(output, 'project/evidence/last_good.json')), false);
    summary.checks.push('Fixture-only server rejects execution; no Blender evidence is synthesized');
  } else {
    await page.locator('#saved-inspection').selectOption(inspection.id);
    await page.waitForFunction(id => document.querySelector('#inspection-id').textContent === id && !document.querySelector('#ack-rules').disabled, inspection.id);
    await acknowledge();
    await screenshot('byok-generated-inspection-desktop.png');
    await page.locator('#run').click();
    await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
    assert.equal(await page.locator('#run').isEnabled(), false);
    const deadline = Date.now() + 15 * 60 * 1000;
    let operation;
    while (Date.now() < deadline) {
      operation = (await state()).operations.find(row => row.id === inspection.id);
      if (operation && ['finished', 'failed', 'failed_before_execution', 'interrupted'].includes(operation.state)) break;
      await sleep(2500);
    }
    assert.equal(operation?.state, 'finished', JSON.stringify(operation));
    assert.equal(operation.result?.report?.machine_verified, true, JSON.stringify(operation));
    assert.equal(operation.result?.revision?.machine_verified, true);
    assert.equal(operation.result?.state?.human_accepted, false);
    assert.equal(operation.result?.revision?.execution_mode, 'docker-isolated');
    assert.equal((await state()).operations.length, 1);
    fs.writeFileSync(path.join(output, 'byok-verified-operation.json'), JSON.stringify(operation, null, 2) + '\n');
    await refresh();
    await page.getByText('Verified', { exact: true }).waitFor();
    await screenshot('byok-verified-result-desktop.png');
    await page.locator('.topbar .review-link').click();
    await page.locator('#revision-title').filter({ hasText: `Revision ${inspection.revision}` }).waitFor();
    await waitForLoadedReport(page, operation.result.report.schema_version);
    assert.equal(await page.locator('#accepted-status').textContent(), 'No human decision recorded');
    assert.equal(await page.locator('#accept-submit').isEnabled(), true);
    await screenshot('byok-existing-review-comparison.png');
    Object.assign(summary, { execution: 'real pinned Docker and independent Blender verification passed',
      verified_revision: inspection.revision, machine_verified: true, human_accepted: false });
    summary.checks.push('Mocked provider proposal passes real isolated Blender and independent verifier after explicit Run', 'Existing review opens verified candidate and leaves human acceptance separate');
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(externalRequests, []);
  assert.equal(transportCalls().length, 4);
  assert.equal(transportState().credential_reads, 4);
  assert(!fs.readFileSync(path.join(output, 'server.log'), 'utf8').includes('offline-fixture-credential-not-a-real-key'));
  Object.assign(summary, { status: 'passed', fixture_only: fixtureOnly, provider_calls: transportCalls().length,
    proposal_count: 1, model_calls: 4, inspection_digest: inspection.inspection_digest });
  save(); console.log(JSON.stringify(summary, null, 2));
})().catch(async error => {
  Object.assign(summary, { status: 'failed', error: String(error.stack || error) });
  if (page && !page.isClosed()) {
    try { await screenshot('byok-failure.png'); } catch (captureError) { summary.capture_error = captureError.message; }
  }
  save(); console.error(error); process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null && server.signalCode === null) {
    // Let the server cancel its own live model request and owned bridge. Never
    // signal a persisted PID or remove its durable operation/recovery records.
    await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
  }
});
