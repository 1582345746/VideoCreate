// Browser QA uses a separate synthetic configuration, never the user's config.
const { chromium } = require(process.env.VC_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const origin = process.env.VC_WEB_TEST_ORIGIN || 'http://127.0.0.1:18787';
  const out = path.resolve(process.env.VC_WEB_FIXTURE_DIR || path.join(__dirname, '../_local/web-m1-20261113'));
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.VC_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport: {width: 1520, height: 1000}});
  const errors = [], external = [], csp = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', event => { if (event.type() === 'error') csp.push(event.text()); });
  await page.route('**/*', route => {
    if (route.request().url().startsWith(origin + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  try {
    await page.goto(origin);
    await page.getByRole('table', {name: '模型列表'}).waitFor();
    assert.ok(await page.locator('tbody tr').count() > 0);
    await page.screenshot({path: path.join(out, 'desktop.png'), fullPage: true});
    await page.getByRole('button', {name: '模型目录', exact: true}).click();
    const total = await page.locator('tbody tr').count();
    await page.getByRole('combobox', {name: '媒体类型'}).selectOption('image');
    assert.ok(await page.locator('tbody tr').count() < total);
    await page.getByRole('combobox', {name: '媒体类型'}).selectOption('');
    await page.getByRole('searchbox', {name: '搜索模型'}).fill('onerror');
    assert.equal(await page.locator('tbody tr').count(), 1);
    assert.equal(await page.locator('.detail img').count(), 0);
    assert.ok((await page.locator('.note').textContent()).includes('<img'));
    await page.getByRole('button', {name: '设置', exact: true}).click();
    assert.ok((await page.locator('.path').textContent()).includes('_local'));
    await page.getByRole('button', {name: '上游管理', exact: true}).click();
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(out, 'mobile.png'), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(csp, []);
    fs.writeFileSync(path.join(out, 'browser-result.json'), JSON.stringify({ok: true,
      checks: ['real HTTP session', 'catalog navigation', 'media filtering', 'text-only notes', 'actual config path', 'narrow viewport'],
      page_errors: errors, external_requests: external, console_errors: csp, paid_creates: 0}, null, 2));
    console.log('Browser checks passed; screenshots and report saved to ' + out);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
