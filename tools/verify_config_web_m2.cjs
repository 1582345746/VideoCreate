// Browser QA for M2 editable configuration flows. Uses only a disposable fixture.
const { chromium } = require(process.env.VC_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const origin = process.env.VC_WEB_TEST_ORIGIN || 'http://127.0.0.1:18787';
  const fixture = path.resolve(process.env.VC_WEB_FIXTURE_DIR || path.join(__dirname, '../_local/web-m1-20261113'));
  const key1 = 'm2-ui-key-20261113-a';
  const key2 = 'm2-ui-key-20261113-b';
  const host = 'm2-ui-' + Date.now() + '.example.test';
  const url = 'https://' + host + '/v1';
  const errors = [], consoleErrors = [], external = [];
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.VC_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', e => { if (e.type() === 'error') consoleErrors.push(e.text()); });
  await page.route('**/*', route => {
    if (route.request().url().startsWith(origin + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  const api = async (p, body, target = page) => target.evaluate(async ({origin, p, body}) => {
    const session = await fetch(origin + '/api/session', {headers: {'X-VC-Client': '1'}, credentials: 'include'});
    const s = await session.json();
    const r = await fetch(origin + '/api/' + p, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'include',
      headers: {'X-VC-Client': '1', ...(body === undefined ? {} : {'Content-Type': 'application/json', 'X-VC-CSRF': s.csrf_token})},
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    return {status: r.status, body: await r.json()};
  }, {origin, p, body});
  const submit = async () => {
    const response = page.waitForResponse(r => r.url() === origin + '/api/changes/commit');
    await page.getByRole('button', {name: '保存上游', exact: true}).click();
    const result = await response;
    assert.equal(result.status(), 200);
    await page.waitForTimeout(120);
  };
  try {
    await page.goto(origin);
    await page.getByRole('table', {name: '模型列表'}).waitFor();
    const before = await api('config/summary');
    assert.equal(before.status, 200);
    const baseCount = before.body.counts.upstreams;

    // URL + Key only: name defaults to the hostname and the key never returns to the page.
    await page.getByRole('button', {name: /添加上游/}).click();
    await page.getByLabel('API 地址（URL）').fill(url);
    await page.getByLabel('API 密钥（Key）').fill(key1);
    await submit();
    assert.ok((await page.locator('.provider-name').allTextContents()).some(v => v.includes(host)));
    assert.equal((await page.locator('body').textContent()).includes(key1), false);
    let summary = await api('config/summary');
    assert.equal(summary.body.counts.upstreams, baseCount + 1);
    const catalog = await api('catalog');
    const createdId = catalog.body.upstreams.find(u => u.url === url)?.id || '';
    assert.ok(createdId);
    const raw = fs.readFileSync(path.join(fixture, 'config.json'), 'utf8');
    assert.equal(raw.includes(key1), false);
    const runtimeFiles = fs.existsSync(path.join(fixture, 'runtime'))
      ? fs.readdirSync(path.join(fixture, 'runtime'), {recursive: true}).map(p => path.join(fixture, 'runtime', p)) : [];
    for (const file of runtimeFiles) if (fs.existsSync(file) && fs.statSync(file).isFile()) assert.equal(fs.readFileSync(file, 'utf8').includes(key1), false);

    // Metadata edit and a same-account rotation are separate whitelisted operations.
    await page.getByRole('button', {name: '编辑资料', exact: true}).click();
    await page.getByText('名称与备注（可选）', {exact:true}).click();
    await page.getByRole('dialog').getByLabel('显示名称').fill('M2 UI 上游');
    await page.getByRole('dialog').getByLabel('备注', {exact:true}).fill('<script>metadata should stay text</script>');
    await submit();
    assert.ok((await page.locator('.provider-name').allTextContents()).some(v => v.includes('M2 UI 上游')));
    assert.equal((await page.locator('body').textContent()).includes(key1), false);
    await page.getByRole('button', {name: '更换密钥', exact: true}).click();
    await page.getByLabel('API 密钥（Key）').fill(key2);
    await page.getByLabel(/确认新密钥属于原上游/).check();
    await submit();
    assert.equal((await page.locator('body').textContent()).includes(key2), false);

    // Untouched update form closes without an unnecessary discard prompt.
    await page.getByRole('button', {name: '编辑资料', exact: true}).click();
    let promptCount = 0;
    page.once('dialog', d => { promptCount++; d.dismiss(); });
    await page.getByRole('button', {name: '取消', exact: true}).click();
    assert.equal(promptCount, 0);

    // Two sessions sharing one token: the second commit must be rejected after the first.
    const page2 = await browser.newPage();
    await page2.goto(origin);
    await page2.getByRole('table', {name: '模型列表'}).waitFor();
    const s1 = await api('config/summary');
    const s2 = await api('config/summary', undefined, page2);
    const p1 = await api('changes/preview', {operation: 'upstream.update', id: createdId,
      values: {name: 'first-window', notes: ''}, expected_token: s1.body.token});
    const p2 = await api('changes/preview', {operation: 'upstream.update', id: createdId,
      values: {name: 'second-window', notes: ''}, expected_token: s2.body.token}, page2);
    assert.equal(p1.status, 200); assert.equal(p2.status, 200);
    const c1 = await api('changes/commit', {preview_token: p1.body.preview_token}, page);
    const c2 = await api('changes/commit', {preview_token: p2.body.preview_token}, page2);
    assert.equal(c1.status, 200); assert.equal(c2.status, 409);
    assert.equal(c2.body.error.code, 'configuration_conflict');

    // Malformed editable requests remain bounded and do not echo submitted secrets.
    const bad = await page.evaluate(async origin => {
      const s = await (await fetch(origin + '/api/session', {headers: {'X-VC-Client': '1'}})).json();
      const summary = await (await fetch(origin + '/api/config/summary', {headers: {'X-VC-Client': '1'}})).json();
      const r = await fetch(origin + '/api/changes/preview', {method: 'POST', credentials: 'include',
        headers: {'X-VC-Client': '1', 'Content-Type': 'application/json', 'X-VC-CSRF': s.csrf_token},
        body: JSON.stringify({operation: 'upstream.create', values: {url: 'https://bad.example', credential: 'leak-me'}, expected_token: summary.token})});
      return {status: r.status, text: await r.text()};
    }, origin);
    assert.equal(bad.status, 422); assert.equal(bad.text.includes('leak-me'), false);
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors.filter(e => !e.includes('422 (Unprocessable Entity)')), []);
    assert.deepEqual(external, []);
    fs.writeFileSync(path.join(fixture, 'browser-m2-result.json'), JSON.stringify({ok: true,
      checks: ['url-key-only save', 'hostname default name', 'metadata edit', 'same-account rotation',
        'untouched cancel', 'two-window conflict', 'credential redaction', 'no paid creates'],
      page_errors: errors, console_errors: consoleErrors, external_requests: external, paid_creates: 0}, null, 2));
    console.log('M2 browser checks passed; report saved to ' + fixture);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
