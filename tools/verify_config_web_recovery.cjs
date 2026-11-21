// Kills only the synthetic server PID printed by its own Python child. Never
// touches the installed server, real configuration, credentials or port 8765.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process'),net=require('node:net');
const root=path.resolve(__dirname,'..'),out=path.resolve(process.env.VC_WEB_RECOVERY_OUT||path.join(root,'_local/web-recovery-20261113'));
const python=process.env.VC_WEB_PYTHON||path.join(root,'_local/web-venv/Scripts/python.exe');
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  assert.ok(out.startsWith(path.join(root,'_local')+path.sep));assert.equal(fs.existsSync(out),false,'Use a fresh evidence directory');fs.mkdirSync(out,{recursive:true});
  const config=path.join(out,'config.json'),tmp=path.join(out,'tmp');fs.mkdirSync(tmp);
  const env={...process.env,PYTHONPATH:path.join(root,'videocreate/src')+path.delimiter+path.join(root,'tests'),PYTHONDONTWRITEBYTECODE:'1',TEMP:tmp,TMP:tmp,VIDEOCREATE_CONFIG_DIR:path.join(out,'unused-config')};
  const setup=spawnSync(python,['-B','-X','utf8','-c',`import sys\nfrom pathlib import Path\nfrom test_v3_config import config\nfrom videocreate.config import management as m\nfrom videocreate.config.storage import atomic_json\np=Path(sys.argv[1]);v=m.migrate(config());atomic_json(p,v);atomic_json(p.parent/'backups'/('config-'+m.fingerprint(v)+'.json'),v)`,config],{cwd:root,env,encoding:'utf8',windowsHide:true});
  assert.equal(setup.status,0,setup.stderr);
  const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));assert.notEqual(port,8765);
  const origin='http://127.0.0.1:'+port,pids=[],instances=[],errors=[],external=[],checks=[];
  let server,actualPid,output='',browser;
  async function start(){
    output='';actualPid=undefined;
    server=spawn(python,['-B','-X','utf8','-c',`import os,sys\nprint('VC_TEST_PID='+str(os.getpid()),flush=True)\nfrom videocreate.config_web.launcher import main\nraise SystemExit(main(sys.argv[1:]))`,'--config',config,'--port',String(port),'--no-browser'],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
    server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/VC_TEST_PID=(\d+)/);if(match)actualPid=Number(match[1]);});server.stderr.on('data',chunk=>output+=chunk);
    const deadline=Date.now()+15000;let active;
    while(Date.now()<deadline){try{const response=await fetch(origin+'/health');if(response.ok){active=await response.json();break}}catch{}await pause(100)}
    assert.ok(active&&actualPid,output);assert.equal(active.product,'VideoCreateConfigWeb');assert.equal(active.mode,'editable');
    assert.equal(instances.includes(active.instance_id),false);instances.push(active.instance_id);pids.push(actualPid);
  }
  async function stop(){
    if(!server||!actualPid)return;
    const child=server,pid=actualPid;server=null;actualPid=null;
    const closed=new Promise(resolve=>child.once('close',resolve));process.kill(pid,'SIGKILL');
    await Promise.race([closed,pause(10000).then(()=>{throw new Error('Synthetic Python child did not exit')})]);
    await assert.rejects(fetch(origin+'/health'));
  }
  try{
    await start();browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
    async function ready(){await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor()}
    async function api(route){return page.evaluate(async route=>(await fetch('/api/'+route,{headers:{'X-VC-Client':'1'}})).json(),route)}
    async function savedDraft(kind,action){
      const response=page.waitForResponse(r=>r.url()===origin+'/api/drafts/save'&&r.request().postDataJSON().form.kind===kind,{timeout:10000});await action();
      try{const r=await response;assert.equal(r.status(),200);return r.json()}catch(e){
        fs.writeFileSync(path.join(out,'draft-failure-ui.json'),JSON.stringify({kind,alerts:await page.getByRole('alert').allTextContents(),notices:await page.locator('.notice').allTextContents(),hints:await page.locator('.hint').allTextContents()},null,2));throw e;
      }
    }
    async function restart(){await stop();await start();await ready()}
    async function commit(button){
      const done=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit',{timeout:10000});await button.click();
      try{assert.equal((await done).status(),200)}catch(e){
        fs.writeFileSync(path.join(out,'failure-ui.json'),JSON.stringify({alerts:await page.getByRole('alert').allTextContents(),button:await button.evaluate(b=>({disabled:b.disabled,text:b.textContent})),notices:await page.locator('.notice').allTextContents()},null,2));
        await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;
      }
    }
    await ready();let before=hash(fs.readFileSync(config));
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();let model=page.getByRole('dialog');
    await model.getByLabel('显示名称',{exact:true}).fill('进程重启后恢复的模型');
    await model.getByLabel('备注',{exact:true}).fill('保留中文与换行\n仅离线夹具');
    await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    await model.getByLabel('展示报价与来源',{exact:true}).fill('{"amount":0.25,"currency":"USD","unit":"second"}');
    const saved=await savedDraft('binding',()=>model.getByLabel('预算价格、条件档位和计费规则',{exact:true}).fill('{"per_second":'));
    assert.deepEqual(saved.omitted_sections,['pricing']);await restart();
    await page.getByRole('button',{name:'恢复模型草稿',exact:true}).click();model=page.getByRole('dialog');
    assert.equal(await model.getByLabel('显示名称',{exact:true}).inputValue(),'进程重启后恢复的模型');assert.match(await model.getByLabel('备注',{exact:true}).inputValue(),/\n/);
    assert.equal(await model.locator('details').first().evaluate(el=>el.open),false);assert.match(await model.getByLabel('展示报价与来源',{exact:true}).inputValue(),/0.25/);
    assert.equal(hash(fs.readFileSync(config)),before);checks.push('model survives actual forced server exit; invalid JSON omitted; no automatic commit');
    await stop();const changed=JSON.parse(fs.readFileSync(config,'utf8'));changed.revision++;fs.writeFileSync(config,JSON.stringify(changed));before=hash(fs.readFileSync(config));await start();await ready();
    await page.getByRole('button',{name:'恢复模型草稿',exact:true}).click();model=page.getByRole('dialog');assert.equal(await model.getByRole('button',{name:'保存模型资料',exact:true}).isDisabled(),true);
    await model.getByRole('button',{name:'使用当前模型重新核对',exact:true}).click();await commit(model.getByRole('button',{name:'保存模型资料',exact:true}));await model.waitFor({state:'hidden'});
    assert.notEqual(hash(fs.readFileSync(config)),before);checks.push('changed model source blocks save until explicit review; manual save only');
    await page.getByRole('button',{name:'默认选择',exact:true}).click();
    const catalog=await api('catalog'),video=catalog.bindings.find(b=>b.kind==='video'&&b.default_eligible),image=catalog.bindings.find(b=>b.kind==='image'&&b.default_eligible);assert.ok(video);
    // The baseline fixture deliberately contains an unready image default.
    // Choose an eligible image or explicitly leave it unset before saving.
    await page.getByRole('combobox',{name:'图片默认接入',exact:true}).selectOption(image?.id||'');
    await page.getByRole('combobox',{name:'视频默认接入',exact:true}).selectOption(video.id);
    await savedDraft('defaults',()=>page.getByRole('combobox',{name:'视频默认策略',exact:true}).selectOption('use-default'));
    before=hash(fs.readFileSync(config));await restart();await page.getByRole('button',{name:'恢复默认草稿',exact:true}).click();
    assert.equal(await page.getByRole('combobox',{name:'视频默认策略',exact:true}).inputValue(),'use-default');assert.equal(hash(fs.readFileSync(config)),before);
    await commit(page.getByRole('button',{name:'保存默认选择',exact:true}));checks.push('independent default choices survive process restart without applying themselves');
    await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('combobox',{name:'配置备份',exact:true}).waitFor();
    const backups=await api('backups');const backup=backups.backups[0].id;
    await savedDraft('repair',()=>page.getByRole('combobox',{name:'配置备份',exact:true}).selectOption(backup));before=hash(fs.readFileSync(config));await restart();
    await page.getByRole('button',{name:'恢复备份选择',exact:true}).click();assert.equal(await page.getByRole('combobox',{name:'配置备份',exact:true}).inputValue(),backup);assert.equal(hash(fs.readFileSync(config)),before);
    await page.getByRole('button',{name:'恢复所选备份',exact:true}).waitFor();checks.push('backup choice survives process exit; recovery does not restore configuration');
    await page.reload();await page.getByRole('button',{name:'丢弃备份选择',exact:true}).click();await page.getByRole('button',{name:'丢弃备份选择',exact:true}).waitFor({state:'hidden'});
    await stop();const damaged=Buffer.from('{"schema_version":4,"auth":"DO-NOT-EXPORT-DAMAGED-SECRET",}');fs.writeFileSync(config,damaged);await start();await page.goto(origin);
    await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('combobox',{name:'配置备份',exact:true}).waitFor();
    await savedDraft('repair',()=>page.getByRole('combobox',{name:'配置备份',exact:true}).selectOption(backup));await stop();fs.appendFileSync(config,' ');const damagedFinal=fs.readFileSync(config);await start();await page.goto(origin);
    // A fresh page starts outside Settings. Repair metadata must be ready
    // without a navigation workaround before the existing draft can be claimed.
    const repairOffer=page.getByRole('button',{name:'恢复备份选择',exact:true});
    await repairOffer.click();assert.equal(await page.getByRole('button',{name:'从备份修复配置',exact:true}).isDisabled(),true);assert.deepEqual(fs.readFileSync(config),damagedFinal);
    await page.getByRole('button',{name:'使用当前文件重新核对',exact:true}).click();await commit(page.getByRole('button',{name:'从备份修复配置',exact:true}));
    const rawBackup=path.join(out,'backups','config-damaged-'+hash(damagedFinal)+'.raw');assert.deepEqual(fs.readFileSync(rawBackup),damagedFinal);
    checks.push('damaged-file recovery detects exact-byte source conflict and preserves original bytes on explicit repair');
    await page.getByRole('button',{name:'上游管理',exact:true}).click();await page.getByRole('button',{name:/添加上游/}).click();
    await page.getByRole('dialog').getByLabel('API 地址（URL）').fill('https://process-draft.example.test/v1');
    await page.getByRole('dialog').getByLabel('API 密钥（Key）').fill('NEVER-PERSIST-PROCESS-KEY');await page.getByText('非秘密输入已暂存；API 密钥不会保存到表单草稿。',{exact:true}).waitFor();
    before=hash(fs.readFileSync(config));await restart();await page.getByRole('button',{name:'恢复草稿',exact:true}).click();
    assert.equal(await page.getByRole('dialog').getByLabel('API 密钥（Key）').inputValue(),'');assert.equal(hash(fs.readFileSync(config)),before);
    const tokens=await page.evaluate(()=>JSON.stringify({...sessionStorage,...localStorage}));assert.equal(tokens.includes('NEVER-PERSIST'),false);
    const draftRoot=path.join(out,'runtime/config-web');for(const identity of fs.readdirSync(draftRoot,{withFileTypes:true}).filter(d=>d.isDirectory())){
      const drafts=path.join(draftRoot,identity.name,'drafts');if(fs.existsSync(drafts))for(const f of fs.readdirSync(drafts))if(f.endsWith('.json')){
        const raw=fs.readFileSync(path.join(drafts,f),'utf8');assert.equal(raw.includes('NEVER-PERSIST'),false);assert.equal(raw.includes('DO-NOT-EXPORT'),false);
      }
    }
    checks.push('upstream Key excluded from browser and server drafts across real process restart');
    await page.screenshot({path:path.join(out,'recovered-upstream.png'),fullPage:true});assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks,server_processes:pids.length,distinct_server_instances:instances.length,pids,page_errors:errors,external_requests:external,paid_creates:0,existing_8765_touched:false},null,2));
    console.log(JSON.stringify({ok:true,checks,server_processes:pids.length,out}));
  }finally{if(browser)await browser.close();await stop();fs.writeFileSync(path.join(out,'last-server.log'),output)}
})().catch(e=>{console.error(e);process.exitCode=1});
