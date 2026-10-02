/* Synthetic browser regression for the QA readiness predicate, not geometry
 * evidence. Serves the real static app with controlled API responses and holds
 * /api/revisions until explicitly released. No sleeps or model execution.
 * The separate review_verifier_ui_qa.cjs gate still requires real saved stores.
 */
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { waitForLoadedReport } = require('./review_verifier_ui_qa.cjs');
const staticRoot = path.resolve(__dirname, '../../experimental_modeling/review_static');
const origin = 'http://verifier-readiness.invalid';
let browser;
before(async () => {
  browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}) });
});
after(async () => { if (browser) await browser.close(); });

async function syntheticPage(t, version, failed = false) {
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  let release;
  const held = new Promise(resolve => { release = resolve; });
  t.after(async () => { release(); await page.close(); });
  await page.route(`${origin}/**`, async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/project') {
      await route.fulfill({ json: { project_name: 'Synthetic readiness regression', read_only: true, read_only_reason: 'Synthetic read-only fixture', latest_revision: 'synthetic-r0', revisions: [{ id: 'synthetic-r0' }], requests: [] } });
    } else if (url.pathname === '/api/revisions/synthetic-r0') {
      await held;
      await route.fulfill(failed ? { status: 503, json: { message: 'Synthetic revision unavailable' } } : {
        json: { revision: { id: 'synthetic-r0', status: 'accepted' }, state: { machine_verified: true }, report: { schema_version: version, machine_verified: true, requirements: [] } },
      });
    } else {
      const files = { '/': ['index.html', 'text/html'], '/static/app.js': ['app.js', 'application/javascript'], '/static/style.css': ['style.css', 'text/css'] };
      const file = files[url.pathname];
      if (file) await route.fulfill({ contentType: file[1], body: fs.readFileSync(path.join(staticRoot, file[0])) });
      else await route.fulfill({ status: 404, body: 'Synthetic test route not found' });
    }
  });
  await page.goto(origin, { waitUntil: 'domcontentloaded' });
  await page.locator('#verifier-contract-notice').waitFor({ timeout: 10000 });
  assert.equal(await page.locator('#revision-description').innerText(), 'Inspection evidence loading…');
  assert.equal(await page.locator('#requirement-summary').innerText(), 'Check version unknown');
  return { page, release, errors };
}

for (const version of [1, 2]) {
  test(`synthetic delayed v${version} report cannot pass on the loading notice`, { timeout: 30000 }, async t => {
    const { page, release, errors } = await syntheticPage(t, version);
    // This is precisely the old v1 wait and notice assertion: both pass before
    // any revision response exists, reproducing the original false readiness.
    assert.ok((await page.locator('#verifier-contract-notice').innerText()).includes('This legacy version-1 report does not include version-2 surface checks.'));
    // A short deadline verifies fail-closed behavior while the response is held;
    // it is not a sleep used to assume the report has arrived.
    await assert.rejects(waitForLoadedReport(page, version, 150), { name: 'TimeoutError' });
    release();
    await waitForLoadedReport(page, version, 10000);
    assert.ok((await page.locator('#requirement-summary').innerText()).includes(version === 1 ? 'Legacy checks v1' : 'Checks v2'));
    assert.equal(await page.locator('#accept-submit').isEnabled(), false);
    // A loaded report of the wrong version must also remain a bounded failure.
    await assert.rejects(waitForLoadedReport(page, version === 1 ? 2 : 1, 150), { name: 'TimeoutError' });
    // The version pill alone must not hide a missing/wrong contract notice.
    await page.locator('#verifier-contract-notice').evaluate(node => { node.textContent = 'Synthetic incorrect scope'; });
    await assert.rejects(waitForLoadedReport(page, version, 150), { name: 'TimeoutError' });
    assert.deepEqual(errors, []);
  });
}

test('synthetic failed revision cannot pass on the legacy loading notice', { timeout: 30000 }, async t => {
  const { page, release, errors } = await syntheticPage(t, 1, true);
  release();
  await page.locator('#notice').filter({ hasText: 'Synthetic revision unavailable' }).waitFor({ timeout: 10000 });
  await assert.rejects(waitForLoadedReport(page, 1, 150), { name: 'TimeoutError' });
  assert.equal(await page.locator('#accept-submit').isEnabled(), false);
  assert.deepEqual(errors, []);
});
