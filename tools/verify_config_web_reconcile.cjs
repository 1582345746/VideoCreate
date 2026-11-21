// Real local transactions, synthetic configuration only. Lose the response
// after the server commits; never retry the write as part of reconciliation.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const origin=process.env.VC_WEB_TEST_ORIGIN,root=process.env.VC_WEB_FIXTURE_DIR;
assert.ok(origin&&root,'Run through verify_config_web_browser_suite.py');
const out=path.join(root,'reconcile');fs.mkdirSync(out);
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const cases=[],errors=[],external=[];let context,page,mode,statusMode,commits,statusReads,dialogs;
  async function api(endpoint,body){return page.evaluate(async({endpoint,body})=>{
    const headers={'X-VC-Client':'1'};
    if(body!==undefined){const s=await(await fetch('/api/session',{headers})).json();headers['X-VC-CSRF']=s.csrf_token;headers['Content-Type']='application/json'}
    const r=await fetch('/api/'+endpoint,{method:body===undefined?'GET':'POST',headers,body:JSON.stringify(body)});
    return {status:r.status,data:await r.json()};
  },{endpoint,body})}
  async function open(){
    mode='';statusMode='';commits=0;statusReads=0;dialogs=[];
    context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();page.setDefaultTimeout(4000);
    page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>{dialogs.push(d.message());return d.accept()});
    await page.route('**/*',async route=>{
      const url=route.request().url();
      if(!url.startsWith(origin+'/')){external.push(url);return route.abort()}
      if(url.endsWith('/api/catalog/check'))throw new Error('No upstream requests allowed');
      if(url.endsWith('/api/changes/commit')){
        commits++;
        if(mode==='committed'){const response=await route.fetch();assert.equal(response.status(),200);return route.abort('failed')}
        if(mode==='not-submitted')return route.abort('failed');
      }
      if(url.endsWith('/api/changes/status')){
        statusReads++;
        if(statusMode==='unknown')return route.fulfill({json:{status:'unknown',message:'合成结果未知，请保留输入并稍后核对。'}});
        if(statusMode==='error')return route.abort('failed');
      }
      return route.continue();
    });
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
  }
  async function check(name,run){
    try{await open();const detail=await run()||{};cases.push({name,ok:true,...detail})}
    catch(e){cases.push({name,ok:false,error:e.message});if(page)await page.screenshot({path:path.join(out,'failure-'+cases.length+'.png'),fullPage:true})}
    finally{if(context)await context.close()}
  }
  async function draft(kind,action){
    const response=page.waitForResponse(r=>r.url()===origin+'/api/drafts/save'&&(r.request().postDataJSON().form.kind||'upstream')===kind);
    await action();const r=await response;assert.equal(r.status(),200);return r.json();
  }
  async function upstream(){
    await page.getByRole('button',{name:/添加上游/}).click();const d=page.getByRole('dialog');
    const url='https://reconcile-'+Date.now()+'.invalid/v1';
    await d.getByLabel('API 地址（URL）').fill(url);await d.getByLabel('API 密钥（Key）').fill('NEVER-PERSIST-RECONCILE-KEY');
    await d.getByText('名称与备注（可选）',{exact:true}).click();
    const saved=await draft('upstream',()=>d.getByLabel('显示名称',{exact:true}).fill('丢失响应后的上游'));
    return {d,url,saved};
  }
  async function lose(button,value='committed'){
    mode=value;const lost=page.waitForRequest(r=>r.url()===origin+'/api/changes/commit');await button.click();await lost;
    if(await page.getByRole('dialog').count())await page.getByRole('dialog').getByRole('alert').waitFor();
    else await page.getByText('有一次保存结果尚未核对。',{exact:false}).waitFor();
  }
  async function reconcile(scope=page){const b=scope.getByRole('button',{name:'核对保存结果',exact:true});await b.click()}
  async function keyboardReconcile(d){
    await page.waitForFunction(()=>document.querySelector('dialog[open] [data-reconcile]')===document.activeElement);
    // <summary> remains keyboard reachable inside a disabled fieldset.
    const steps=[];
    for(let i=0;i<6;i++){
      await page.keyboard.press('Tab');
      const state=await d.evaluate(el=>({inside:el.contains(document.activeElement),tag:document.activeElement?.tagName,text:document.activeElement?.textContent?.slice(0,120)}));
      steps.push(state);
      if(!state.inside){
        const controls=await d.evaluate(el=>[...el.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')]
          .filter(e=>e.tabIndex>=0&&!e.matches(':disabled')&&e.getClientRects().length>0)
          .map(e=>({tag:e.tagName,text:e.textContent?.slice(0,100),closed:e.closest('details:not([open])')?.tagName,rects:[...e.getClientRects()].map(r=>({width:r.width,height:r.height}))})));
        throw new Error('Keyboard focus escaped pending modal: '+JSON.stringify({steps,controls}));
      }
      if(await d.getByRole('button',{name:'核对保存结果',exact:true}).evaluate(el=>el===document.activeElement))return steps;
    }
    throw new Error('Reconcile button unreachable by keyboard: '+JSON.stringify(steps));
  }
  async function gone(saved){assert.equal((await api('drafts/load',{draft_token:saved.draft_token})).status,404)}
  try{
    await check('committed upstream closes and selects saved identity, removes exact draft and returns focus',async()=>{
      const {d,url,saved}=await upstream();const before=(await api('catalog')).data.upstreams.length;
      await lose(d.getByRole('button',{name:'保存上游',exact:true}));
      const keyboard=await keyboardReconcile(d);
      await page.screenshot({path:path.join(out,'pending-upstream.png'),fullPage:true});
      await reconcile(d);await d.waitFor({state:'hidden'});
      assert.equal((await api('catalog')).data.upstreams.length,before+1);await gone(saved);
      assert.equal(await page.locator('.summary .mono').textContent(),url);
      await page.waitForFunction(()=>document.activeElement===document.querySelector('[data-upstream-action="create"]'));
      assert.equal(commits,1);return {commits,draft_removed:true,form_closed:true,keyboard};
    });
    await check('model modal exposes reconciliation and resumes successful cleanup',async()=>{
      await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();const d=page.getByRole('dialog');
      const saved=await draft('binding',()=>d.getByLabel('备注',{exact:true}).fill('核对成功的模型资料'));
      await lose(d.getByRole('button',{name:'保存模型资料',exact:true}));
      const keyboard=await keyboardReconcile(d);
      await page.screenshot({path:path.join(out,'pending-model.png'),fullPage:true});
      await reconcile(d);await d.waitFor({state:'hidden'});await gone(saved);
      await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
      assert.equal(await page.getByRole('dialog').getByLabel('备注',{exact:true}).inputValue(),'核对成功的模型资料');assert.equal(commits,1);
      return {commits,modal_reconcile_accessible:true,draft_removed:true,keyboard};
    });
    await check('default reconciliation resets dirty baseline and cleans its submitted draft',async()=>{
      const packet=(await api('catalog')).data;await page.getByRole('button',{name:'默认选择',exact:true}).click();
      for(const [kind,label] of [['image','图片'],['video','视频']]){
        await page.getByRole('combobox',{name:label+'默认接入',exact:true}).selectOption(packet.bindings.find(b=>b.kind===kind&&b.default_eligible)?.id||'');
      }
      const policy=page.getByRole('combobox',{name:'视频默认策略',exact:true});
      const saved=await draft('defaults',()=>policy.selectOption('use-default'));
      await lose(page.getByRole('button',{name:'保存默认选择',exact:true}));await reconcile();
      await page.getByText('图片和视频的默认策略已保存。',{exact:true}).waitFor();
      await page.waitForFunction(()=>!document.querySelector('select[aria-label="视频默认策略"]').matches(':disabled'));await gone(saved);
      assert.equal(await policy.inputValue(),'use-default');dialogs=[];await page.getByRole('button',{name:'设置',exact:true}).click();
      assert.deepEqual(dialogs,[],'Saved defaults still prompt as dirty');assert.equal(commits,1);return {commits,dirty_baseline_reset:true};
    });
    await check('restored backup reconciliation clears the submitted selection and draft',async()=>{
      await page.getByRole('button',{name:'设置',exact:true}).click();const choice=page.getByRole('combobox',{name:'配置备份',exact:true});
      await choice.locator('option').nth(1).waitFor({state:'attached'});const id=await choice.locator('option').nth(1).getAttribute('value');
      const saved=await draft('repair',()=>choice.selectOption(id));
      await lose(page.getByRole('button',{name:'恢复所选备份',exact:true}));await reconcile();
      await page.getByText('配置已恢复，原始备份与旧凭据版本继续保留。',{exact:true}).waitFor();
      await page.waitForFunction(()=>document.querySelector('select[aria-label="配置备份"]').value==='');await gone(saved);assert.equal(commits,1);
      return {commits,selection_cleared:true,draft_removed:true};
    });
    await check('not-submitted result preserves nonsecret input and draft for explicit retry',async()=>{
      const {d,url,saved}=await upstream();await lose(d.getByRole('button',{name:'保存上游',exact:true}),'not-submitted');await reconcile(d);
      await page.waitForFunction(()=>!document.querySelector('input[type="url"]').matches(':disabled'));
      assert.equal(await d.getByLabel('API 地址（URL）').inputValue(),url);assert.equal(await d.getByLabel('API 密钥（Key）').inputValue(),'');
      assert.equal((await api('drafts/load',{draft_token:saved.draft_token})).status,200);
      assert.equal((await api('catalog')).data.upstreams.some(u=>u.url===url),false);assert.equal(commits,1);
      mode='';await d.getByLabel('API 密钥（Key）').fill('synthetic-explicit-retry');await d.getByRole('button',{name:'保存上游',exact:true}).click();await d.waitFor({state:'hidden'});
      assert.equal((await api('catalog')).data.upstreams.filter(u=>u.url===url).length,1);return {explicit_retry_commits:commits};
    });
    await check('unknown and failed status keep inputs locked, reconcile accessible and write count unchanged',async()=>{
      const {d}=await upstream();await lose(d.getByRole('button',{name:'保存上游',exact:true}));
      for(const value of ['unknown','error']){
        statusMode=value;await reconcile(d);
        await page.waitForFunction(()=>[...document.querySelector('dialog[open]').querySelectorAll('button')].some(b=>b.textContent==='核对保存结果'&&!b.disabled));
        assert.ok(await d.getByLabel('显示名称',{exact:true}).isDisabled(),'Result-unknown form became editable');
        assert.ok(await d.getByRole('button',{name:'正在保存…',exact:true}).isDisabled());assert.ok(await d.getByRole('button',{name:'取消',exact:true}).isDisabled());
        assert.ok(await d.getByRole('button',{name:'核对保存结果',exact:true}).isEnabled());assert.equal(commits,1);
      }
      statusMode='';await reconcile(d);await d.waitFor({state:'hidden'});assert.equal(commits,1);return {status_reads:statusReads,commits,no_automatic_retry:true};
    });
    await check('duplicate reconcile clicks issue one status request and one completion',async()=>{
      const {d,saved}=await upstream();await lose(d.getByRole('button',{name:'保存上游',exact:true}));
      await d.getByRole('button',{name:'核对保存结果',exact:true}).evaluate(el=>{el.click();el.click()});await d.waitFor({state:'hidden'});
      assert.equal(statusReads,1);assert.equal(commits,1);await gone(saved);return {status_reads:statusReads,commits};
    });
    await check('reloading pending token preserves draft with explicit review message and no secret storage',async()=>{
      const {d,saved}=await upstream();await lose(d.getByRole('button',{name:'保存上游',exact:true}));
      const stored=await page.evaluate(()=>({...sessionStorage,...localStorage}));
      const pendingKey=Object.keys(stored).find(k=>/^vc-pending-change:[a-f0-9]{64}$/.test(k));assert.ok(pendingKey);
      assert.ok(/^[a-f0-9]{48}$/.test(stored[pendingKey]));
      assert.equal(JSON.stringify(stored).includes('NEVER-PERSIST'),false);
      await page.reload();await page.getByRole('button',{name:'恢复草稿',exact:true}).waitFor();await reconcile();
      await page.getByText(/页面重开前的非秘密草稿继续保留/).waitFor();
      assert.equal((await api('drafts/load',{draft_token:saved.draft_token})).status,200);assert.equal(commits,1);
      assert.equal(await page.evaluate(key=>sessionStorage.getItem(key),pendingKey),null);return {commits,draft_retained_after_reload:true};
    });
    await check('newer shared draft survives same-page successful reconciliation CAS cleanup',async()=>{
      const {d,saved}=await upstream();await lose(d.getByRole('button',{name:'保存上游',exact:true}));
      const loaded=(await api('drafts/load',{draft_token:saved.draft_token})).data;
      const newer=await api('drafts/save',{draft_token:saved.draft_token,expected_version:loaded.draft_version,source_token:loaded.source_token,form:{...loaded.form,name:'另一个窗口后来保存的草稿'}});
      assert.equal(newer.status,200);assert.notEqual(newer.data.draft_version,saved.draft_version);
      await reconcile(d);await d.waitFor({state:'hidden'});
      const retained=await api('drafts/load',{draft_token:saved.draft_token});assert.equal(retained.status,200);assert.equal(retained.data.form.name,'另一个窗口后来保存的草稿');assert.equal(commits,1);
      return {commits,newer_draft_retained:true};
    });
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{await browser.close()}
  const report={ok:cases.every(c=>c.ok),cases,page_errors:errors,external_requests:external,paid_creates:0,
    source:'real local preview/commit/status/draft endpoints; synthetic configuration; response loss after route.fetch or before send'};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(!report.ok)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
