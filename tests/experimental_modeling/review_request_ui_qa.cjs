/* Real request-bridge evidence, copied before human review writes. */
'use strict';
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const source = process.env.MODELING_REQUEST_QA_STORE;
if (!source) throw new Error('Set MODELING_REQUEST_QA_STORE to the generated project evidence');
const output = process.env.MODELING_REVIEW_QA_OUTPUT || '/tmp/request-review-ui';
fs.mkdirSync(output, { recursive: true });
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'request-review-copy-'));
const store = path.join(temporary, 'evidence');
fs.cpSync(source, store, { recursive: true });
let server, browser;
(async () => {
  server = spawn(process.env.PYTHON || 'python3', ['-m', 'experimental_modeling.review_server', '--store', store], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  const origin = await new Promise((resolve, reject) => {
    let data = ''; const timer = setTimeout(() => reject(new Error('Review startup timeout')), 20000);
    server.stdout.on('data', chunk => { data += chunk; const match = data.match(/Local model review: (http:\/\/127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    server.on('error', reject); server.stderr.on('data', chunk => process.stderr.write(chunk));
  });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(90000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin);
  await page.locator('#revision-title').filter({ hasText: 'Revision repair' }).waitFor();
  assert.equal(await page.locator('#request-queue details').count(), 4);
  for (const item of await page.locator('#request-queue details').all()) await item.evaluate(node => { node.open = true; });
  await page.getByRole('button', { name: 'bad: checks rejected', exact: true }).click();
  await page.locator('#revision-title').filter({ hasText: 'Revision bad' }).waitFor();
  assert.equal(await page.locator('#accept-submit').isEnabled(), false);
  await page.getByRole('button', { name: 'repair: Machine accepted', exact: true }).click();
  await page.locator('#revision-title').filter({ hasText: 'Revision repair' }).waitFor();
  await page.locator('#accept-submit').click();
  await page.locator('#accepted-status').filter({ hasText: 'Human decision recorded' }).waitFor();
  await page.reload();
  await page.locator('#accepted-status').filter({ hasText: 'Human decision recorded' }).waitFor();
  for (const item of await page.locator('#request-queue details').all()) await item.evaluate(node => { node.open = true; });
  assert.equal(await page.getByRole('button', { name: 'repair: Human accepted', exact: true }).count(), 1);
  await page.screenshot({ path: path.join(output, 'request-links-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(output, 'request-links-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'request-links-summary.json'), JSON.stringify({ status: 'passed', checks: ['request result links', 'rejected acceptance disabled', 'separate human acceptance', 'reload persistence', 'mobile layout'] }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    await new Promise(resolve => { const timer = setTimeout(() => server.kill('SIGKILL'), 10000); server.once('exit', () => { clearTimeout(timer); resolve(); }); server.kill('SIGTERM'); });
  }
  fs.rmSync(temporary, { recursive: true, force: true });
});
