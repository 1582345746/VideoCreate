// Structured contract/pricing UX against the existing synthetic test fixture.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const origin=process.env.VC_WEB_TEST_ORIGIN||'http://127.0.0.1:18787';
const root=path.resolve(process.env.VC_WEB_FIXTURE_DIR || path.join(__dirname,'../_local/web-m1-20261113')),out=path.resolve(process.env.VC_WEB_CONTRACTS_OUT||path.join(root,'structured-contracts'));
const digest=()=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'config.json'))).digest('hex');
(async()=>{
  fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[],commits=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  page.on('request',r=>{if(r.url()===origin+'/api/changes/commit')commits.push(r.method())});
  await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
  async function api(route){return page.evaluate(async route=>(await fetch('/api/'+route,{headers:{'X-VC-Client':'1'}})).json(),route)}
  async function enter(locator,value){await locator.fill(value);await locator.press('Tab')}
  async function commit(model){const done=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await done).status(),200);await model.waitFor({state:'hidden'})}
  async function open(){await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();const model=page.getByRole('dialog');await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();return model}
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();await page.getByRole('button',{name:'模型目录',exact:true}).click();
    const original=(await api('catalog')).bindings.find(b=>b.kind==='video'&&b.default_eligible);assert.ok(original);
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(original.remote_model);await page.locator('tbody tr').filter({hasText:original.upstream_name}).first().click();
    let model=await open();let before=digest();const quote=model.locator('.contract-group').nth(2),budget=model.locator('.contract-group').nth(3);
    await quote.locator('summary').click();await enter(quote.getByLabel('展示报价金额',{exact:true}),'0.25');await enter(quote.getByLabel('展示报价币种',{exact:true}),'USD');await quote.getByLabel('展示报价单位',{exact:true}).selectOption('second');
    await quote.getByLabel('展示报价来源类型',{exact:true}).selectOption('documentation');await enter(quote.getByLabel('展示报价来源 URL',{exact:true}),'https://docs.example.test/price');
    await budget.locator('summary').click();await budget.getByRole('button',{name:'清除此组，恢复未知',exact:true}).click();
    await enter(budget.getByLabel('预算价格币种',{exact:true}),'CNY');await budget.getByLabel('预算价格证据状态',{exact:true}).selectOption('unverified');
    await enter(budget.getByLabel('最低计费秒数',{exact:true}),'5');await enter(budget.getByLabel('计费秒数取整步长',{exact:true}),'2');await enter(budget.getByLabel('预算价格到期时间',{exact:true}),'2027-01-01T00:00:00+00:00');
    for(const [index,resolution,price] of [[1,'720p','0.2'],[2,'1080p','0.4']]){
      await budget.getByRole('button',{name:'添加价格档位',exact:true}).click();await enter(budget.getByLabel(`档位 ${index} 分辨率`,{exact:true}),resolution);await enter(budget.getByLabel(`档位 ${index} 每秒价格`,{exact:true}),price);
    }
    const raw=JSON.parse(await model.getByLabel('预算价格、条件档位和计费规则',{exact:true}).inputValue());assert.equal(raw.tiers.length,2);assert.equal(raw.round_seconds,2);assert.equal(raw.status,'unverified');
    assert.equal(digest(),before);assert.equal(commits.length,0);await page.screenshot({path:path.join(out,'price-tiers-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'price-tiers-mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.setViewportSize({width:1440,height:1000});await commit(model);let saved=(await api('catalog')).bindings.find(b=>b.id===original.id);
    assert.equal(saved.listed_pricing.unit,'second');assert.equal(saved.listed_pricing.amount,0.25);assert.equal(saved.listed_pricing.currency,'USD');assert.equal(saved.pricing.currency,'CNY');assert.equal(saved.pricing.tiers.length,2);assert.match(saved.price_text,/待核实/);
    for(const key of ['remote_model','adapter','operations','enabled'])assert.deepEqual(saved[key],original[key]);
    model=await open();await model.locator('.contract-group').nth(3).locator('summary').click();await model.locator('.contract-group').nth(3).getByRole('button',{name:'删除此档位',exact:true}).last().click();await commit(model);
    saved=(await api('catalog')).bindings.find(b=>b.id===original.id);assert.equal(saved.pricing.tiers.length,1);
    model=await open();await model.getByLabel('展示报价与来源',{exact:true}).fill('{"unit":');
    await model.locator('.contract-group').nth(2).locator('summary').click();await model.getByText('此组 JSON 尚不完整，请先在下方 JSON 输入中修正；结构化字段暂不可编辑。',{exact:true}).waitFor();
    assert.equal(await model.locator('.contract-group').nth(2).getByLabel('展示报价金额',{exact:true}).count(),0);
    await model.getByRole('button',{name:'取消',exact:true}).click();
    model=await open();before=digest();for(const index of [2,3]){const group=model.locator('.contract-group').nth(index);await group.locator('summary').click();await group.getByRole('button',{name:'清除此组，恢复未知',exact:true}).click()}
    assert.equal(digest(),before);await commit(model);saved=(await api('catalog')).bindings.find(b=>b.id===original.id);assert.equal(saved.pricing,undefined);assert.equal(saved.listed_pricing,undefined);assert.equal(saved.price_text,'未录入');
    assert.equal(commits.length,3);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const result={ok:true,checks:['quote units/currencies/sources distinct from budget','tier add/remove and billing minimum/rounding','no child commit; three explicit parent saves','malformed JSON blocks structured edit without rewriting','clearing prices restores unknown; no zero-price inference','original binding identity/protocol/enabled preserved','390px no overflow'],parent_saves:commits.length,page_errors:errors,external_requests:external,paid_creates:0};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(e){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({alerts:await page.getByRole('alert').allTextContents(),errors},null,2));throw e}
  finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
