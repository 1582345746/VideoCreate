// Automated accessibility evidence uses only the runner's synthetic config.
const {chromium} = require(process.env.VC_PLAYWRIGHT_MODULE || 'playwright');
const axe = require(process.env.VC_AXE_MODULE || '../web/provider-config/node_modules/axe-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const origin = process.env.VC_WEB_TEST_ORIGIN;
  const fixture = process.env.VC_WEB_FIXTURE_DIR;
  assert.ok(origin && /^http:\/\/127\.0\.0\.1:\d+$/.test(origin) && fixture);
  assert.notEqual(new URL(origin).port, '8765');
  const output = path.join(fixture, 'accessibility');
  fs.mkdirSync(output, {recursive: true});
  const config = path.join(fixture, 'config.json');
  const before = fs.readFileSync(config);
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.VC_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], external = [], audits = [], keyboard = [], semantics = [], symbolContrast = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => {
    if (route.request().url().startsWith(origin + '/')) return route.continue();
    external.push(route.request().url()); return route.abort();
  });
  function project(items) {
    return items.map(item => ({id: item.id, impact: item.impact, tags: item.tags,
      nodes: item.nodes.map(node => ({target: node.target, failure_summary: node.failureSummary,
        review_messages: [...node.any, ...node.all, ...node.none].map(check => ({id: check.id, message: check.message}))}))}));
  }
  async function audit(name) {
    const result = await page.evaluate(async () => window.axe.run(document, {
      runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}
    }));
    audits.push({name, violations: project(result.violations),
      incomplete: project(result.incomplete), rules_passed: result.passes.length});
    // Axe cannot classify pure glyphs. Review their actual rendered colors too,
    // including decorative navigation glyphs that are absent from the AX tree.
    const review = await page.evaluate(incomplete => {
      const scope = document.querySelector('dialog[open]') || document;
      const reviewed = new Map();
      function rgb(text) {
        const parts = text.match(/^rgba?\(([^)]+)\)$/)?.[1].split(/[,\s/]+/).filter(Boolean).map(Number);
        return parts && parts.length >= 3 && parts.every(Number.isFinite) ? parts : null;
      }
      function luminance(color) {
        const linear = color.slice(0, 3).map(value => value / 255).map(value =>
          value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
        return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
      }
      const nodes = Array.from(scope.querySelectorAll('.sidebar nav button span,.star')).filter(el =>
        el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden').map(el => {
        const style = getComputedStyle(el), foreground = rgb(style.color);
        let background = null, review = null;
        for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) {
          const css = getComputedStyle(ancestor), color = rgb(css.backgroundColor);
          if (Number(css.opacity) !== 1 || css.filter !== 'none' || css.mixBlendMode !== 'normal' || css.backgroundImage !== 'none') {
            review = 'opacity/filter/blend/image needs separate rendered review'; break;
          }
          if (!background && color) {
            if (color.length === 3 || color[3] === 1) background = color;
            else if (color[3] !== 0) {review = 'translucent background needs separate rendered review'; break;}
          }
        }
        if (!foreground || foreground.length > 3 && foreground[3] !== 1 || !background) review ||= 'opaque foreground/background not established';
        const a = foreground && luminance(foreground), b = background && luminance(background);
        const ratio = !review ? (Math.max(a, b) + .05) / (Math.min(a, b) + .05) : null;
        const navigation = !!el.closest('nav[aria-label="主导航"]');
        const result = {type: navigation ? 'navigation-decoration' : 'favorite-status', text: el.textContent,
          name: navigation ? el.closest('button').getAttribute('aria-label') : el.getAttribute('aria-label'),
          foreground: style.color, background, ratio, minimum: 4.5, review_required: review,
          passed: ratio !== null && ratio >= 4.5,
          semantic: navigation ? el.getAttribute('aria-hidden') === 'true' : el.getAttribute('role') === 'img' && el.getAttribute('aria-label') === '已收藏'};
        reviewed.set(el,result);return result;
      });
      const axeIncomplete = incomplete.map(item => {
        let matches;
        try {matches = item.target.length === 1 ? document.querySelectorAll(item.target[0]) : [];} catch {matches = [];}
        const symbol = matches.length === 1 ? reviewed.get(matches[0]) : null;
        return {...item, covered: item.rule === 'color-contrast' && !!symbol?.passed,
          ratio: symbol?.ratio ?? null, reviewed_type: symbol?.type ?? null};
      });
      return {nodes, axe_incomplete: axeIncomplete};
    }, result.incomplete.flatMap(group => group.nodes.map(node => ({rule: group.id, target: node.target}))));
    const symbols = review.nodes;
    symbolContrast.push({audit: name, ...review});
    for (const symbol of symbols) semantics.push({audit: name, name: symbol.name, type: symbol.type, passed: symbol.semantic});
    const stars = symbols.filter(item => item.type === 'favorite-status');
    if (stars.length) semantics.push({audit: name, type: 'favorite-accessible-image-count',
      passed: await page.getByRole('img', {name: '已收藏', exact: true}).count() === stars.length});
  }
  async function navigate(name) {
    await page.getByRole('button', {name, exact: true}).click();
    await page.getByRole('heading', {level: 1}).waitFor();
    const current = page.getByRole('navigation', {name: '主导航'}).locator('[aria-current="page"]');
    semantics.push({type: 'current-page', name, passed: await current.count() === 1 && await current.getAttribute('aria-label') === name});
  }
  async function tabWithin(dialog, backward = false) {
    await page.keyboard.press(backward ? 'Shift+Tab' : 'Tab');
    return dialog.evaluate((el, reverse) => {
      const controls = Array.from(el.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]'))
        .filter(node => node.tabIndex >= 0 && !node.matches(':disabled') && !node.closest('[inert]') &&
          node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden');
      return document.activeElement === controls[reverse ? controls.length - 1 : 0];
    }, backward);
  }
  async function expandOptionalMetadata(dialog) {
    const summary = dialog.getByText('名称与备注（可选）', {exact: true});
    if (!await summary.evaluate(el => el.parentElement.open)) await summary.click();
    await dialog.getByLabel('备注', {exact: true}).waitFor();
  }
  try {
    await page.goto(origin);
    await page.getByRole('table', {name: '模型列表'}).waitFor();
    // DevTools evaluation injects the audit without weakening the served CSP.
    await page.evaluate(axe.source);
    const names = ['上游管理', '模型目录', '默认选择', '检查与记录', '设置'];
    for (const name of names) {
      await navigate(name);
      await audit('desktop-' + name);
    }
    await navigate('模型目录');
    const favorite = page.locator('tbody tr').filter({has: page.locator('.star')}).first();
    await favorite.hover(); await audit('desktop-favorite-hover');
    await favorite.focus(); await page.keyboard.press('Enter');
    await audit('desktop-favorite-selected');
    await page.getByRole('navigation', {name: '主导航'}).getByRole('button', {name: '上游管理', exact: true}).hover();
    await audit('desktop-navigation-hover');
    await page.screenshot({path: path.join(output, 'catalog-desktop.png')});
    await page.getByText('按任务条件筛选与比较（可选）', {exact: true}).click();
    await audit('desktop-task-conditions');
    await page.getByText('按任务条件筛选与比较（可选）', {exact: true}).click();
    const row = page.locator('tbody tr').nth(1);
    await row.focus(); await page.keyboard.press('Enter');
    assert.ok(await row.evaluate(el => el.classList.contains('selected')));
    keyboard.push('model row selected using Enter');
    const editor = page.getByRole('button', {name: '编辑资料与价格', exact: true});
    await editor.focus(); await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog');
    await dialog.waitFor();
    await audit('model-dialog-basic');
    const last = dialog.getByRole('button', {name: '保存模型资料', exact: true});
    await last.focus();
    keyboard.push({name: 'model-dialog-forward-boundary', inside: await tabWithin(dialog)});
    await dialog.getByLabel('显示名称', {exact: true}).focus();
    keyboard.push({name: 'model-dialog-backward-boundary', inside: await tabWithin(dialog, true)});
    await dialog.getByText('按明确文档维护协议、参数与报价（可选）', {exact: true}).click();
    await audit('model-dialog-advanced');
    await dialog.locator('.contract-group > summary').evaluateAll(nodes => {
      for (const summary of nodes) summary.parentElement.open = true;
    });
    await audit('model-dialog-all-contract-groups');
    await last.focus();
    keyboard.push({name: 'model-dialog-expanded-forward-boundary', inside: await tabWithin(dialog)});
    await page.screenshot({path: path.join(output, 'advanced-desktop.png')});
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.ok(await editor.evaluate(el => el === document.activeElement));
    keyboard.push('model dialog Escape returns to opener');
    const add = page.getByRole('button', {name: '＋ 添加上游', exact: true});
    await add.focus(); await page.keyboard.press('Enter');
    await dialog.waitFor(); await audit('upstream-dialog-basic');
    await dialog.getByRole('button', {name: '保存上游', exact: true}).focus();
    keyboard.push({name: 'upstream-dialog-forward-boundary', inside: await tabWithin(dialog)});
    await dialog.getByLabel('API 地址（URL）', {exact: true}).focus();
    keyboard.push({name: 'upstream-dialog-backward-boundary', inside: await tabWithin(dialog, true)});
    await expandOptionalMetadata(dialog);
    await audit('upstream-dialog-expanded');
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});
    assert.ok(await add.evaluate(el => el === document.activeElement));
    keyboard.push('upstream dialog Escape returns to opener');
    await page.setViewportSize({width: 390, height: 844});
    for (const name of names) {
      await navigate(name); await audit('mobile-' + name);
      if (name === '模型目录') await page.screenshot({path: path.join(output, 'catalog-mobile.png'), fullPage: true});
    }
    await navigate('模型目录');
    await page.getByRole('button', {name: '编辑资料与价格', exact: true}).click();
    await dialog.waitFor();
    const advanced = dialog.getByText('按明确文档维护协议、参数与报价（可选）', {exact: true});
    if (!await advanced.evaluate(el => el.parentElement.open)) await advanced.click();
    await audit('mobile-model-dialog-advanced');
    await page.keyboard.press('Escape'); await dialog.waitFor({state: 'hidden'});
    await navigate('上游管理');
    await page.getByRole('button', {name: '＋ 添加上游', exact: true}).click();
    await dialog.waitFor();
    await expandOptionalMetadata(dialog);
    await audit('mobile-upstream-dialog');
    await page.screenshot({path: path.join(output, 'upstream-mobile.png')});
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});
    assert.deepEqual(fs.readFileSync(config), before);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    const violations = audits.reduce((n, item) => n + item.violations.length, 0);
    const focusFailures = keyboard.filter(item => typeof item === 'object' && !item.inside);
    const semanticFailures = semantics.filter(item => !item.passed);
    const contrastFailures = symbolContrast.flatMap(item => item.nodes).filter(item => !item.passed);
    const uncovered = symbolContrast.flatMap(item => item.axe_incomplete).filter(item => !item.covered);
    const report = {ok: violations === 0 && focusFailures.length === 0 && semanticFailures.length === 0 && contrastFailures.length === 0 && uncovered.length === 0, axe_version: axe.version,
      scope: 'WCAG 2 A/AA, 2.1 A/AA and 2.2 AA tags; five pages, dialogs and keyboard boundaries',
      automated_only: true, human_screen_reader: 'not-performed', audits, keyboard,
      violation_groups: violations, focus_boundary_failures: focusFailures.length,
      semantics, semantic_failures: semanticFailures.length, symbol_contrast: symbolContrast,
      symbol_contrast_failures: contrastFailures.length,
      uncovered_incomplete_nodes: uncovered.length,
      symbol_contrast_scope: 'Visible navigation glyphs and saved-favorite status; opaque CSS colors only, stricter 4.5 ratio; opacity/filter/blend/background image or transparency stays unresolved',
      incomplete_checks: 'Raw axe incomplete retained; exact-target opaque symbol-color checks supplement them. Other targets or rendering conditions remain unresolved; no complete WCAG or human screen-reader certification',
      page_errors: errors, external_requests: external, config_unchanged: true, paid_creates: 0};
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ok: report.ok, audits: audits.length, violations,
      focus_boundary_failures: focusFailures.length, semantic_failures: semanticFailures.length,
      symbol_contrast_failures: contrastFailures.length, uncovered_incomplete_nodes: uncovered.length, output}));
    if (!report.ok) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
