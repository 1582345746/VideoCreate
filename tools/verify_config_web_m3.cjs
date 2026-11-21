// Integration QA against an explicitly isolated local fixture; no upstream requests.
const {chromium} = require(process.env.VC_PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
(async () => {
  const origin=process.env.VC_WEB_TEST_ORIGIN || 'http://127.0.0.1:18787';
  const out=path.resolve(process.env.VC_WEB_FIXTURE_DIR || path.join(__dirname,'../_local/web-m1-20261113'));
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  await page.route('**/*',route=>{
    if(route.request().url().startsWith(origin+'/'))return route.continue();
    external.push(route.request().url());return route.abort();
  });
  async function saved(button){const response=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await button.click();assert.equal((await response).status(),200);await page.waitForTimeout(180)}
  async function api(p){return page.evaluate(async p=>(await fetch('/api/'+p,{headers:{'X-VC-Client':'1'}})).json(),p)}
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    let packet=await api('catalog');
    const image=packet.bindings.find(b=>b.kind==='image'&&b.default_eligible),video=packet.bindings.find(b=>b.kind==='video'&&b.default_eligible);
    await page.getByRole('button',{name:'默认选择',exact:true}).click();
    await page.getByRole('combobox',{name:'图片默认接入',exact:true}).selectOption(image.id);
    await page.getByRole('combobox',{name:'视频默认接入',exact:true}).selectOption(video.id);
    await page.getByRole('combobox',{name:'图片默认策略',exact:true}).selectOption('use-default');
    await page.getByRole('combobox',{name:'视频默认策略',exact:true}).selectOption('ask');
    await saved(page.getByRole('button',{name:'保存默认选择',exact:true}));
    const defaults=await api('defaults');assert.equal(defaults.image.binding,image.id);assert.equal(defaults.video.binding,video.id);

    // Single parent save for notes, favorite and optional structured pricing.
    await page.getByRole('button',{name:'模型目录',exact:true}).click();
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(image.remote_model);
    await page.locator('tbody tr').filter({hasText:image.upstream_name}).first().click();
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
    const model=page.getByRole('dialog');
    await model.getByLabel('备注',{exact:true}).fill('离线浏览器验证 · 报价不是实付');
    await model.getByLabel('收藏此接入').check();
    await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    await model.getByLabel('展示报价与来源',{exact:true}).fill(JSON.stringify({amount:0.2,currency:'USD',unit:'image',notes:'synthetic QA quote'}));
    await saved(model.getByRole('button',{name:'保存模型资料',exact:true}));
    packet=await api('catalog');const changed=packet.bindings.find(b=>b.id===image.id);assert.equal(changed.favorite,true);assert.equal(changed.listed_pricing.amount,0.2);
    assert.equal(changed.remote_model,image.remote_model);assert.deepEqual(changed.operations,image.operations);
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
    assert.equal(await page.getByRole('dialog').locator('details').first().evaluate(el=>el.open),false);
    await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();

    // Offline compare and task assessment never choose or reorder a production menu.
    await page.getByRole('searchbox',{name:'搜索模型'}).fill('');
    await page.getByText('按任务条件筛选与比较（可选）',{exact:true}).click();
    await page.locator('.comparison-picker input').nth(0).check();await page.locator('.comparison-picker input').nth(1).check();
    await page.getByRole('button',{name:'比较所选接入',exact:true}).click();await page.locator('.comparison-grid article').first().waitFor();
    assert.equal(await page.locator('.comparison-grid article').count(),2);
    await page.getByRole('button',{name:'按任务筛选',exact:true}).click();await page.locator('.fit-results p').first().waitFor();
    await page.getByRole('button',{name:'清除任务筛选',exact:true}).click();

    // Preview the anonymous report and export a new file via an authenticated download.
    await page.getByRole('button',{name:'检查与记录',exact:true}).click();
    await page.getByRole('button',{name:'预览匿名诊断',exact:true}).click();await page.locator('.diagnostic-preview').waitFor();
    const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出此预览',exact:true}).click();
    const file=await download;const exportPath=path.join(out,'browser-anonymous-diagnostic.json');await file.saveAs(exportPath);
    const report=JSON.parse(fs.readFileSync(exportPath,'utf8'));assert.equal(report.disclosure,'anonymous');assert.equal(report.network_requests,0);

    // Force reload restores only explicit nonsecret fields, and never a submitted Key.
    await page.getByRole('button',{name:'上游管理',exact:true}).click();await page.getByRole('button',{name:/添加上游/}).click();
    await page.getByRole('dialog').getByLabel('API 地址（URL）').fill('https://draft-browser.example.test/v1');
    await page.getByRole('dialog').getByLabel('API 密钥（Key）').fill('never-persist-this-browser-draft-key');
    await page.getByText('名称与备注（可选）',{exact:true}).click();await page.getByRole('dialog').getByLabel('显示名称').fill('浏览器草稿');
    await page.getByText('非秘密输入已暂存；API 密钥不会保存到表单草稿。',{exact:true}).waitFor();
    const persisted=await page.evaluate(()=>JSON.stringify({...sessionStorage,...localStorage}));assert.equal(persisted.includes('never-persist'),false);
    await page.reload();await page.getByRole('button',{name:'恢复草稿',exact:true}).waitFor();await page.getByRole('button',{name:'恢复草稿',exact:true}).click();
    assert.equal(await page.getByRole('dialog').getByLabel('API 密钥（Key）').inputValue(),'');
    assert.equal(await page.getByRole('dialog').getByLabel('API 地址（URL）').inputValue(),'https://draft-browser.example.test/v1');
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile-edit-dialog.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.getByRole('button',{name:'取消',exact:true}).click();
    await page.setViewportSize({width:1440,height:1000});

    // Lost response after server commit: status reconciliation must not create twice.
    packet=await api('catalog');const before=packet.upstreams.length;
    await page.getByRole('button',{name:/添加上游/}).click();
    await page.getByRole('dialog').getByLabel('API 地址（URL）').fill('https://lost-response-'+Date.now()+'.example.test/v1');
    await page.getByRole('dialog').getByLabel('API 密钥（Key）').fill('synthetic-key-for-lost-response');
    await page.route('**/api/changes/commit',async route=>{await route.fetch();await route.abort('failed');},{times:1});
    await page.getByRole('button',{name:'保存上游',exact:true}).click();await page.getByRole('dialog').getByRole('alert').waitFor();
    await page.getByRole('dialog').getByRole('button',{name:'核对保存结果',exact:true}).click();
    await page.getByText('已核对：上一次配置保存成功。',{exact:true}).waitFor();
    packet=await api('catalog');assert.equal(packet.upstreams.length,before+1);
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.screenshot({path:path.join(out,'desktop-m3.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(out,'browser-m3-result.json'),JSON.stringify({ok:true,checks:['independent defaults','single model save','price source','offline comparison','task filter','anonymous download','nonsecret crash recovery','narrow modal','lost-response reconciliation'],page_errors:errors,external_requests:external,paid_creates:0},null,2));
    console.log('M3 browser checks passed; report saved to '+out);
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
