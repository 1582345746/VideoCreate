// Existing-data UI acceptance: only offline allowlisted API reads. No mutations.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const origin=process.env.VC_WEB_TEST_ORIGIN,root=process.env.VC_WEB_FIXTURE_DIR,config=process.env.VC_WEB_EXISTING_CONFIG;
assert.ok(origin&&root&&config,'Run through verify_config_web_readonly_data.py');
const out=path.join(root,'browser');fs.mkdirSync(out);
const saved=JSON.parse(fs.readFileSync(config,'utf8').replace(/^\uFEFF/,''));
const sensitive=Object.values(saved.upstreams).flatMap(u=>['api_key','env','secret_ref'].map(k=>u.auth?.[k])).filter(v=>typeof v==='string'&&v);
const allowed=new Set(['session','config/summary','catalog','defaults','backups','catalog/observation','evidence','catalog/filter','catalog/compare','diagnostics/preview']);
const forbiddenKeys=new Set(['auth','api_key','secret_ref','account_id','credential_version','raw_config']);
function safe(value){
  if(typeof value==='string')for(const secret of sensitive)assert.equal(value.includes(secret),false,'Stored credential or reference must remain private');
  else if(Array.isArray(value))value.forEach(safe);
  else if(value&&typeof value==='object')for(const [key,item] of Object.entries(value)){assert.equal(forbiddenKeys.has(key),false,'Private property in browser DTO');safe(item)}
}
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],blocked=[],external=[],requests=[];
  page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{
    const req=route.request(),url=req.url();
    if(!url.startsWith(origin+'/')){external.push(url);return route.abort()}
    if(url.startsWith(origin+'/api/')){
      const endpoint=url.slice((origin+'/api/').length);requests.push({endpoint,method:req.method()});
      if(!allowed.has(endpoint)){blocked.push(endpoint);return route.abort()}
    }
    return route.continue();
  });
  async function api(endpoint,body){
    assert.equal(allowed.has(endpoint),true);
    const result=await page.evaluate(async({endpoint,body})=>{
      const headers={'X-VC-Client':'1'};
      if(body!==undefined){const s=await(await fetch('/api/session',{headers})).json();headers['X-VC-CSRF']=s.csrf_token;headers['Content-Type']='application/json'}
      const response=await fetch('/api/'+endpoint,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
      return {status:response.status,data:await response.json()};
    },{endpoint,body});
    assert.equal(result.status,200,'Allowlisted offline read failed');safe(result.data);return result.data;
  }
  async function settled(){
    await page.waitForFunction(()=>![...document.querySelectorAll('aside.detail p')].some(n=>n.textContent==='正在读取操作记录…'));
    assert.equal(await page.getByRole('alert').count(),0);safe(await page.locator('body').innerText());
  }
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    const catalog=await api('catalog'),summary=catalog.summary;
    assert.equal(summary.status,'valid');assert.equal(summary.editable,false);assert.equal(summary.mode,'read-only');
    assert.equal(path.resolve(summary.config_path),path.resolve(config));
    const counts=Object.fromEntries(['upstreams','models','bindings','routes'].map(k=>[k,Object.keys(saved[k]).length]));
    assert.deepEqual(summary.counts,counts);assert.equal(catalog.upstreams.length,counts.upstreams);assert.equal(catalog.bindings.length,counts.bindings);
    const dtoIds=catalog.bindings.map(b=>b.id);assert.deepEqual([...dtoIds].sort(),Object.keys(saved.bindings).sort());
    assert.equal(await page.locator('[data-upstream-action]').count(),0);assert.equal(await page.locator('[data-binding-editor]').count(),0);
    let providerPages=0,details=0;
    for(let i=0;i<catalog.upstreams.length;i++){
      await page.locator('.provider-nav button').nth(i).click();await settled();
      const expected=catalog.bindings.filter(b=>b.upstream_id===catalog.upstreams[i].id);
      assert.equal(await page.locator('tbody tr').count(),expected.length);providerPages++;
      for(let j=0;j<expected.length;j++){
        await page.locator('tbody tr').nth(j).click();await settled();const detail=page.getByRole('complementary',{name:'模型详情'});
        assert.equal(await detail.locator('h2').innerText(),expected[j].name);
        assert.equal(await detail.locator('.evidence-operation').count(),expected[j].adapter==='unconfigured'?0:expected[j].operations.length);
        assert.equal(await detail.getByText('配置已变化，请刷新配置后再查看操作记录。',{exact:true}).count(),0);details++;
      }
    }
    // API evidence values and the UI use the same original file and token.
    let operationRecords=0;
    for(const binding of catalog.bindings){
      const actual=await api('evidence',{binding:binding.id});assert.equal(actual.binding,binding.id);
      assert.equal(actual.config_token,summary.token);assert.equal(actual.network_requests,0);assert.equal(actual.paid_creates,0);
      assert.deepEqual(Object.keys(actual.operations).sort(),binding.adapter==='unconfigured'?[]:[...binding.operations].sort());
      for(const stages of Object.values(actual.operations)){
        assert.deepEqual(Object.keys(stages).sort(),['catalog','contract','quality','smoke']);
        for(const stage of Object.values(stages)){assert.ok(['unverified','reported_pass','fail'].includes(stage.status));assert.ok(Number.isInteger(stage.receipt_count))}
        operationRecords++;
      }
    }
    await page.getByRole('button',{name:'模型目录',exact:true}).click();await settled();assert.equal(await page.locator('tbody tr').count(),counts.bindings);
    for(const kind of ['image','video']){
      await page.getByRole('combobox',{name:'媒体类型',exact:true}).selectOption(kind);
      assert.equal(await page.locator('tbody tr').count(),catalog.bindings.filter(b=>b.kind===kind).length);
    }
    await page.getByRole('combobox',{name:'媒体类型',exact:true}).selectOption('');
    await page.getByRole('button',{name:'默认选择',exact:true}).click();
    for(const kind of ['图片','视频']){
      assert.equal(await page.getByRole('combobox',{name:kind+'默认接入',exact:true}).isDisabled(),true);
      assert.equal(await page.getByRole('combobox',{name:kind+'默认策略',exact:true}).isDisabled(),true);
    }
    assert.equal(await page.getByRole('button',{name:'保存默认选择',exact:true}).count(),0);
    await page.getByRole('button',{name:'检查与记录',exact:true}).click();
    await page.getByRole('heading',{name:'已有明确文档',exact:true}).waitFor();
    const selector=page.getByRole('combobox',{name:'检查上游',exact:true});
    for(const upstream of catalog.upstreams){
      const response=page.waitForResponse(r=>r.url()===origin+'/api/catalog/observation');
      await selector.selectOption(upstream.id); // First value may already be selected.
      await page.getByRole('button',{name:'查看本机记录',exact:true}).click();
      const packet=await(await response).json();safe(packet);
      await page.waitForFunction(()=>![...document.querySelectorAll('button')].some(b=>b.textContent==='正在读取…'));
      assert.equal(await page.getByRole('button',{name:'保存所选禁用草稿',exact:true}).count(),0);
      assert.equal(await page.getByRole('button',{name:'按此文档整理接入',exact:true}).count(),0);
    }
    await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByText(summary.config_path,{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'恢复所选备份',exact:true}).count(),0);
    await page.screenshot({path:path.join(out,'existing-data-settings-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.getByRole('button',{name:'模型目录',exact:true}).click();await settled();
    await page.screenshot({path:path.join(out,'existing-data-catalog-mobile.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);assert.deepEqual(external,[]);
    assert.equal(requests.some(r=>r.endpoint==='catalog/check'),false);
    const report={ok:true,counts,provider_pages:providerPages,binding_details:details,evidence_bindings:catalog.bindings.length,
      operation_records:operationRecords,config_path_matches:true,config_token_matches_all_evidence:true,read_only_controls_verified:true,
      pages:['providers','catalog','defaults','checks','settings'],page_errors:errors,blocked_actions:blocked,external_browser_requests:external,
      api_request_counts:Object.fromEntries([...new Set(requests.map(r=>r.endpoint))].map(name=>[name,requests.filter(r=>r.endpoint===name).length])),
      real_upstream_requests:0,credential_resolution:0,configuration_mutations:0,paid_creates:0,human_acceptance:false};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw error}
  finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
