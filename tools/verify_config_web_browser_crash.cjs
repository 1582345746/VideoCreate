// Uses a new F-drive Chrome profile and synthetic config; only its verified
// browser PID is killed. No user browser, upstream request or port 8765 is used.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),out=path.resolve(process.env.VC_WEB_CRASH_OUT||path.join(root,'_local/web-browser-crash-20261113'));
const python=process.env.VC_WEB_PYTHON||path.join(root,'_local/web-venv/Scripts/python.exe');
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex'),pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  assert.ok(out.startsWith(path.join(root,'_local')+path.sep));assert.equal(fs.existsSync(out),false,'Choose new evidence directory');fs.mkdirSync(out,{recursive:true});
  const config=path.join(out,'config.json'),tmp=path.join(out,'tmp'),profile=path.join(out,'isolated-chrome');fs.mkdirSync(tmp);
  const env={...process.env,PYTHONPATH:path.join(root,'videocreate/src')+path.delimiter+path.join(root,'tests'),PYTHONDONTWRITEBYTECODE:'1',TEMP:tmp,TMP:tmp,VIDEOCREATE_CONFIG_DIR:path.join(out,'unused')};
  const setup=spawnSync(python,['-B','-X','utf8','-c',`import sys\nfrom pathlib import Path\nfrom test_v3_config import config\nfrom videocreate.config import management as m\nfrom videocreate.config.storage import atomic_json\np=Path(sys.argv[1]);v=m.migrate(config());atomic_json(p,v);atomic_json(p.parent/'backups'/('config-'+m.fingerprint(v)+'.json'),v)`,config],{cwd:root,env,encoding:'utf8',windowsHide:true});assert.equal(setup.status,0,setup.stderr);
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));assert.notEqual(port,8765);
  const origin='http://127.0.0.1:'+port,errors=[],external=[],checks=[];let server,pid,context,output='',listCalls=0;
  function track(page){page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());page.on('request',r=>{if(r.url()===origin+'/api/drafts/list')listCalls++})}
  async function launch(){
    context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--enable-automation'],viewport:{width:1440,height:1000},env});
    await context.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
    context.on('page',track);for(const page of context.pages())track(page);
  }
  async function page(){const p=await context.newPage();await p.goto(origin);await p.getByRole('table',{name:'模型列表'}).waitFor();return p}
  async function saveDraft(p,action){const response=p.waitForResponse(r=>r.url()===origin+'/api/drafts/save');const [r]=await Promise.all([response,action()]);assert.equal(r.status(),200);return r.json()}
  async function list(p){await p.getByText('本机未提交草稿',{exact:true}).click();const response=p.waitForResponse(r=>r.url()===origin+'/api/drafts/list');await p.getByRole('button',{name:'读取本机草稿列表',exact:true}).click();assert.equal((await response).status(),200);const items=p.getByRole('list',{name:'本机草稿列表'});await items.waitFor();return items}
  async function recover(p,label){const items=await list(p);await items.getByRole('listitem').filter({hasText:label}).getByRole('button',{name:'恢复输入',exact:true}).click()}
  async function api(p,route,body){return p.evaluate(async({route,body})=>{const s=await(await fetch('/api/session',{headers:{'X-VC-Client':'1'}})).json();const r=await fetch('/api/'+route,{method:'POST',headers:{'X-VC-Client':'1','Content-Type':'application/json','X-VC-CSRF':s.csrf_token},body:JSON.stringify(body)});return{status:r.status,data:await r.json()}},{route,body})}
  try{
    server=spawn(python,['-B','-X','utf8','-c',`import os,sys\nprint('VC_TEST_PID='+str(os.getpid()),flush=True)\nfrom videocreate.config_web.launcher import main\nraise SystemExit(main(sys.argv[1:]))`,'--config',config,'--port',String(port),'--no-browser'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
    server.stdout.on('data',c=>{output+=c;const m=output.match(/VC_TEST_PID=(\d+)/);if(m)pid=Number(m[1])});server.stderr.on('data',c=>output+=c);
    let health;for(let i=0;i<100;i++){try{health=await(await fetch(origin+'/health')).json();break}catch{}await pause(100)}assert.equal(health?.product,'VideoCreateConfigWeb');assert.ok(pid);
    const original=hash(fs.readFileSync(config));await launch();const saved={};
    const up=await page();await up.getByRole('button',{name:'＋ 添加上游',exact:true}).click();
    await up.getByRole('dialog').getByLabel('API 地址（URL）').fill('https://browser-crash.example.test/v1');
    saved.upstream=await saveDraft(up,async()=>{await up.getByText('名称与备注（可选）',{exact:true}).click();await up.getByRole('dialog').getByLabel('备注',{exact:true}).fill('PRIVATE-UNCOMMITTED-NOTE')});
    await up.getByRole('dialog').getByLabel('API 密钥（Key）').fill('NEVER-PERSIST-BROWSER-KEY');
    const model=await page(),catalog=await model.evaluate(async()=>(await fetch('/api/catalog',{headers:{'X-VC-Client':'1'}})).json());
    const image=catalog.bindings.find(b=>b.id==='image-primary');assert.ok(image);
    await model.getByRole('button',{name:'模型目录',exact:true}).click();await model.getByRole('searchbox',{name:'搜索模型'}).fill(image.remote_model);
    await model.locator('tbody tr').filter({hasText:image.upstream_name}).first().click();
    await model.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
    await model.getByRole('dialog').getByLabel('显示名称',{exact:true}).fill('浏览器崩溃后模型输入');
    await model.getByRole('dialog').getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    const imagePricing={currency:'USD',per_image:.04,tiers:[{when:{operation:'text-to-image'},per_request:.01,per_image:.06}]};
    saved.binding=await saveDraft(model,()=>model.getByRole('dialog').getByLabel('预算价格、条件档位和计费规则',{exact:true}).fill(JSON.stringify(imagePricing)));
    assert.deepEqual(saved.binding.omitted_sections,[]);
    const defaults=await page();await defaults.getByRole('button',{name:'默认选择',exact:true}).click();saved.defaults=await saveDraft(defaults,()=>defaults.getByRole('combobox',{name:'视频默认策略',exact:true}).selectOption('use-default'));
    const repair=await page();await repair.getByRole('button',{name:'设置',exact:true}).click();const backup=await repair.getByRole('combobox',{name:'配置备份',exact:true}).locator('option').nth(1).getAttribute('value');saved.repair=await saveDraft(repair,()=>repair.getByRole('combobox',{name:'配置备份',exact:true}).selectOption(backup));
    assert.equal(listCalls,0,'No automatic draft enumeration');
    for(const p of [up,model,defaults,repair])await p.evaluate(()=>{sessionStorage.clear();localStorage.clear()});
    const cdp=await context.browser().newBrowserCDPSession();const command=await cdp.send('Browser.getBrowserCommandLine');assert.ok(command.arguments.some(a=>a.startsWith('--user-data-dir=')&&path.resolve(a.slice(16))===profile));
    const info=await cdp.send('SystemInfo.getProcessInfo'),browserPid=info.processInfo.find(p=>p.type==='browser').id;assert.ok(browserPid>0&&browserPid!==pid);
    const disconnected=new Promise(r=>context.browser().once('disconnected',r));process.kill(browserPid,'SIGKILL');await Promise.race([disconnected,pause(10000).then(()=>{throw Error('Test Chrome did not exit')})]);context=null;
    await launch();const fresh=await page();assert.equal(await fresh.evaluate(()=>sessionStorage.length),0);assert.equal(listCalls,0);assert.equal(await fresh.getByRole('dialog').count(),0);
    const items=await list(fresh);assert.equal(await items.getByRole('listitem').count(),4);assert.equal((await items.textContent()).includes('PRIVATE-UNCOMMITTED'),false);assert.equal((await items.textContent()).includes('browser-crash.example'),false);
    await fresh.setViewportSize({width:390,height:844});assert.equal(await fresh.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await fresh.screenshot({path:path.join(out,'draft-list-mobile.png'),fullPage:true});
    await items.getByRole('listitem').filter({hasText:'上游输入'}).getByRole('button',{name:'恢复输入',exact:true}).click();
    assert.equal(await fresh.getByRole('dialog').getByLabel('API 地址（URL）').inputValue(),'https://browser-crash.example.test/v1');assert.equal(await fresh.getByRole('dialog').getByLabel('API 密钥（Key）').inputValue(),'');assert.equal(hash(fs.readFileSync(config)),original);
    checks.push('Actual isolated Chrome PID killed; sessionStorage identifiers lost; explicit metadata discovery recovers upstream without Key or config write');
    const b=await page();await recover(b,'模型资料');assert.equal(await b.getByRole('dialog').getByLabel('显示名称',{exact:true}).inputValue(),'浏览器崩溃后模型输入');
    const restored=b.getByRole('dialog');
    if(!await restored.locator('details').first().evaluate(el=>el.open))await restored.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    assert.deepEqual(JSON.parse(await restored.getByLabel('预算价格、条件档位和计费规则',{exact:true}).inputValue()),imagePricing);
    const imageBudget=restored.locator('.contract-group').nth(3);await imageBudget.locator('summary').click();
    assert.equal(await imageBudget.getByLabel('预算每张价格（仅图片）',{exact:true}).inputValue(),'0.04');
    assert.equal(await imageBudget.getByLabel('档位 1 每张价格（仅图片）',{exact:true}).inputValue(),'0.06');
    checks.push('Requested-image base and tier pricing survive actual browser crash and restore into structured fields without configuration save');
    const d=await page();await recover(d,'默认选择');assert.equal(await d.getByRole('combobox',{name:'视频默认策略',exact:true}).inputValue(),'use-default');
    const r=await page();await recover(r,'备份选择');assert.equal(await r.getByRole('combobox',{name:'配置备份',exact:true}).inputValue(),backup);assert.equal(hash(fs.readFileSync(config)),original);
    checks.push('All four forms recover after real browser crash and lost tab capabilities; no automatic apply');
    // Two tabs share one cookie. Explicit claim in tab two must invalidate tab one.
    const two=await page();await recover(two,'上游输入');await two.getByText('名称与备注（可选）',{exact:true}).click();await fresh.getByText('名称与备注（可选）',{exact:true}).click();const remote=await saveDraft(two,()=>two.getByRole('dialog').getByLabel('显示名称',{exact:true}).fill('其他窗口的新输入'));
    const collision=fresh.waitForResponse(x=>x.url()===origin+'/api/drafts/save');await fresh.getByRole('dialog').getByLabel('显示名称',{exact:true}).fill('保留在第一窗口');assert.equal((await collision).status(),409);
    await fresh.getByRole('button',{name:'将当前上游输入另存新草稿',exact:true}).waitFor();assert.equal(await fresh.getByRole('dialog').getByLabel('显示名称',{exact:true}).inputValue(),'保留在第一窗口');
    let repeated=0;fresh.on('request',r=>{if(r.url()===origin+'/api/drafts/save')repeated++});await fresh.getByRole('dialog').getByLabel('显示名称',{exact:true}).fill('第一窗口继续输入');await pause(900);assert.equal(repeated,0,'Conflict blocks repeated autosave');
    const latest=await api(two,'drafts/load',{draft_token:remote.draft_token});assert.equal(latest.data.form.name,'其他窗口的新输入');
    const forked=await saveDraft(fresh,()=>fresh.getByRole('button',{name:'将当前上游输入另存新草稿',exact:true}).click());assert.notEqual(forked.draft_token,remote.draft_token);assert.equal((await api(two,'drafts/load',{draft_token:remote.draft_token})).data.form.name,'其他窗口的新输入');
    checks.push('Same-cookie competing tabs: stale save is 409, input retained, autosave paused, explicit fork preserves both drafts');
    // Stale list discard is rejected and must preserve the new draft version.
    const stale=await api(two,'drafts/discard',{draft_token:remote.draft_token,expected_version:saved.upstream.draft_version});assert.equal(stale.status,409);assert.equal((await api(two,'drafts/load',{draft_token:remote.draft_token})).status,200);
    await d.getByRole('list',{name:'本机草稿列表'}).getByRole('listitem').filter({hasText:'模型资料'}).getByRole('button',{name:'恢复输入',exact:true}).click();
    await d.getByRole('alert').filter({hasText:'请先保存或关闭当前表单'}).waitFor();assert.equal(await d.getByRole('combobox',{name:'视频默认策略',exact:true}).inputValue(),'use-default');
    checks.push('Stale discard preserves newer version; recovering another draft protects existing unsaved form');
    // Metadata and raw drafts never contain the Key sentinel.
    const runtime=path.join(out,'runtime/config-web');for(const folder of fs.readdirSync(runtime,{withFileTypes:true}).filter(d=>d.isDirectory())){const drafts=path.join(runtime,folder.name,'drafts');if(fs.existsSync(drafts))for(const name of fs.readdirSync(drafts))if(name.endsWith('.json'))assert.equal(fs.readFileSync(path.join(drafts,name),'utf8').includes('NEVER-PERSIST-BROWSER-KEY'),false)}
    assert.equal(hash(fs.readFileSync(config)),original);
    // A config commit can succeed while its advisory draft cleanup conflicts.
    // The UI must close successfully, retain the other window's newer draft,
    // and permit a fresh form instead of leaving a stale local capability.
    const current=await api(b,'drafts/load',{draft_token:saved.binding.draft_token});
    const competing=await api(b,'drafts/load',{draft_token:saved.binding.draft_token,claim:true,expected_version:current.data.draft_version});assert.equal(competing.status,200);
    const bConflict=b.waitForResponse(x=>x.url()===origin+'/api/drafts/save');await b.getByRole('dialog').getByLabel('备注',{exact:true}).fill('明确保存的资料');assert.equal((await bConflict).status(),409);
    const committed=b.waitForResponse(x=>x.url()===origin+'/api/changes/commit');await b.getByRole('dialog').getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await committed).status(),200);await b.getByRole('dialog').waitFor({state:'hidden'});
    assert.notEqual(hash(fs.readFileSync(config)),original);const retained=await api(b,'drafts/load',{draft_token:saved.binding.draft_token});assert.equal(retained.data.draft_version,competing.data.draft_version);
    assert.deepEqual(JSON.parse(fs.readFileSync(config,'utf8')).bindings[image.id].pricing,imagePricing);
    await b.getByRole('button',{name:'编辑资料与价格',exact:true}).click();await b.getByRole('dialog').waitFor();
    checks.push('Explicit config save succeeds despite stale draft cleanup, preserves competing draft, and allows a fresh form');
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks,actual_browser_pid_killed:browserPid,browser_profile:profile,server_pid:pid,configuration_unchanged_until_manual_save:true,manual_config_commits:1,page_errors:errors,external_requests:external,paid_creates:0,existing_8765_touched:false},null,2));console.log(JSON.stringify({ok:true,checks,out}));
  }finally{
    if(context)await context.close();if(server&&pid){const closed=new Promise(r=>server.once('close',r));process.kill(pid,'SIGKILL');await Promise.race([closed,pause(10000)])}fs.writeFileSync(path.join(out,'server.log'),output);
  }
})().catch(e=>{console.error(e);process.exitCode=1});
