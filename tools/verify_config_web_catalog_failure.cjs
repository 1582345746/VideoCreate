// Real browser against a local app whose discovery function injects safe failures.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const axe=require(process.env.VC_AXE_MODULE||'../web/provider-config/node_modules/axe-core');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const origin=process.env.VC_WEB_TEST_ORIGIN,root=process.env.VC_WEB_FIXTURE_DIR;
assert.ok(origin&&root,'Run through verify_config_web_catalog_failure.py');
const out=path.join(root,'browser');fs.mkdirSync(out);
const config=path.join(root,'config.json'),before=fs.readFileSync(config),initial=JSON.parse(before);
const digest=()=>crypto.createHash('sha256').update(fs.readFileSync(config)).digest('hex');
const initialHash=digest(),calls=()=>fs.existsSync(path.join(root,'discovery-calls.jsonl'))?
  fs.readFileSync(path.join(root,'discovery-calls.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
const secret='catalog-failure-private-fixture-key',privateError='catalog-failure-private-exception';
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[],commits=[],previews=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  page.on('request',r=>{if(r.url()===origin+'/api/changes/commit')commits.push(r.method());if(r.url()===origin+'/api/changes/preview')previews.push(r.method())});
  await page.route('**/*',route=>{if(route.request().url().startsWith(origin+'/'))return route.continue();external.push(route.request().url());return route.abort()});
  async function result(response){const text=await response.text();assert.equal(response.status(),200);assert.equal(text.includes(secret),false);assert.equal(text.includes(privateError),false);return JSON.parse(text)}
  async function action(name,route){const response=page.waitForResponse(r=>r.url()===origin+'/api/'+route);await page.getByRole('button',{name,exact:true}).click();return result(await response)}
  async function catalog(){return result(await page.request.get(origin+'/api/catalog',{headers:{'X-VC-Client':'1'}}))}
  async function selectDraft(remote){
    await page.getByRole('button',{name:'模型目录',exact:true}).click();
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(remote);
    await page.locator('tbody tr').filter({has:page.locator('.model-id').getByText(remote,{exact:true})}).click();
  }
  async function auditSetup(){
    return page.evaluate(async()=>{
      const report=await window.axe.run(document.querySelector('[aria-label="接入整理待办"]'),{
        runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
      return {violations:report.violations,incomplete:report.incomplete,rules_passed:report.passes.length};
    });
  }
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    await page.evaluate(axe.source);
    const setupChecks=[];
    for(const [remote,kind] of [['seedance2.5-V','video'],['seedance2.5-v','video'],['Unknown-image','image']]){
      await selectDraft(remote);
      const todo=page.getByRole('region',{name:'接入整理待办',exact:true});await todo.waitFor();
      const row=(await catalog()).bindings.find(b=>b.remote_model===remote);
      assert.equal(row.enabled,false);assert.equal(row.default_eligible,false);
      assert.equal(await todo.getByRole('listitem').count(),kind==='video'?5:4);
      assert.deepEqual(await todo.getByRole('listitem').allTextContents(),row.setup_gaps.map(g=>g.message));
      assert.equal(await todo.locator('input,select,textarea,button').count(),0);
      assert.match(await todo.textContent(),/保存 URL\/Key 无需填写/);
      assert.equal(digest(),initialHash);assert.equal(calls().length,0);assert.equal(commits.length,0);
      const audits=[{viewport:'1440x1000',...await auditSetup()}];
      if(kind==='image'){
        await page.setViewportSize({width:390,height:844});await todo.scrollIntoViewIfNeeded();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
        await page.screenshot({path:path.join(out,'draft-setup-mobile.png'),fullPage:true});
        audits.push({viewport:'390x844',...await auditSetup()});
        await page.setViewportSize({width:1440,height:1000});
      }
      assert.ok(audits.every(a=>a.violations.length===0&&a.incomplete.length===0));
      setupChecks.push({remote_model:remote,kind,gaps:row.setup_gaps.map(g=>g.code),read_only:true,audits});
    }
    await selectDraft('seedance2.5-V');await page.screenshot({path:path.join(out,'draft-setup-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:'检查与记录',exact:true}).click();
    const selector=page.getByRole('combobox',{name:'检查上游',exact:true});
    await selector.selectOption(process.env.VC_WEB_MATCHED_UPSTREAM);
    let packet=await action('查看本机记录','catalog/observation');
    assert.equal(packet.contracts.length,1);assert.equal(calls().length,0);
    const apply=page.getByRole('button',{name:'按此文档整理接入',exact:true});await apply.waitFor();
    const failures=[['404','not-supported'],['401','unauthorized'],['403','unauthorized'],['302','redirect-blocked'],['timeout','read-failed'],['credentials','credential-unavailable']];
    const observed=[];
    for(const [mode,status] of failures){
      fs.writeFileSync(path.join(root,'scenario.json'),JSON.stringify({mode}));
      packet=await action('检查目录（只读）','catalog/check');
      assert.equal(packet.status,status);assert.equal(packet.contracts.length,1);assert.deepEqual(packet.rows,[]);
      assert.equal(packet.observation_id,undefined);assert.equal(await apply.isVisible(),true);
      assert.equal(digest(),initialHash);assert.equal(calls().length,observed.length+1);
      assert.equal(commits.length,0);observed.push({mode,status,contract_visible:true,configuration_unchanged:true});
    }
    await page.screenshot({path:path.join(out,'failed-catalog-with-contract-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await apply.scrollIntoViewIfNeeded();assert.equal(await apply.isVisible(),true);
    await page.screenshot({path:path.join(out,'failed-catalog-with-contract-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    const committed=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await apply.click();await result(await committed);
    await page.getByText('已按明确文档登记文生视频候选；实测与质量仍未验证。',{exact:true}).waitFor();
    const saved=JSON.parse(fs.readFileSync(config,'utf8'));
    const added=Object.values(saved.bindings).filter(b=>b.remote_model==='seedance2.5-V');
    assert.equal(added.length,1);assert.equal(added[0].upstream,process.env.VC_WEB_MATCHED_UPSTREAM);
    assert.equal(added[0].adapter,'xingapi-video-v1');assert.deepEqual(added[0].operations,['text-to-video']);
    assert.equal(added[0].enabled,true);assert.deepEqual(saved.upstreams,initial.upstreams);
    assert.equal(commits.length,1);assert.equal(previews.length,1);assert.equal(calls().length,failures.length);
    const arranged=await catalog();
    assert.deepEqual(arranged.bindings.find(b=>b.id==='draft-exact').setup_gaps,[]);
    assert.equal(arranged.bindings.find(b=>b.id==='draft-case').setup_gaps.length,5);
    assert.deepEqual(saved.bindings['draft-case'],initial.bindings['draft-case']);
    assert.deepEqual(saved.bindings['draft-image'],initial.bindings['draft-image']);
    await selectDraft('seedance2.5-V');assert.equal(await page.getByRole('region',{name:'接入整理待办',exact:true}).count(),0);
    await selectDraft('seedance2.5-v');await page.getByRole('region',{name:'接入整理待办',exact:true}).waitFor();
    await page.getByRole('button',{name:'检查与记录',exact:true}).click();
    // An unrecognized address still gets no recipe; failure never broadens the scope.
    await selector.selectOption(process.env.VC_WEB_UNKNOWN_UPSTREAM);
    fs.writeFileSync(path.join(root,'scenario.json'),JSON.stringify({mode:'404'}));
    packet=await action('检查目录（只读）','catalog/check');assert.deepEqual(packet.contracts,[]);
    assert.equal(await apply.count(),0);assert.equal(calls().length,failures.length+1);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const report={ok:true,failures:observed,setup_checks:setupChecks,checks:['offline documents available before catalog read','six explicit discovery failures retain precise document','no observation fabricated','failed checks preserve config and create no transactions','one explicit document preview/commit after failure','precise text-only binding and unchanged upstreams','unrecognized address has no recipe','390px no horizontal overflow','errors and key sentinel remain private','video/image draft gaps are explicit, read-only and require no extra user fields','exact document clears only the matching draft; lowercase model remains unknown'],
      discovery_calls:calls().length,document_commits:commits.length,document_previews:previews.length,
      page_errors:errors,external_browser_requests:external,paid_creates:0};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw error}
  finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
