// Synthetic configuration only. Hold real local responses across user input.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const origin=process.env.VC_WEB_TEST_ORIGIN,root=process.env.VC_WEB_FIXTURE_DIR;
assert.ok(origin&&root,'Run through verify_config_web_browser_suite.py');
const out=path.join(root,'save-lock');fs.mkdirSync(out);
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const results=[],pageErrors=[],external=[];let page,context,held=[],holdAt='',holdError=false,previews=0,commits=0;
  async function settle(){await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))}
  async function open(){
    held=[];holdAt='';holdError=false;previews=0;commits=0;
    context=await browser.newContext({viewport:{width:1440,height:1000}});page=await context.newPage();page.setDefaultTimeout(7000);
    page.on('pageerror',e=>pageErrors.push(e.message));page.on('dialog',d=>d.accept());
    await page.route('**/*',async route=>{
      const req=route.request(),url=req.url();
      if(!url.startsWith(origin+'/')){external.push(url);return route.abort()}
      if(url.endsWith('/api/catalog/check'))throw new Error('No upstream checks permitted');
      if(url.endsWith('/api/changes/preview'))previews++;
      if(url.endsWith('/api/changes/commit'))commits++;
      if(url===origin+'/api/changes/'+holdAt){
        const response=holdError?null:await route.fetch();
        let release;const gate=new Promise(r=>release=r),item={release,response,operation:req.postDataJSON().operation};
        item.done=gate.then(()=>holdError?route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({error:{message:'合成保存失败，请检查输入。'}})}):route.fulfill({response}));
        held.push(item);return item.done;
      }
      return route.continue();
    });
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
  }
  async function waiting(count=1){
    const end=Date.now()+2500;
    while(held.length<count&&Date.now()<end)await new Promise(r=>setTimeout(r,20));
    assert.ok(held.length>=count,'Expected held local response');await settle();return held[count-1];
  }
  async function releaseAll(){
    holdAt='';for(const item of held)item.release();await Promise.allSettled(held.map(i=>i.done));await settle();
  }
  async function check(name,run){
    let detail={};
    try{await open();detail=await run()||{};results.push({name,ok:true,...detail})}
    catch(e){results.push({name,ok:false,error:e.message,...(e.observed||{})});await page.screenshot({path:path.join(out,'failure-'+results.length+'.png'),fullPage:true})}
    finally{await releaseAll();await page.waitForTimeout(250);await context.close()}
  }
  async function newUpstream(){
    await page.getByRole('button',{name:/添加上游/}).click();
    const d=page.getByRole('dialog');
    const url='https://save-lock-'+Date.now()+'.invalid/v1';
    await d.getByLabel('API 地址（URL）').fill(url);await d.getByLabel('API 密钥（Key）').fill('synthetic-save-lock-key');
    await d.getByText('名称与备注（可选）',{exact:true}).click();
    await d.getByLabel('显示名称',{exact:true}).fill('提交时的上游名称');
    await d.getByLabel('备注',{exact:true}).fill('提交时的非秘密备注');return {d,url};
  }
  function config(){return JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8'))}
  try{
    await check('upstream preview freezes inputs until the committed result is handled',async()=>{
      const {d,url}=await newUpstream();holdAt='preview';await d.getByRole('button',{name:'保存上游',exact:true}).click();await waiting();
      const name=d.getByLabel('显示名称',{exact:true}),locked=await name.isDisabled();
      if(!locked){
        await name.fill('保存中后来输入但会丢失的名称');await releaseAll();await d.waitFor({state:'hidden'});
        const saved=Object.values(config().upstreams).find(u=>u.base_url===url);
        const e=new Error('Upstream fields remained editable while save was pending');
        e.observed={later_input_lost:saved.display_name==='提交时的上游名称',actual_saved_name:saved.display_name};throw e;
      }
      assert.ok(await d.getByLabel('API 地址（URL）').isDisabled());assert.ok(await d.getByLabel('API 密钥（Key）').isDisabled());
      assert.ok(await d.getByLabel('备注',{exact:true}).isDisabled());assert.ok(await d.getByRole('button',{name:'取消',exact:true}).isDisabled());
      await releaseAll();await d.waitFor({state:'hidden'});assert.equal(previews,1);assert.equal(commits,1);
      await page.waitForFunction(()=>document.activeElement===document.querySelector('[data-upstream-action="create"]'));
      assert.equal(Object.values(config().upstreams).find(u=>u.base_url===url).display_name,'提交时的上游名称');
      return {fields_locked:true,preview_requests:previews,commit_requests:commits};
    });
    await check('model metadata and advanced native controls freeze while commit response is delayed',async()=>{
      await page.getByRole('button',{name:'模型目录',exact:true}).click();await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
      const d=page.getByRole('dialog');await d.getByLabel('备注',{exact:true}).fill('提交时的模型备注');
      holdAt='commit';await d.getByRole('button',{name:'保存模型资料',exact:true}).click();await waiting();
      const notes=d.getByLabel('备注',{exact:true}),locked=await notes.isDisabled();
      if(!locked){
        await notes.fill('保存中后来输入但会丢失的模型备注');await releaseAll();await d.waitFor({state:'hidden'});
        const e=new Error('Model fields remained editable after server commit');e.observed={later_input_lost:true};throw e;
      }
      assert.equal(await d.locator('input,textarea,select,button').evaluateAll(els=>els.filter(el=>!el.matches(':disabled')).length),0);
      await releaseAll();await d.waitFor({state:'hidden'});assert.equal(previews,1);assert.equal(commits,1);
      await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();
      assert.equal(await page.getByRole('dialog').getByLabel('备注',{exact:true}).inputValue(),'提交时的模型备注');
      return {native_controls_locked:true,reopened_value_matches:true};
    });
    await check('defaults cannot change or navigate away during preview and save',async()=>{
      await page.getByRole('button',{name:'默认选择',exact:true}).click();
      const image=page.getByRole('combobox',{name:'图片默认接入',exact:true}),video=page.getByRole('combobox',{name:'视频默认接入',exact:true});
      await image.selectOption('');await page.getByRole('combobox',{name:'图片默认策略',exact:true}).selectOption('ask');
      const options=await video.locator('option').evaluateAll(els=>els.filter(e=>e.value&&!e.disabled).map(e=>e.value));assert.ok(options.length);
      await video.selectOption(options[0]);const policy=page.getByRole('combobox',{name:'视频默认策略',exact:true});await policy.selectOption('use-default');
      holdAt='preview';await page.getByRole('button',{name:'保存默认选择',exact:true}).click();await waiting();
      const locked=await policy.isDisabled();
      if(!locked){
        await policy.selectOption('ask');await releaseAll();await page.getByText('图片和视频的默认策略已保存。',{exact:true}).waitFor();
        const e=new Error('Default fields remained editable during save');e.observed={later_input_lost:(await policy.inputValue())==='use-default'};throw e;
      }
      assert.ok(await image.isDisabled());assert.ok(await video.isDisabled());assert.ok(await page.getByRole('button',{name:'设置',exact:true}).isDisabled());
      await releaseAll();await page.getByText('图片和视频的默认策略已保存。',{exact:true}).waitFor();
      assert.ok(await policy.isEnabled());assert.ok(await page.getByRole('button',{name:'设置',exact:true}).isEnabled());
      await policy.selectOption('ask');assert.equal(await policy.inputValue(),'ask');return {inputs_and_navigation_locked:true,editing_resumes:true};
    });
    await check('backup restore freezes the submitted choice and navigation',async()=>{
      await page.getByRole('button',{name:'设置',exact:true}).click();const choice=page.getByRole('combobox',{name:'配置备份',exact:true});
      await choice.locator('option').nth(1).waitFor({state:'attached'});const id=await choice.locator('option').nth(1).getAttribute('value');await choice.selectOption(id);
      holdAt='preview';await page.getByRole('button',{name:'恢复所选备份',exact:true}).click();await waiting();
      assert.ok(await choice.isDisabled(),'Backup choice remained editable during restore');
      assert.ok(await page.getByRole('button',{name:'刷新备份列表',exact:true}).isDisabled());
      assert.ok(await page.getByRole('button',{name:'默认选择',exact:true}).isDisabled());
      await releaseAll();await page.getByText('配置已恢复，原始备份与旧凭据版本继续保留。',{exact:true}).waitFor();
      await page.waitForFunction(()=>!document.querySelector('select[aria-label="配置备份"]').matches(':disabled'));
      assert.ok(await choice.isEnabled());return {choice_and_navigation_locked:true};
    });
    await check('failed upstream save unlocks controls and preserves nonsecret fields for retry',async()=>{
      const {d,url}=await newUpstream();holdAt='preview';holdError=true;
      await d.getByRole('button',{name:'保存上游',exact:true}).click();await waiting();
      assert.ok(await d.getByLabel('显示名称',{exact:true}).isDisabled());
      await releaseAll();await d.getByRole('alert').waitFor();holdError=false;
      assert.equal(await d.getByLabel('API 地址（URL）').inputValue(),url);
      assert.equal(await d.getByLabel('显示名称',{exact:true}).inputValue(),'提交时的上游名称');
      assert.equal(await d.getByLabel('备注',{exact:true}).inputValue(),'提交时的非秘密备注');
      assert.equal(await d.getByLabel('API 密钥（Key）').inputValue(),'');assert.ok(await d.getByLabel('显示名称',{exact:true}).isEnabled());
      await d.getByLabel('显示名称',{exact:true}).fill('失败后明确修改并重试');await d.getByLabel('API 密钥（Key）').fill('synthetic-retry-key');
      await d.getByRole('button',{name:'保存上游',exact:true}).click();await d.waitFor({state:'hidden'});
      assert.equal(Object.values(config().upstreams).find(u=>u.base_url===url).display_name,'失败后明确修改并重试');
      return {nonsecret_fields_preserved:true,key_not_retained:true,retry_passed:true};
    });
    await check('same-page duplicate action is reserved before preview returns',async()=>{
      holdAt='preview';const archive=page.getByRole('button',{name:'归档',exact:true});
      await archive.evaluate(el=>{el.click();el.click()});await waiting();await page.waitForTimeout(150);
      assert.equal(previews,1,'More than one preview started before the first response');assert.ok(await archive.isDisabled());
      await releaseAll();await page.getByRole('table',{name:'模型列表'}).waitFor();assert.equal(commits,1);return {preview_requests:previews,commit_requests:commits};
    });
    assert.deepEqual(pageErrors,[]);assert.deepEqual(external,[]);
  } finally{await browser.close()}
  const report={ok:results.every(r=>r.ok),cases:results,page_errors:pageErrors,external_requests:external,
    source:'real local preview/commit endpoints with delayed browser responses; synthetic configuration only',paid_creates:0};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  if(!report.ok)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
