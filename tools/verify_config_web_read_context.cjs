// Delayed UI fixtures, never provider/model evidence. No configuration writes.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const origin=process.env.VC_WEB_TEST_ORIGIN,root=process.env.VC_WEB_FIXTURE_DIR;
assert.ok(origin&&root,'Run through verify_config_web_browser_suite.py');
const out=path.join(root,'read-context');fs.mkdirSync(out);
const config=path.join(root,'config.json'),before=fs.readFileSync(config);
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const results=[],errors=[],external=[],mutations=[],networkChecks=[];
  let page,held=[],catalog,mode='immediate',evidenceMode='immediate';
  const evidence=(bid,label,token=catalog.summary.token)=>({binding:bid,config_token:token,
    operations:{[label]:{catalog:{status:'unverified',receipt_count:0}}},paid_creates:0,network_requests:0});
  const observed=(uid,label)=>({status:'observed',rows:[{remote_model:label,importable:true}],contracts:[],upstream:uid});
  async function open(){
    held=[];mode='immediate';evidenceMode='immediate';
    page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(7000);
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',async route=>{
      const req=route.request(),url=req.url();
      if(!url.startsWith(origin+'/')){external.push(url);return route.abort()}
      if(/\/api\/(changes|drafts)\/(commit|save)|\/api\/diagnostics\/export/.test(url)){
        mutations.push(url);return route.abort();
      }
      const type=url.slice((origin+'/api/').length);
      if(type==='catalog'){
        const response=await route.fetch();catalog=await response.json();return route.fulfill({response});
      }
      if(type==='catalog/check')networkChecks.push(req.postDataJSON());
      if(['catalog/observation','catalog/check','evidence'].includes(type)){
        const body=req.postDataJSON(),id=body.upstream||body.binding;
        const reply=type==='evidence'?evidence(id,'UI-fixture-current-'+id):observed(id,'UI-fixture-current-'+id);
        if((type==='evidence'?evidenceMode:mode)==='hold'){
          let release;const gate=new Promise(r=>release=r),item={type,id,release,reply,status:200,done:null};
          item.done=gate.then(()=>route.fulfill({status:item.status,contentType:'application/json',body:JSON.stringify(item.reply)}));
          held.push(item);return item.done;
        }
        if(type==='evidence'&&evidenceMode==='mismatch')reply.config_token='different-config-token';
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(reply)});
      }
      return route.continue();
    });
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    catalog=await page.evaluate(async()=>await(await fetch('/api/catalog',{headers:{'X-VC-Client':'1'}})).json());
  }
  async function waitHeld(n){
    const end=Date.now()+2500;
    while(held.length<n&&Date.now()<end)await new Promise(r=>setTimeout(r,20));
    assert.ok(held.length>=n,`Expected ${n} independent context requests; saw ${held.length}`);
    return held[n-1];
  }
  async function release(item,label,status=200){
    if(label)item.reply=status===200?(item.type==='evidence'?evidence(item.id,label):observed(item.id,label)):{error:{message:label}};
    item.status=status;
    const done=page.waitForResponse(r=>r.url()===origin+'/api/'+item.type&&r.request().postDataJSON()[item.type==='evidence'?'binding':'upstream']===item.id);
    item.release();await item.done;await done;
    // Let the fetch continuation and Vue patch settle, independently of text assertions.
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  }
  async function check(name,run){
    try{await open();await run();results.push({name,ok:true})}
    catch(e){results.push({name,ok:false,error:e.message});await page.screenshot({path:path.join(out,'failure-'+results.length+'.png'),fullPage:true})}
    finally{for(const item of held)item.release();await Promise.allSettled(held.map(i=>i.done));await page.close()}
  }
  async function checks(){await page.getByRole('button',{name:'检查与记录',exact:true}).click();await page.locator('.observation-list').waitFor()}
  const selector=()=>page.getByRole('combobox',{name:'检查上游',exact:true});
  const busy=()=>page.getByRole('button',{name:'正在读取…',exact:true});
  async function evidenceSetup(){
    await page.getByRole('button',{name:'模型目录',exact:true}).click();
    await page.locator('.evidence-operation').waitFor();
    const rows=page.locator('tbody tr');assert.ok(await rows.count()>=2);return rows;
  }
  try{
    await check('catalog switch preserves new busy state; late success discarded',async()=>{
      await checks();const old=await selector().inputValue(),other=catalog.upstreams.find(u=>u.id!==old).id;
      mode='hold';await page.getByRole('button',{name:'查看本机记录',exact:true}).click();const a=await waitHeld(1);
      await selector().selectOption(other);const b=await waitHeld(2);
      assert.equal(b.id,other);await release(a,'UI-fixture-OLD-catalog');
      assert.equal(await page.getByText('UI-fixture-OLD-catalog',{exact:true}).count(),0);
      assert.equal(await busy().isDisabled(),true);await release(b,'UI-fixture-NEW-catalog');
      await page.getByText('UI-fixture-NEW-catalog',{exact:true}).waitFor();
      assert.equal(await page.getByRole('button',{name:'查看本机记录',exact:true}).isEnabled(),true);
    });
    await check('catalog A-B-A rejects old same-ID success and old error',async()=>{
      await checks();const old=await selector().inputValue(),other=catalog.upstreams.find(u=>u.id!==old).id;
      mode='hold';await page.getByRole('button',{name:'查看本机记录',exact:true}).click();const a=await waitHeld(1);
      await selector().selectOption(other);const b=await waitHeld(2);await selector().selectOption(old);const a2=await waitHeld(3);
      await release(a2,'UI-fixture-NEW-A');await release(a,'UI-fixture-OLD-A');await release(b,'UI-fixture-OLD-error',409);
      await page.getByText('UI-fixture-NEW-A',{exact:true}).waitFor();
      assert.equal(await page.getByText('UI-fixture-OLD-A',{exact:true}).count(),0);assert.equal(await page.getByRole('alert').count(),0);
    });
    await check('catalog navigation discards old errors',async()=>{
      await checks();mode='hold';await page.getByRole('button',{name:'查看本机记录',exact:true}).click();const a=await waitHeld(1);
      await page.getByRole('button',{name:'上游管理',exact:true}).click();await release(a,'UI-fixture-navigation-error',409);
      assert.equal(await page.getByRole('alert').count(),0);
    });
    await check('explicit check cannot replace new upstream or its import selection',async()=>{
      await checks();const old=await selector().inputValue(),other=catalog.upstreams.find(u=>u.id!==old).id;
      mode='hold';await page.getByRole('button',{name:'检查目录（只读）',exact:true}).click();const a=await waitHeld(1);
      assert.equal(a.type,'catalog/check');await selector().selectOption(other);const b=await waitHeld(2);
      assert.equal(b.type,'catalog/observation');await release(b,'UI-fixture-current-selection');
      const selection=page.getByRole('checkbox',{name:'UI-fixture-current-selection'});await selection.check();
      await release(a,'UI-fixture-OLD-network');assert.equal(await selection.isChecked(),true);
      assert.equal(await page.getByText('UI-fixture-OLD-network',{exact:true}).count(),0);
    });
    await check('refresh with same config token invalidates pending catalog read',async()=>{
      await checks();mode='hold';await page.getByRole('button',{name:'查看本机记录',exact:true}).click();
      await release(await waitHeld(1),'UI-fixture-current-error',409);await page.getByRole('alert').waitFor();
      await page.getByRole('button',{name:'查看本机记录',exact:true}).click();const pending=await waitHeld(2);
      await page.getByRole('button',{name:'重新读取',exact:true}).click();
      await page.getByRole('button',{name:'查看本机记录',exact:true}).waitFor();await release(pending,'UI-fixture-before-refresh');
      assert.equal(await page.getByText('UI-fixture-before-refresh',{exact:true}).count(),0);
      assert.equal(await page.getByRole('alert').count(),0);
    });
    await check('evidence A-B-A rejects old same-ID success',async()=>{
      const rows=await evidenceSetup();evidenceMode='hold';
      await rows.nth(1).click();const b=await waitHeld(1);await rows.first().click();const a=await waitHeld(2);await rows.nth(1).click();const b2=await waitHeld(3);
      await release(b2,'UI-fixture-NEW-evidence');await release(b,'UI-fixture-OLD-evidence');await release(a);
      assert.match(await page.locator('aside.detail').innerText(),/UI-fixture-NEW-evidence/);
      assert.doesNotMatch(await page.locator('aside.detail').innerText(),/UI-fixture-OLD-evidence/);
    });
    await check('evidence old errors cannot overwrite new binding',async()=>{
      const rows=await evidenceSetup();evidenceMode='hold';await rows.nth(1).click();const b=await waitHeld(1);
      await rows.first().click();const a=await waitHeld(2);await release(a,'UI-fixture-NEW-evidence');await release(b,'UI-fixture-evidence-error',409);
      assert.doesNotMatch(await page.locator('aside.detail').innerText(),/UI-fixture-evidence-error/);
    });
    await check('evidence unmount invalidates pending errors',async()=>{
      const rows=await evidenceSetup();evidenceMode='hold';await rows.nth(1).click();const pending=await waitHeld(1);
      await page.getByRole('button',{name:'设置',exact:true}).click();evidenceMode='immediate';
      await page.getByRole('button',{name:'模型目录',exact:true}).click();await page.locator('.evidence-operation').waitFor();
      await release(pending,'UI-fixture-unmounted-error',409);
      assert.doesNotMatch(await page.locator('aside.detail').innerText(),/UI-fixture-unmounted-error/);
    });
    await check('current evidence error is distinct from empty records',async()=>{
      const rows=await evidenceSetup();evidenceMode='hold';await rows.nth(1).click();
      await page.getByText('正在读取操作记录…',{exact:true}).waitFor();
      await release(await waitHeld(1),'UI-fixture-current-evidence-error',409);
      await page.getByText('UI-fixture-current-evidence-error',{exact:true}).waitFor();
      assert.equal(await page.getByText('暂无可读取的操作记录。',{exact:true}).count(),0);
      assert.equal(await page.getByText('正在读取操作记录…',{exact:true}).count(),0);
    });
    await check('evidence response must match displayed config fingerprint',async()=>{
      const rows=await evidenceSetup();evidenceMode='mismatch';await rows.nth(1).click();
      await page.waitForFunction(()=>document.querySelector('aside.detail')?.textContent.includes('配置已变化'));
      assert.equal(await page.locator('.evidence-operation').count(),0);
      await page.screenshot({path:path.join(out,'config-changed-desktop.png'),fullPage:true});
      await page.setViewportSize({width:390,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:path.join(out,'config-changed-mobile.png'),fullPage:true});
    });
    await check('real evidence API reports exact loaded config fingerprint',async()=>{
      // APIRequestContext bypasses the browser fixture route for this one local
      // request, using the same synthetic service and its own CSRF session.
      const session=await page.request.get(origin+'/api/session',{headers:{'X-VC-Client':'1'}});
      const s=await session.json(),binding=catalog.bindings.find(b=>b.adapter!=='unconfigured');
      const response=await page.request.post(origin+'/api/evidence',{headers:{'X-VC-Client':'1','X-VC-CSRF':s.csrf_token,'Origin':origin},data:{binding:binding.id}});
      assert.equal(response.status(),200);const actual=await response.json();
      assert.equal(actual.config_token,catalog.summary.token);assert.equal(actual.binding,binding.id);
      assert.deepEqual(Object.keys(actual.operations).sort(),[...binding.operations].sort());
      assert.equal(actual.network_requests,0);assert.equal(actual.paid_creates,0);
      assert.equal(JSON.stringify(actual).includes('UI-fixture'),false);
    });
    assert.deepEqual(fs.readFileSync(config),before);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(mutations,[]);
    assert.equal(networkChecks.length,1,'Only one explicitly clicked catalog check; fulfilled by browser fixture');
    const report={ok:results.every(r=>r.ok),cases:results,fixtures:'browser-injected UI markers only; never model evidence',
      configuration_sha256:crypto.createHash('sha256').update(before).digest('hex'),configuration_unchanged:true,
      page_errors:errors,external_requests:external,configuration_mutations:mutations,explicit_fixture_catalog_checks:networkChecks.length,automatic_catalog_checks:0,real_upstream_requests:0,paid_creates:0};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
    assert.equal(report.ok,true,'Read-context cases failed; inspect result.json');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
