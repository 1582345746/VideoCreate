// Restart only owned synthetic servers on one ephemeral port. The two config
// files deliberately have identical contents: content fingerprints cannot prove path.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),out=path.resolve(process.env.VC_WEB_CONTEXT_OUT||path.join(root,'_local/web-config-context-20261114'));
const source=process.env.VC_WEB_SOURCE||path.join(root,'videocreate/src');
const python=process.env.VC_WEB_PYTHON||path.join(root,'_local/web-venv/Scripts/python.exe');
const pause=ms=>new Promise(r=>setTimeout(r,ms)),hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
(async()=>{
  assert.ok(out.startsWith(path.join(root,'_local')+path.sep));assert.equal(fs.existsSync(out),false);fs.mkdirSync(out,{recursive:true});
  const tmp=path.join(out,'tmp');fs.mkdirSync(tmp);
  process.env.TEMP=tmp;process.env.TMP=tmp;
  const env={...process.env,PYTHONPATH:source+path.delimiter+path.join(root,'tests'),PYTHONDONTWRITEBYTECODE:'1',TEMP:tmp,TMP:tmp,VIDEOCREATE_CONFIG_DIR:path.join(out,'unused')};
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));assert.notEqual(port,8765);
  const origin='http://127.0.0.1:'+port,cases=[],errors=[],external=[],instances=[],pids=[];
  let server,pid,log='',browser,context,page,paths,active,lost=false,posted=[];
  async function stop(){
    if(!server)return;const child=server,owned=pid;server=null;pid=null;
    const closed=new Promise(r=>child.once('close',r));process.kill(owned,'SIGKILL');
    await Promise.race([closed,pause(10000).then(()=>{throw Error('Owned service did not stop')})]);
    await assert.rejects(fetch(origin+'/health'));
  }
  async function start(which){
    await stop();active=which;let output='';
    server=spawn(python,['-B','-X','utf8','-c',`import os,sys\nprint('OWNED_PID='+str(os.getpid()),flush=True)\nfrom videocreate.config_web.launcher import main\nraise SystemExit(main(sys.argv[1:]))`,'--config',paths[which],'--port',String(port),'--no-browser'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
    server.stdout.on('data',c=>{output+=c;const m=output.match(/OWNED_PID=(\d+)/);if(m)pid=Number(m[1])});server.stderr.on('data',c=>output+=c);
    const end=Date.now()+12000;let health;
    while(Date.now()<end){try{health=await(await fetch(origin+'/health')).json();if(health.product==='VideoCreateConfigWeb'&&pid)break}catch{}await pause(70)}
    assert.ok(pid&&health,output);assert.equal(health.product,'VideoCreateConfigWeb');instances.push(health.instance_id);pids.push(pid);log+=which+' '+output+'\n';return health;
  }
  async function api(endpoint,body){return page.evaluate(async({endpoint,body})=>{
    const headers={'X-VC-Client':'1'};
    if(body!==undefined){const session=await(await fetch('/api/session',{headers})).json();headers['X-VC-CSRF']=session.csrf_token;headers['Content-Type']='application/json'}
    const response=await fetch('/api/'+endpoint,{method:body===undefined?'GET':'POST',headers,body:JSON.stringify(body)});
    return {status:response.status,data:await response.json()};
  },{endpoint,body})}
  async function ready(){await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor()}
  async function storage(){return page.evaluate(()=>({...sessionStorage}))}
  async function draft(kind,action){const result=page.waitForResponse(r=>r.url()===origin+'/api/drafts/save'&&(r.request().postDataJSON().form.kind||'upstream')===kind);await action();const r=await result;assert.equal(r.status(),200);return r.json()}
  async function upstream(label){
    await page.getByRole('button',{name:/添加上游/}).click();const d=page.getByRole('dialog');
    await d.getByLabel('API 地址（URL）').fill('https://'+label+'.invalid/v1');await d.getByText('名称与备注（可选）',{exact:true}).click();
    const saved=await draft('upstream',()=>d.getByLabel('显示名称',{exact:true}).fill(label));return {d,saved};
  }
  async function lose(d){lost=true;await d.getByLabel('API 密钥（Key）').fill('NEVER-PERSIST-CONTEXT-KEY');await d.getByRole('button',{name:'保存上游',exact:true}).click();await d.getByRole('alert').waitFor();lost=false}
  async function check(name,run){
    try{
      await stop();const folder=path.join(out,'case-'+(cases.length+1));fs.mkdirSync(folder);paths={A:path.join(folder,'配置 A','config.json'),B:path.join(folder,'配置 B','config.json')};
      const setup=spawnSync(python,['-B','-X','utf8','-c',`import sys\nfrom pathlib import Path\nfrom test_v3_config import config\nfrom videocreate.config import management as m\nfrom videocreate.config.storage import atomic_json\nv=m.migrate(config())\nfor name in sys.argv[1:]:\n p=Path(name);atomic_json(p,v);atomic_json(p.parent/'backups'/('config-'+m.fingerprint(v)+'.json'),v)`,paths.A,paths.B],{cwd:root,env,encoding:'utf8',windowsHide:true});assert.equal(setup.status,0,setup.stderr);assert.equal(hash(paths.A),hash(paths.B));
      context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();page.setDefaultTimeout(4500);posted=[];lost=false;
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
      await page.route('**/*',async route=>{
        const req=route.request(),url=req.url();if(!url.startsWith(origin+'/')){external.push(url);return route.abort()}
        if(req.method()==='POST')posted.push({active,path:url.slice(origin.length),body:req.postDataJSON(),config_header:req.headers()['x-vc-config']});
        if(url.endsWith('/api/catalog/check'))throw Error('Upstream checks forbidden');
        if(lost&&url.endsWith('/api/changes/commit')){const r=await route.fetch();assert.equal(r.status(),200);return route.abort('failed')}
        return route.continue();
      });
      const detail=await run()||{};cases.push({name,ok:true,...detail});
    }catch(e){cases.push({name,ok:false,error:e.message});if(page)await page.screenshot({path:path.join(out,'failure-'+cases.length+'.png'),fullPage:true})}
    finally{if(context)await context.close();context=null;await stop()}
  }
  try{
    browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    await check('same port A to B to A retains each pending token and never queries foreign receipt',async()=>{
      const a=await start('A');await ready();const first=await upstream('context-a');await lose(first.d);const storedA=await storage();
      const pendingA=Object.entries(storedA).find(([k])=>k.startsWith('vc-pending-change'));assert.ok(pendingA);
      await start('B');await ready();assert.equal(await page.getByText('有一次保存结果尚未核对。',{exact:false}).count(),0,'Foreign pending receipt shown in B');
      assert.equal((await storage())[pendingA[0]],pendingA[1]);assert.equal(posted.filter(p=>p.active==='B'&&p.path==='/api/changes/status').length,0);
      assert.equal(await page.getByRole('button',{name:'恢复草稿',exact:true}).count(),0);
      const second=await upstream('context-b');await lose(second.d);const storedB=await storage();const pendingB=Object.entries(storedB).find(([k])=>k.startsWith('vc-pending-change')&&k!==pendingA[0]);assert.ok(pendingB,'B overwrote A pending capability');
      await start('A');await ready();await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await page.getByText(/已核对：上一次配置保存成功/).waitFor();
      assert.equal((await storage())[pendingA[0]],undefined);assert.equal((await storage())[pendingB[0]],pendingB[1]);assert.equal((await api('drafts/load',{draft_token:first.saved.draft_token})).status,200);
      await start('B');await ready();await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await page.getByText(/已核对：上一次配置保存成功/).waitFor();assert.equal((await storage())[pendingB[0]],undefined);
      assert.equal(Object.keys(JSON.parse(fs.readFileSync(paths.A))).includes('api_key'),false);return {distinct_configs:2,distinct_pending_keys:true,one_original_commit_per_config:true,config_id:a.config_id};
    });
    await check('draft capability remains recoverable after another configuration reuses port',async()=>{
      await start('A');await ready();const {saved}=await upstream('draft-in-a');const stored=await storage();const key=Object.keys(stored).find(k=>k.startsWith('vc-upstream-draft'));assert.ok(key);
      await start('B');await ready();assert.equal((await storage())[key],saved.draft_token,'Opening B destroyed A draft capability');assert.equal(await page.getByRole('button',{name:'恢复草稿',exact:true}).count(),0);
      const other=await upstream('draft-in-b');await start('A');await ready();await page.getByRole('button',{name:'恢复草稿',exact:true}).click();
      assert.equal(await page.getByRole('dialog').getByLabel('显示名称',{exact:true}).inputValue(),'draft-in-a');assert.equal(await page.getByRole('dialog').getByLabel('API 密钥（Key）').inputValue(),'');
      assert.ok(Object.values(await storage()).includes(other.saved.draft_token));return {both_drafts_preserved:true,only_current_offer:true};
    });
    await check('same-page refresh after port switch blocks source form from writing identical B config',async()=>{
      const a=await start('A');await ready();const catalog=(await api('catalog')).data;
      await page.getByRole('button',{name:'默认选择',exact:true}).click();
      for(const [kind,label] of [['image','图片'],['video','视频']])await page.getByRole('combobox',{name:label+'默认接入',exact:true}).selectOption(catalog.bindings.find(b=>b.kind===kind&&b.default_eligible)?.id||'');
      await draft('defaults',()=>page.getByRole('combobox',{name:'视频默认策略',exact:true}).selectOption('use-default'));
      const originalB=hash(paths.B);await start('B');await page.getByRole('button',{name:'保存默认选择',exact:true}).click();await page.getByRole('alert').first().waitFor();
      await page.getByRole('button',{name:'重新读取',exact:true}).click();
      await page.getByRole('alert').filter({hasText:/另一份配置/}).waitFor();
      assert.equal(await page.getByRole('combobox',{name:'视频默认策略',exact:true}).inputValue(),'use-default');assert.equal(hash(paths.B),originalB);
      await page.getByRole('button',{name:'保存默认选择',exact:true}).click();await page.waitForTimeout(200);assert.equal(hash(paths.B),originalB);
      assert.equal(posted.filter(p=>p.active==='B'&&p.path==='/api/changes/commit').length,0);return {identical_fingerprints:true,foreign_commit_requests:0,old_config_id:a.config_id,foreign_bytes_unchanged:true};
    });
    await check('legacy draft tokens migrate only where the original server can actually load them',async()=>{
      const a=await start('A');await ready();const {saved}=await upstream('legacy-a');
      await page.evaluate(token=>{for(const k of Object.keys(sessionStorage))if(k.startsWith('vc-upstream-draft'))sessionStorage.removeItem(k);sessionStorage.setItem('vc-upstream-draft',token)},saved.draft_token);
      await start('B');await ready();assert.equal((await storage())['vc-upstream-draft'],saved.draft_token,'Legacy A token erased by B');
      await start('A');await ready();await page.getByRole('button',{name:'恢复草稿',exact:true}).waitFor();const stored=await storage();
      assert.equal(stored['vc-upstream-draft'],undefined);assert.equal(stored['vc-upstream-draft:'+a.config_id],saved.draft_token);return {legacy_migration_verified_against_server:true};
    });
    await check('legacy unscoped pending record requires explicit original-path confirmation',async()=>{
      await start('A');await ready();const {d}=await upstream('legacy-pending');await lose(d);
      await page.evaluate(()=>{const key=Object.keys(sessionStorage).find(k=>k.startsWith('vc-pending-change'));const token=sessionStorage.getItem(key);sessionStorage.removeItem(key);sessionStorage.setItem('vc-pending-change',token)});
      await start('B');await ready();page.removeAllListeners('dialog');let prompt='';page.on('dialog',d=>{prompt=d.message();return d.dismiss()});
      await page.getByRole('button',{name:'核对保存结果',exact:true}).click();assert.match(prompt,/原配置/);assert.match(prompt,/配置 B/);assert.ok((await storage())['vc-pending-change']);
      assert.equal(posted.filter(p=>p.active==='B'&&p.path==='/api/changes/status').length,0);
      page.removeAllListeners('dialog');page.on('dialog',d=>d.accept());await start('A');await ready();await page.getByRole('button',{name:'核对保存结果',exact:true}).click();await page.getByText(/已核对：上一次配置保存成功/).waitFor();assert.equal((await storage())['vc-pending-change'],undefined);return {legacy_not_silently_assigned:true};
    });
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{if(browser)await browser.close();await stop();fs.writeFileSync(path.join(out,'server.log'),log)}
  const result={ok:cases.every(c=>c.ok),cases,server_processes:pids.length,distinct_instances:new Set(instances).size,pids,page_errors:errors,external_requests:external,paid_creates:0,existing_8765_touched:false,source};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));if(!result.ok)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
