/* Read-only browser checks against versioned, already generated evidence. */
'use strict';
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const output = process.env.MODELING_REVIEW_QA_OUTPUT || '/tmp/verifier-review-ui';
fs.mkdirSync(output, { recursive: true });
let server, browser;
async function stopServer() {
  if (!server || server.exitCode !== null) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => server.kill('SIGKILL'), 10000);
    server.once('exit', () => { clearTimeout(timer); resolve(); }); server.kill('SIGTERM');
  });
}
async function inspect(version, store) {
  assert.ok(store, `Set MODELING_V${version}_QA_STORE`);
  server = spawn(process.env.PYTHON || 'python3', ['-m', 'experimental_modeling.review_server', '--store', store, '--read-only'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const origin = await new Promise((resolve, reject) => {
    let data = ''; const timer = setTimeout(() => reject(new Error('Review startup timeout')), 20000);
    server.stdout.on('data', chunk => { data += chunk; const match = data.match(/Local model review: (http:\/\/127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.on('error', reject); server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin); await page.locator('#verifier-contract-notice').waitFor();
  const phrase = version === 1 ? 'This legacy version-1 report does not include version-2 surface checks.' : 'Version 2 checks indexed translation and surface data.';
  assert.ok((await page.locator('#verifier-contract-notice').innerText()).includes(phrase));
  assert.ok((await page.locator('#requirement-summary').innerText()).includes(version === 1 ? 'Legacy checks v1' : 'Checks v2'));
  assert.equal(await page.locator('#accept-submit').isEnabled(), false);
  await page.screenshot({ path: path.join(output, `verifier-v${version}-desktop.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(output, `verifier-v${version}-mobile.png`), fullPage: true });
  assert.deepEqual(errors, []);
  await page.close(); await stopServer();
}
(async () => {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
  await inspect(1, process.env.MODELING_V1_QA_STORE);
  await inspect(2, process.env.MODELING_V2_QA_STORE);
  fs.writeFileSync(path.join(output, 'verifier-version-ui-summary.json'), JSON.stringify({ status: 'passed', checks: ['v1 scope unchanged', 'v2 indexed scope visible', 'read-only acceptance disabled', 'desktop and mobile layout'] }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close(); await stopServer();
});
