/* Read-only browser checks against versioned, already generated evidence. */
'use strict';
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const output = process.env.MODELING_REVIEW_QA_OUTPUT || '/tmp/verifier-review-ui';
const reportTimeout = 90000;
let server, browser, currentPage, currentVersion;
const screenshots = [];
const completedVersions = [];
function reportContent(version) {
  assert.ok(version === 1 || version === 2, 'Expected verifier version 1 or 2');
  return {
    phrase: version === 1 ? 'This legacy version-1 report does not include version-2 surface checks.' : 'Version 2 checks indexed translation and surface data.',
    label: version === 1 ? 'Legacy checks v1' : 'Checks v2',
  };
}
async function waitForLoadedReport(page, version, timeout = reportTimeout) {
  // renderRequirements(null) already shows the legacy notice while the revision
  // request is pending. Only the matching version pill AND scope text prove the
  // expected report has rendered; neither an element nor a response alone does.
  await page.waitForFunction(({ phrase, label }) => {
    const notice = document.getElementById('verifier-contract-notice');
    const labels = document.querySelectorAll('#requirement-summary .status-pill');
    return notice?.textContent.includes(phrase) && [...labels].some(node => node.textContent === label);
  }, reportContent(version), { timeout });
}
async function stopServer() {
  if (!server || server.exitCode !== null || server.signalCode !== null) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => server.kill('SIGKILL'), 10000);
    server.once('exit', () => { clearTimeout(timer); resolve(); }); server.kill('SIGTERM');
  });
}
async function inspect(version, store) {
  currentVersion = version;
  assert.ok(store, `Set MODELING_V${version}_QA_STORE`);
  server = spawn(process.env.PYTHON || 'python3', ['-m', 'experimental_modeling.review_server', '--store', store, '--read-only'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const origin = await new Promise((resolve, reject) => {
    let data = ''; const timer = setTimeout(() => reject(new Error('Review startup timeout')), 20000);
    server.stdout.on('data', chunk => { data += chunk; const match = data.match(/Local model review: (http:\/\/127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.on('error', error => { clearTimeout(timer); reject(error); });
    server.on('exit', code => { clearTimeout(timer); reject(new Error(`Review server exited ${code}`)); });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  const page = currentPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin);
  await waitForLoadedReport(page, version);
  const { phrase, label } = reportContent(version);
  assert.ok((await page.locator('#verifier-contract-notice').innerText()).includes(phrase));
  assert.ok((await page.locator('#requirement-summary').innerText()).includes(label));
  assert.equal(await page.locator('#accept-submit').isEnabled(), false);
  const desktop = `verifier-v${version}-desktop.png`;
  await page.screenshot({ path: path.join(output, desktop), fullPage: true }); screenshots.push(desktop);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  const mobile = `verifier-v${version}-mobile.png`;
  await page.screenshot({ path: path.join(output, mobile), fullPage: true }); screenshots.push(mobile);
  assert.deepEqual(errors, []);
  completedVersions.push(version);
  await page.close(); currentPage = null; await stopServer();
}
async function run() {
  fs.mkdirSync(output, { recursive: true });
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
  await inspect(1, process.env.MODELING_V1_QA_STORE);
  await inspect(2, process.env.MODELING_V2_QA_STORE);
  fs.writeFileSync(path.join(output, 'verifier-version-ui-summary.json'), JSON.stringify({ status: 'passed', checks: ['v1 scope unchanged', 'v2 indexed scope visible', 'read-only acceptance disabled', 'desktop and mobile layout'], completed_versions: completedVersions, screenshots }, null, 2) + '\n');
}
if (require.main === module) {
  run().catch(async error => {
    let observed = null;
    if (currentPage && !currentPage.isClosed()) {
      try {
        observed = await currentPage.evaluate(() => Object.fromEntries(['revision-description', 'verifier-contract-notice', 'requirement-summary', 'notice'].map(id => [id, document.getElementById(id)?.textContent || ''])));
        const failure = `verifier-v${currentVersion}-failure.png`;
        await currentPage.screenshot({ path: path.join(output, failure), fullPage: true, timeout: 10000 }); screenshots.push(failure);
      } catch (captureError) { observed = { ...observed, capture_error: captureError.message }; }
    }
    fs.writeFileSync(path.join(output, 'verifier-version-ui-summary.json'), JSON.stringify({ status: 'failed', error: error.message, failed_version: currentVersion, completed_versions: completedVersions, observed, screenshots }, null, 2) + '\n');
    console.error(error); process.exitCode = 1;
  }).finally(async () => {
    if (browser) await browser.close(); await stopServer();
  });
}
module.exports = { waitForLoadedReport };
