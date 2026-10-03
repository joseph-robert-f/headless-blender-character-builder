/* Real isolated workbench/browser integration. No model provider or synthetic
 * geometry success. The external-lamp fixture runs through the pinned Docker
 * bridge. One response is deliberately dropped after the actual run POST to
 * test reconciliation of the real, durable operation. */
'use strict';
const { chromium } = require('playwright');
const { waitForLoadedReport } = require('./review_verifier_ui_qa.cjs');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '../..');
const example = path.join(root, 'experimental_modeling/examples/external_lamp');
const output = path.resolve(process.env.MODELING_WORKBENCH_QA_OUTPUT || path.join(os.tmpdir(), 'modeling-workbench-ui'));
const image = process.env.MODELING_SANDBOX_IMAGE;
const docker = process.env.MODELING_WORKBENCH_QA_DOCKER;
const socket = process.env.MODELING_WORKBENCH_QA_SOCKET || '/run/docker.sock';
if (!image || !/^sha256:[a-f0-9]{64}$/.test(image)) throw new Error('MODELING_SANDBOX_IMAGE must identify an existing immutable local image.');
if (!docker || !path.isAbsolute(docker)) throw new Error('MODELING_WORKBENCH_QA_DOCKER must be an absolute trusted Docker executable.');
if (fs.existsSync(output)) throw new Error('Use a new MODELING_WORKBENCH_QA_OUTPUT directory; existing evidence is never overwritten.');
fs.mkdirSync(output, { recursive: true });
const python = execFileSync(process.env.PYTHON || 'python3', ['-c', 'import os,sys; print(os.path.realpath(sys.executable))'], { encoding: 'utf8' }).trim();
assert(path.isAbsolute(python));
const project = path.join(output, 'project'), handoffs = path.join(output, 'handoffs'), proposals = path.join(output, 'proposals'), rules = path.join(output, 'rules');
for (const directory of [handoffs, proposals, rules]) fs.mkdirSync(directory);
fs.cpSync(path.join(example, 'proposal'), path.join(proposals, 'lamp'), { recursive: true });
for (const name of ['policy-initial.json', 'requirements.json']) fs.copyFileSync(path.join(example, name), path.join(rules, name));
execFileSync(python, ['-c', 'import sys; from pathlib import Path; from experimental_modeling.project import initialize; initialize(Path(sys.argv[1]), "External author workbench QA")', project], { cwd: root, stdio: 'inherit' });

const checks = [], summary = { status: 'running', scope: 'Real external-author lamp source through local Linux Docker; no built-in model call', checks };
const saveSummary = () => fs.writeFileSync(path.join(output, 'workbench-ui-summary.json'), JSON.stringify(summary, null, 2));
saveSummary();
let server, browser, page;
const errors = [], mutations = [];
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function getJSON(origin, route) {
  const response = await page.request.get(origin + route);
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
}
async function acknowledge() {
  await page.waitForFunction(() => !document.querySelector('#ack-rules').disabled);
  assert.equal(await page.locator('#run').isEnabled(), false);
  await page.locator('#ack-rules').check();
  assert.equal(await page.locator('#run').isEnabled(), false);
  await page.locator('#ack-inputs').check();
  assert.equal(await page.locator('#run').isEnabled(), true);
}
async function inspect() {
  const response = page.waitForResponse(response => response.url().endsWith('/api/workbench/inspect') && response.request().method() === 'POST');
  await page.locator('#inspect-submit').click();
  const result = await response; assert.equal(result.status(), 200, await result.text());
  const inspection = await result.json();
  await page.waitForFunction(id => document.querySelector('#inspection-id').textContent === id && !document.querySelector('#ack-rules').disabled, inspection.id);
  return inspection;
}

(async () => {
  server = spawn(python, ['-m', 'experimental_modeling.workbench', '--project', project, '--handoff-root', handoffs, '--proposal-root', proposals, '--rules-root', rules, '--docker', fs.realpathSync(docker), '--docker-socket', socket, '--sandbox-image', image, '--python', python], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const origin = await new Promise((resolve, reject) => {
    let data = ''; const timer = setTimeout(() => reject(new Error('Workbench startup timeout')), 30000);
    server.stdout.on('data', chunk => { data += chunk; fs.appendFileSync(path.join(output, 'server.log'), chunk); const match = data.match(/External author workbench: (http:\/\/127\.0\.0\.1:\d+)\/workbench/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.stderr.on('data', chunk => { fs.appendFileSync(path.join(output, 'server.log'), chunk); process.stderr.write(chunk); });
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Workbench exited before ready (${code}).`)); });
  });
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(90000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'POST') mutations.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() }); });
  await page.goto(origin + '/workbench');
  await page.getByText('External author workbench QA', { exact: true }).waitFor();
  assert.equal(mutations.length, 0);
  assert.equal(await page.locator('#run').isEnabled(), false);
  assert.equal((await getJSON(origin, '/api/workbench')).operations.length, 0);
  checks.push('Opening the workbench does not execute anything');

  const brief = '\n' + JSON.parse(fs.readFileSync(path.join(example, 'handoff/request.json'), 'utf8')).prompt;
  await page.locator('#brief').fill(brief);
  await page.locator('#prepare-brief').click();
  await page.locator('#handoff-result[open]').waitFor();
  await page.waitForFunction(() => !document.querySelector('#handoff').disabled);
  assert.equal(mutations[0].body.brief, brief, 'The exact authorized brief must not be trimmed');
  const handoff = JSON.parse(await page.locator('#handoff-json').textContent());
  assert.equal(JSON.parse(fs.readFileSync(path.join(handoff.path, 'request.json'), 'utf8')).prompt, brief);
  await page.locator('#handoff').selectOption({ label: handoff.label });
  await page.locator('#proposal').selectOption({ label: 'lamp' });
  await page.locator('#policy').selectOption({ label: 'policy-initial.json' });
  await page.locator('#requirements').selectOption({ label: 'requirements.json' });
  assert.equal(mutations.length, 1);
  const stale = await inspect();
  assert.equal(stale.inputs.request.prompt, brief);
  for (const source of stale.inputs.source) {
    const bytes = fs.readFileSync(path.join(proposals, 'lamp/source', source.name));
    assert.equal(source.sha256, crypto.createHash('sha256').update(bytes).digest('hex'));
    assert.equal(source.bytes, bytes.length);
    assert.equal(source.text, bytes.toString('utf8'));
    assert((await page.locator('#source-records').textContent()).includes(source.sha256));
  }
  assert.deepEqual(JSON.parse(await page.locator('#inputs-json').textContent()), stale.inputs);
  assert.deepEqual(JSON.parse(await page.locator('#diffs-json').textContent()), stale.diffs);
  await page.locator('#show-diffs').click();
  assert.equal(await page.locator('#diffs-panel').isVisible(), true);
  await acknowledge();
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#ack-rules').disabled);
  assert.equal(await page.locator('#ack-rules').isChecked(), false);
  assert.equal(await page.locator('#ack-inputs').isChecked(), false);
  assert.equal(await page.locator('#run').isEnabled(), false);
  checks.push('Exact brief, full source hashes/bytes/text, full JSON and paired diffs', 'Both acknowledgments required and reset on reload');

  // A stale input consumes this inspection without launching an author child.
  const paramsPath = path.join(proposals, 'lamp/params.json'), originalParams = fs.readFileSync(paramsPath);
  const changedParams = JSON.parse(originalParams); changedParams.height_m += .001;
  fs.writeFileSync(paramsPath, JSON.stringify(changedParams));
  await acknowledge();
  await page.locator('#run').click();
  await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
  const staleOperation = await getJSON(origin, `/api/workbench/operations/${stale.id}`);
  assert.equal(staleOperation.state, 'failed_before_execution');
  assert.equal(staleOperation.can_interrupt, false);
  assert.equal(staleOperation.result, undefined);
  assert.equal(fs.existsSync(path.join(project, 'evidence/last_good.json')), false);
  assert.equal(await page.locator('#run').isEnabled(), false);
  fs.writeFileSync(path.join(output, 'stale-operation.json'), JSON.stringify(staleOperation, null, 2));
  checks.push('Changed input rejected before execution and permission remains consumed');
  fs.writeFileSync(paramsPath, originalParams);

  // A fresh explicit inspection is needed after repairing the stale proposal.
  await page.locator('#handoff').selectOption({ label: handoff.label });
  await page.locator('#proposal').selectOption({ label: 'lamp' });
  await page.locator('#policy').selectOption({ label: 'policy-initial.json' });
  await page.locator('#requirements').selectOption({ label: 'requirements.json' });
  const inspection = await inspect();
  assert.notEqual(inspection.id, stale.id);
  await page.locator('#show-diffs').click();
  await page.screenshot({ path: path.join(output, 'workbench-inspection-desktop.png'), fullPage: true });
  await acknowledge();
  let realRunResponse;
  await page.route(origin + '/api/workbench/run', async route => {
    // The request reaches the actual server exactly once; only its reply is lost.
    const response = await route.fetch();
    assert.equal(response.status(), 200, await response.text());
    realRunResponse = await response.json();
    await route.abort('connectionreset');
  }, { times: 1 });
  await page.locator('#run').click();
  await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
  assert.equal(realRunResponse.id, inspection.id);
  assert.equal(realRunResponse.revision, inspection.revision);
  assert.equal(await page.locator('#run').isEnabled(), false);
  let durable = await getJSON(origin, '/api/workbench');
  assert.equal(durable.operations.length, 2);
  const retry = await page.request.post(origin + '/api/workbench/run', { headers: { Origin: origin, 'Content-Type': 'application/json' }, data: { csrf_token: durable.csrf_token, inspection_id: inspection.id } });
  assert.equal(retry.status(), 200, await retry.text());
  const replay = await retry.json();
  assert.equal(replay.id, inspection.id); assert.equal(replay.revision, inspection.revision);
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
  assert.equal(await page.locator('#run').isEnabled(), false);
  assert.equal((await getJSON(origin, '/api/workbench')).operations.length, 2);
  checks.push('Real lost-response reconciliation, duplicate POST idempotency, and reload without another revision');

  const deadline = Date.now() + 15 * 60 * 1000;
  let operation;
  while (Date.now() < deadline) {
    operation = await getJSON(origin, `/api/workbench/operations/${inspection.id}`);
    // Child exit and durable monitor publication need not land in one polling
    // tick. Only an explicit terminal journal record ends the wait.
    if (['finished', 'failed', 'failed_before_execution', 'interrupted'].includes(operation.state)) break;
    await sleep(2500);
  }
  assert.equal(operation?.state, 'finished', JSON.stringify(operation));
  assert.equal(operation.result?.report?.machine_verified, true, JSON.stringify(operation));
  assert.equal(operation.result?.revision?.machine_verified, true);
  assert.equal(operation.result?.state?.human_accepted, false);
  assert.equal(operation.result?.revision?.execution_mode, 'docker-isolated');
  fs.writeFileSync(path.join(output, 'verified-operation.json'), JSON.stringify(operation, null, 2));
  await page.locator('#refresh').click();
  await page.getByText('Verified', { exact: true }).waitFor();
  await page.waitForFunction(revision => [...document.querySelectorAll('article.operation')].some(card => card.querySelector('h3')?.textContent === revision && card.querySelector('.status-pill')?.textContent === 'finished'), inspection.revision);
  assert.equal(await page.getByText('Accepted separately', { exact: true }).count(), 0);
  await page.screenshot({ path: path.join(output, 'workbench-result-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, 'workbench-result-mobile.png'), fullPage: true });
  checks.push('Real independently verified Docker candidate with human acceptance false', 'Desktop and mobile workbench layout');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('.review-link').click();
  await page.locator('#revision-title').filter({ hasText: `Revision ${inspection.revision}` }).waitFor();
  await waitForLoadedReport(page, operation.result.report.schema_version);
  assert.equal(await page.locator('#accepted-status').textContent(), 'No human decision recorded');
  assert.equal(await page.locator('#accept-submit').isEnabled(), true);
  await page.screenshot({ path: path.join(output, 'existing-review-comparison.png'), fullPage: true });
  // Exercise the saved-refinement handoff through the unchanged review UI.
  const refinement = 'Increase the lamp height by 30 mm and preserve the base.';
  await page.locator('#request-prompt').fill(refinement);
  await page.locator('#request-submit').click();
  await page.locator('#request-queue').getByText(refinement, { exact: true }).waitFor({ state: 'attached' });
  await page.goto(origin + '/workbench');
  await page.waitForFunction(() => document.querySelector('#saved-request').options.length > 1);
  await page.locator('#saved-request').selectOption({ index: 1 });
  await page.locator('#prepare-request').click();
  await page.locator('#handoff-result[open]').waitFor();
  const refinedHandoff = JSON.parse(await page.locator('#handoff-json').textContent());
  const request = JSON.parse(fs.readFileSync(path.join(refinedHandoff.path, 'request.json'), 'utf8'));
  assert.equal(request.prompt, refinement); assert.equal(request.reference.revision, inspection.revision);
  assert.equal((await getJSON(origin, '/api/workbench')).operations.length, 2);
  checks.push('Existing review opens recorded revision; separate acceptance stays untouched', 'Saved refinement handoff retains exact parent and does not run');

  // A deliberately slow, independently selected test proposal gives the browser
  // a deterministic opportunity to interrupt the currently owned bridge. The
  // sleep is appended after the recorded source, so docstrings/future imports
  // stay legal. Nothing is injected into the trusted supervisor or verifier.
  const slowProposal = path.join(proposals, 'lamp-interruption-fixture');
  fs.cpSync(path.join(example, 'revisions/height/proposal'), slowProposal, { recursive: true });
  const slowBuilder = path.join(slowProposal, 'source/builder.py');
  const recordedBuilder = fs.readFileSync(slowBuilder, 'utf8');
  fs.writeFileSync(slowBuilder, recordedBuilder + '\n# Integration-only interruption window; never part of the delivered model.\nimport time as _workbench_qa_time\n_workbench_qa_time.sleep(90)\n');
  fs.copyFileSync(path.join(example, 'revisions/height/policy.json'), path.join(rules, 'policy-height.json'));
  const pointerPath = path.join(project, 'evidence/last_good.json');
  const originalPointer = fs.readFileSync(pointerPath);
  await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
  await page.locator('#refresh').click();
  await page.waitForFunction(() => [...document.querySelector('#proposal').options].some(option => option.textContent === 'lamp-interruption-fixture'));
  await page.locator('#handoff').selectOption({ label: refinedHandoff.label });
  await page.locator('#proposal').selectOption({ label: 'lamp-interruption-fixture' });
  await page.locator('#policy').selectOption({ label: 'policy-height.json' });
  await page.locator('#requirements').selectOption({ label: 'requirements.json' });
  const slowInspection = await inspect();
  assert.deepEqual(slowInspection.inputs.requirements, inspection.inputs.requirements, 'The interruption fixture must retain the locked project requirements');
  assert.equal(slowInspection.inputs.request.reference.revision, inspection.revision);
  assert(slowInspection.inputs.source.find(file => file.name === 'builder.py').text.endsWith('_workbench_qa_time.sleep(90)\n'));
  await acknowledge();
  await page.locator('#run').click();
  await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
  const markerPath = path.join(project, '.launcher-build.json');
  const startupDeadline = Date.now() + 180000;
  let runningMarker;
  while (Date.now() < startupDeadline) {
    const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
    if (marker.revision === slowInspection.revision && marker.status === 'running') { runningMarker = marker; break; }
    const current = await getJSON(origin, `/api/workbench/operations/${slowInspection.id}`);
    assert(!['finished', 'failed', 'failed_before_execution', 'interrupted'].includes(current.state), `Interruption fixture ended before its running marker: ${JSON.stringify(current)}`);
    await sleep(500);
  }
  assert(runningMarker, 'The inspected revision did not reach its running launcher marker within the runtime-startup deadline');
  const owned = await getJSON(origin, `/api/workbench/operations/${slowInspection.id}`);
  assert.equal(owned.can_interrupt, true, 'Only a currently owned live child may be interrupted');
  await page.locator(`[data-interrupt="${slowInspection.id}"]`).click();
  const interruptDeadline = Date.now() + 180000;
  let interrupted;
  while (Date.now() < interruptDeadline) {
    interrupted = await getJSON(origin, `/api/workbench/operations/${slowInspection.id}`);
    if (['interrupted', 'failed'].includes(interrupted.state)) break;
    assert.notEqual(interrupted.state, 'finished', 'The deliberately slow operation finished instead of being interrupted');
    await sleep(1000);
  }
  assert(['interrupted', 'failed'].includes(interrupted?.state), JSON.stringify(interrupted));
  assert.equal(interrupted.can_interrupt, false);
  assert.notEqual(interrupted.result?.report?.machine_verified, true);
  assert.notEqual(interrupted.result?.state?.human_accepted, true);
  const recoveryBytes = fs.readFileSync(markerPath), recovery = JSON.parse(recoveryBytes);
  assert.equal(recovery.revision, slowInspection.revision);
  assert(['running', 'recovery_required'].includes(recovery.status), 'Interruption must preserve a conservative recovery marker');
  assert.deepEqual(fs.readFileSync(pointerPath), originalPointer, 'Interruption must not advance last-good');
  durable = await getJSON(origin, '/api/workbench');
  assert.equal(durable.operations.length, 3);
  const repeatedRun = await page.request.post(origin + '/api/workbench/run', { headers: { Origin: origin, 'Content-Type': 'application/json' }, data: { csrf_token: durable.csrf_token, inspection_id: slowInspection.id } });
  assert.equal(repeatedRun.status(), 200, await repeatedRun.text());
  assert.deepEqual(await repeatedRun.json(), interrupted, 'Repeating Run must return the interrupted record without replay');
  const repeatedStop = await page.request.post(origin + '/api/workbench/interrupt', { headers: { Origin: origin, 'Content-Type': 'application/json' }, data: { csrf_token: durable.csrf_token, operation_id: slowInspection.id } });
  assert.equal(repeatedStop.status(), 200, await repeatedStop.text());
  assert.deepEqual(await repeatedStop.json(), interrupted, 'A repeated interruption after exit must be a no-op');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#run').textContent === 'Run already recorded');
  assert.equal(await page.locator('#run').isEnabled(), false);
  assert.equal(await page.locator(`[data-interrupt="${slowInspection.id}"]`).count(), 0);
  assert.equal(await page.getByRole('button', { name: /recover|resume|acknowledge.*interrupt/i }).count(), 0, 'The workbench must not offer browser recovery acknowledgment');
  assert.equal(await page.getByRole('checkbox', { name: /recover|resume|acknowledge.*interrupt/i }).count(), 0);
  assert.deepEqual(fs.readFileSync(markerPath), recoveryBytes, 'Repeated requests and browser reload must retain the exact recovery marker');
  assert.deepEqual(fs.readFileSync(pointerPath), originalPointer);
  assert.equal((await getJSON(origin, '/api/workbench')).operations.length, 3);
  fs.writeFileSync(path.join(output, 'interruption-proof.json'), JSON.stringify({ operation: interrupted, running_marker: runningMarker, preserved_recovery_marker: recovery, last_good_preserved: true, repeated_run_no_replay: true, repeated_interrupt_no_op: true, browser_recovery_acknowledgment: false }, null, 2));
  await page.screenshot({ path: path.join(output, 'workbench-interrupted-desktop.png'), fullPage: true });
  checks.push('Owned child interrupted after its running launcher marker', 'Recovery marker and original last-good preserved', 'Interrupted Run replay and repeated stop are idempotent', 'Reload retains interruption and offers no browser recovery acknowledgment');
  assert.deepEqual(errors, []);
  Object.assign(summary, { status: 'passed', verified_revision: inspection.revision, inspection_digest: inspection.inspection_digest, machine_verified: true, human_accepted: false, interrupted_revision: slowInspection.revision, interrupted_state: interrupted.state, recovery_status: recovery.status, operations: 3 });
  saveSummary();
  console.log(JSON.stringify(summary, null, 2));
})().catch(error => { Object.assign(summary, { status: 'failed', error: String(error.stack || error) }); saveSummary(); console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    // Let the server interrupt only its currently owned child and retain recovery
    // evidence. Never kill a persisted PID or erase this integration journal.
    await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
  }
});
