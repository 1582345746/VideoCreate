// Typed media contract editing through the parent model form. Synthetic config
// only: no file upload, reference URL, upstream call or paid generation.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const origin=process.env.VC_WEB_TEST_ORIGIN||'http://127.0.0.1:18787';
const root=path.resolve(process.env.VC_WEB_FIXTURE_DIR||path.join(__dirname,'../_local/web-m1-20261113')),out=path.join(root,'typed-references');
const digest=()=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'config.json'))).digest('hex');
(async()=>{
  fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[],commits=[],checks=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  page.on('request',r=>{if(r.url()===origin+'/api/changes/commit')commits.push(r.method())});
  await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
  async function api(route,body){return page.evaluate(async({route,body})=>{const s=await(await fetch('/api/session',{headers:{'X-VC-Client':'1'}})).json();const r=await fetch('/api/'+route,{method:body===undefined?'GET':'POST',headers:{'X-VC-Client':'1',...(body===undefined?{}:{'X-VC-CSRF':s.csrf_token,'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});return{status:r.status,data:await r.json()}},{route,body})}
  async function enter(label,value){const input=page.getByRole('dialog').getByLabel(label,{exact:true});await input.fill(String(value));await input.press('Tab')}
  async function open(){await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();const model=page.getByRole('dialog');await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();await model.locator('.contract-group').nth(1).locator('summary').first().click();return model}
  async function commit(model){const done=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await done).status(),200);await model.waitFor({state:'hidden'})}
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();await page.getByRole('button',{name:'模型目录',exact:true}).click();const before=(await api('catalog')).data;
    const original=before.bindings.find(b=>b.kind==='video'&&b.default_eligible);assert.ok(original);
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(original.remote_model);await page.locator('tbody tr').filter({hasText:original.upstream_name}).first().click();let model=await open();const initial=digest();
    const existing=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());assert.equal(existing.media_reference_limits,undefined);
    await model.getByRole('button',{name:'填写明确的多媒体参考合同',exact:true}).click();
    let raw=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());assert.equal(raw.media_reference_limits.maximum_total_count,undefined);assert.equal(raw.media_reference_limits.audio_reference_with_generated_audio,undefined);
    for(const [key,value] of [['三类参考总数量上限',6],['三类参考总字节上限',15000000],['URL 至少剩余有效秒数',120]])await enter(key,value);
    await model.getByRole('combobox',{name:'音频参考与生成声音并用',exact:true}).selectOption('false');
    await model.getByRole('checkbox',{name:'允许组合：图片',exact:true}).check();await model.getByRole('checkbox',{name:'允许组合：图片 + 视频 + 音频',exact:true}).check();
    const values={
      '图片':{'最多文件数':2,'单文件字节上限':2000000,'同类总字节上限':4000000,'最大宽度（像素）':1920,'最大高度（像素）':1080,' MIME 类型':'image/png, image/jpeg'},
      '视频':{'最多文件数':2,'单文件字节上限':4000000,'同类总字节上限':8000000,'单文件最长秒数':5,'同类总时长上限':10,'最大宽度（像素）':1920,'最大高度（像素）':1080,' MIME 类型':'video/mp4'},
      '音频':{'最多文件数':2,'单文件字节上限':1000000,'同类总字节上限':2000000,'单文件最长秒数':5,'同类总时长上限':10,'最高采样率（Hz）':48000,'最多声道数':2,' MIME 类型':'audio/wav'}
    };
    for(const [kind,fields] of Object.entries(values))for(const [field,value] of Object.entries(fields))await enter(kind+'参考'+field,value);
    for(const name of ['图片参考角色：首帧','图片参考角色：角色身份','视频参考角色：动作','音频参考角色：声音'])await model.getByRole('checkbox',{name,exact:true}).check();
    await model.getByRole('button',{name:'添加执行条件',exact:true}).click();await model.getByRole('combobox',{name:'执行条件 1 操作',exact:true}).selectOption('reference-to-video');await enter('执行条件 1 分辨率','720p');await enter('执行条件 1 最长秒数',8);
    await model.getByRole('button',{name:'添加执行条件',exact:true}).click();await model.getByRole('group',{name:'执行条件 2',exact:true}).getByRole('button',{name:'删除此执行条件',exact:true}).click();
    raw=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());for(const [key,value] of Object.entries(existing))assert.deepEqual(raw[key],value);
    assert.equal(raw.media_reference_limits.audio_reference_with_generated_audio,false);assert.equal(raw.media_reference_limits.video.maximum_duration_seconds,5);assert.deepEqual(raw.media_reference_limits.audio.roles,['sound']);
    assert.equal(digest(),initial);assert.equal(commits.length,0);checks.push('Required contract values start unknown; structured counts/bytes/MIME/roles/combinations/durations preserve other capabilities without child writes');
    // Contract fields alone cannot grant the wrong adapter reference semantics.
    const refusal=page.waitForResponse(r=>r.url()===origin+'/api/changes/preview');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await refusal).status(),422);assert.equal(digest(),initial);assert.equal(commits.length,0);
    await model.getByRole('combobox',{name:'协议',exact:true}).selectOption('xingapi-video-v2');await model.getByRole('checkbox',{name:'reference-to-video',exact:true}).check();
    await commit(model);const saved=(await api('catalog')).data.bindings.find(b=>b.id===original.id);assert.equal(saved.adapter,'xingapi-video-v2');assert.deepEqual(saved.capability_overrides.media_reference_limits,raw.media_reference_limits);
    checks.push('Shared core refuses limits on incompatible adapter; one parent save persists exact typed contract and operation');
    const fit=await api('catalog/filter',{scenario:{operation:'reference-to-video',seconds:5,resolution:'720p',reference_counts:{image:1,video:1,audio:1}}});assert.equal(fit.status,200);const row=fit.data.rows.find(r=>r.id===original.id);assert.equal(row.fit.matches,true,JSON.stringify(row));assert.equal(row.fit.ready_to_create,false);
    for(const scenario of [{seconds:10,reference_counts:{image:1,video:1,audio:1}}, {seconds:5,reference_counts:{image:3}}, {seconds:5,reference_counts:{video:1}}, {seconds:5,reference_counts:{image:1,video:1,audio:1},generate_audio:true}]) {
      const result=await api('catalog/filter',{scenario:{operation:'reference-to-video',resolution:'720p',...scenario}});assert.equal(result.status,200);assert.equal(result.data.rows.find(r=>r.id===original.id).fit.matches,false,JSON.stringify(scenario));
    }
    checks.push('Structured condition add/remove persists; offline filter consumes duration/count/combination/audio constraints without granting creation');
    // Test clear/remove and malformed JSON boundaries on the real parent form.
    model=await open();const beforeEdit=digest();
    await enter('音频参考最多声道数','');const cleared=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());assert.equal('maximum_channels' in cleared.media_reference_limits.audio,false);assert.equal(cleared.media_reference_limits.audio.maximum_sample_rate,48000);
    await model.getByRole('button',{name:'音频 MIME 与角色设为空列表',exact:true}).click();const unsupported=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());assert.deepEqual(unsupported.media_reference_limits.audio.roles,[]);assert.deepEqual(unsupported.media_reference_limits.audio.mime_types,[]);
    const emptyRefusal=page.waitForResponse(r=>r.url()===origin+'/api/changes/preview');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await emptyRefusal).status(),422);assert.equal(digest(),beforeEdit);
    await model.getByLabel('可执行参数约束',{exact:true}).fill('{"media_reference_limits":');await model.getByRole('alert').filter({hasText:'此组 JSON 尚不完整'}).waitFor();assert.equal(await model.getByRole('button',{name:'移除参考约束，恢复未知',exact:true}).count(),0);assert.equal(await model.getByLabel('可执行参数约束',{exact:true}).inputValue(),'{"media_reference_limits":');
    await model.getByLabel('可执行参数约束',{exact:true}).fill(JSON.stringify(saved.capability_overrides));await model.getByRole('button',{name:'移除参考约束，恢复未知',exact:true}).click();const removed=JSON.parse(await model.getByLabel('可执行参数约束',{exact:true}).inputValue());assert.equal(removed.media_reference_limits,undefined);for(const [key,value] of Object.entries(existing))assert.deepEqual(removed[key],value);
    const removeRefusal=page.waitForResponse(r=>r.url()===origin+'/api/changes/preview');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await removeRefusal).status(),422);assert.equal(digest(),beforeEdit);
    checks.push('Clearing optional values restores unknown; empty active roles/MIME and removing enabled reference limits are refused; malformed JSON is retained');
    await model.getByLabel('可执行参数约束',{exact:true}).fill(JSON.stringify(saved.capability_overrides));await page.setViewportSize({width:390,height:844});await model.getByRole('combobox',{name:'音频参考与生成声音并用',exact:true}).scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,'typed-references-mobile.png'),fullPage:true});await model.getByRole('checkbox',{name:'视频参考角色：动作',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'typed-video-mobile.png'),fullPage:true});
    assert.equal(commits.length,1);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks,parent_saves:commits.length,page_errors:errors,external_requests:external,paid_creates:0},null,2));console.log(JSON.stringify({ok:true,checks}));
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
