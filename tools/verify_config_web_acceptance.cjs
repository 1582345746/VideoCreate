// Real HTTP/browser acceptance against the disposable fixture only.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),http=require('node:http');
const origin=process.env.VC_WEB_TEST_ORIGIN||'http://127.0.0.1:18787';
const root=path.resolve(process.env.VC_WEB_FIXTURE_DIR || path.join(__dirname,'../_local/web-m1-20261113')),config=path.join(root,'config.json');
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
(async()=>{
  const initial=hash(fs.readFileSync(config));
  const cookie=(await fetch(origin)).headers.get('set-cookie').split(';')[0];
  const session=await (await fetch(origin+'/api/session',{headers:{Cookie:cookie,'X-VC-Client':'1'}})).json();
  const valid={Cookie:cookie,'X-VC-Client':'1','Content-Type':'application/json',Origin:origin,'X-VC-CSRF':session.csrf_token};
  const routes=['changes/preview','changes/commit','changes/status','catalog/observation','catalog/check','evidence','catalog/filter','catalog/compare','diagnostics/preview','diagnostics/export','drafts/save','drafts/load','drafts/discard','drafts/list'];
  for(const route of routes){
    for(const [headers,status] of [[{},401],[{...valid,'X-VC-CSRF':'invalid'},403],[{...valid,Origin:'https://attacker.test'},403],[{...valid,Host:'attacker.test'},403],[{...valid,'Content-Type':'text/plain'},415]]){
      const response=await new Promise((resolve,reject)=>{
        const r=http.request(origin+'/api/'+route,{method:'POST',headers},response=>{
          let text='';response.on('data',c=>text+=c);response.on('end',()=>resolve({status:response.statusCode,text}));
        });r.on('error',reject);r.end('{}');
      });
      assert.equal(response.status,status,route);assert.equal(response.text.includes('credential'),false);
    }
  }
  assert.equal(hash(fs.readFileSync(config)),initial);
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
  async function api(route,body){return page.evaluate(async({route,body})=>{
    const s=await(await fetch('/api/session',{headers:{'X-VC-Client':'1'}})).json();
    const r=await fetch('/api/'+route,{method:body===undefined?'GET':'POST',headers:{'X-VC-Client':'1',...(body===undefined?{}:{'Content-Type':'application/json','X-VC-CSRF':s.csrf_token})},body:body===undefined?undefined:JSON.stringify(body)});
    return {status:r.status,data:await r.json()};
  },{route,body})}
  async function otherChange(operation,values,id){
    const summary=await api('config/summary');
    const p=await api('changes/preview',{operation,values,id,expected_token:summary.data.token});assert.equal(p.status,200);
    const c=await api('changes/commit',{preview_token:p.data.preview_token});assert.equal(c.status,200);
  }
  async function save(button){const done=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await button.click();assert.equal((await done).status(),200);await page.waitForTimeout(150)}
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    const before=(await api('config/summary')).data.counts.upstreams;
    for(let i=0;i<3;i++){
      const add=page.getByRole('button',{name:'＋ 添加上游',exact:true});await add.focus();await page.keyboard.press('Enter');
      const dialog=page.getByRole('dialog');await dialog.waitFor();
      assert.equal(await page.getByLabel('API 地址（URL）').evaluate(el=>el===document.activeElement),true);
      await page.getByLabel('API 地址（URL）').fill('https://acceptance-'+Date.now()+'-'+i+'.example.test/v1');
      await page.getByLabel('API 密钥（Key）').fill('isolated-ui-acceptance-'+i);
      await save(dialog.getByRole('button',{name:'保存上游',exact:true}));
      assert.equal(await add.evaluate(el=>el===document.activeElement),true);
    }
    assert.equal((await api('config/summary')).data.counts.upstreams,before+3);

    // Native Escape and focus return preserve the user's choice about long text.
    const add=page.getByRole('button',{name:'＋ 添加上游',exact:true});await add.click();
    await page.getByText('名称与备注（可选）',{exact:true}).click();
    const long='长中文备注与配置来源。'.repeat(300);await page.getByRole('dialog').getByLabel('备注',{exact:true}).fill(long);
    page.once('dialog',d=>d.dismiss());await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),1);
    assert.equal(await page.getByRole('dialog').getByLabel('备注',{exact:true}).inputValue(),long);
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(root,'mobile-long-notes.png'),fullPage:true});
    page.once('dialog',d=>d.accept());await page.keyboard.press('Escape');await page.setViewportSize({width:1440,height:1000});

    // A model form must reject a config changed after it was opened.
    await page.getByRole('button',{name:'模型目录',exact:true}).click();
    let catalog=(await api('catalog')).data;const binding=catalog.bindings[0];
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(binding.remote_model);
    await page.locator('tbody tr').filter({hasText:binding.upstream_name}).first().click();
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
    await page.getByRole('dialog').getByLabel('备注',{exact:true}).fill('stale browser form');
    const otherNotes='other window retained '+Date.now();await otherChange('binding.update',{notes:otherNotes},binding.id);
    const conflict=page.waitForResponse(r=>r.url()===origin+'/api/changes/preview');
    await page.getByRole('dialog').getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await conflict).status(),409);
    assert.equal((await api('catalog')).data.bindings.find(b=>b.id===binding.id).notes,otherNotes);
    page.once('dialog',d=>d.accept());await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
    await page.getByRole('button',{name:'刷新配置',exact:true}).click();

    // Restore and malformed-file repair use the real settings form.
    await page.getByRole('button',{name:'设置',exact:true}).click();
    await page.getByRole('combobox',{name:'配置备份',exact:true}).locator('option').nth(1).waitFor({state:'attached'});
    const choice=await page.getByRole('combobox',{name:'配置备份',exact:true}).locator('option').nth(1).getAttribute('value');
    await page.getByRole('combobox',{name:'配置备份',exact:true}).selectOption(choice);
    page.once('dialog',d=>d.accept());await save(page.getByRole('button',{name:'恢复所选备份',exact:true}));
    const damaged=Buffer.from('{"schema_version":4,"unparsed":"isolated-damaged-sentinel",\r\n}');fs.writeFileSync(config,damaged);
    await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();
    await page.getByRole('combobox',{name:'配置备份',exact:true}).locator('option').nth(1).waitFor({state:'attached'});
    await page.getByRole('combobox',{name:'配置备份',exact:true}).selectOption(choice);
    page.once('dialog',d=>d.accept());await save(page.getByRole('button',{name:'从备份修复配置',exact:true}));
    assert.deepEqual(fs.readFileSync(path.join(root,'backups','config-damaged-'+hash(damaged)+'.raw')),damaged);
    assert.equal(JSON.parse(fs.readFileSync(config,'utf8')).schema_version,4);
    assert.equal((await page.locator('body').textContent()).includes('isolated-damaged-sentinel'),false);
    await page.setViewportSize({width:640,height:480});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(root,'browser-acceptance-result.json'),JSON.stringify({ok:true,checks:['all POST routes reject missing session/CSRF/cross-origin/host/content-type','three URL/Key-only upstreams','keyboard open/Escape/focus return','long Chinese notes/narrow viewport','model-form stale source rejected','settings backup restore','corrupt-file repair/exact-byte backup'],security_cases:routes.length*5,page_errors:errors,external_requests:external,paid_creates:0,human_screen_reader:'not-performed'},null,2));
    console.log('HTTP security and browser acceptance passed.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
