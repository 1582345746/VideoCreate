// Real Chromium zoom through chrome://settings in a fresh isolated profile.
// Browser DPR must prove the requested zoom was applied before any assertion.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const origin=process.env.VC_WEB_TEST_ORIGIN||'http://127.0.0.1:18787',root=path.resolve(process.env.VC_WEB_FIXTURE_DIR||path.join(__dirname,'../_local/web-m1-20261113')),out=path.join(root,'browser-zoom');
const hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
(async()=>{
  fs.mkdirSync(out,{recursive:true});const before=hash(fs.readFileSync(path.join(root,'config.json'))),results=[],errors=[],external=[];
  for(const zoom of [1,1.25,1.5,1.75,2]){
    const profile=path.join(out,'profile-'+zoom);
    const context=await chromium.launchPersistentContext(profile,{headless:true,viewport:null,args:['--force-device-scale-factor=1','--window-size=1440,1000'],executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    await context.route('**/*',r=>{if(r.request().url().startsWith(origin+'/')||r.request().url().startsWith('chrome://'))return r.continue();external.push(r.request().url());return r.abort()});
    try {
    const settings=await context.newPage();await settings.goto('chrome://settings/appearance');
    await settings.evaluate(zoom=>new Promise((resolve,reject)=>chrome.settingsPrivate.setDefaultZoom(zoom,()=>chrome.runtime.lastError?reject(Error(chrome.runtime.lastError.message)):resolve())),zoom);
    assert.ok(Math.abs(await settings.evaluate(()=>new Promise(resolve=>chrome.settingsPrivate.getDefaultZoom(resolve)))-zoom)<1e-9);await settings.close();
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
    async function capture(name) {
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const cdp=await context.newCDPSession(page),shot=await cdp.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});await cdp.detach();
      const bytes=Buffer.from(shot.data,'base64');assert.ok(bytes.length>5000,'Screenshot must contain the painted form');fs.writeFileSync(path.join(out,name),bytes);
    }
    async function actionFits(model,label) {
      const visible=await model.getByRole('button',{name:label,exact:true}).evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth&&el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});
      assert.equal(visible,true,label+' must fit and receive clicks at zoom '+zoom);
    }
      await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
      const metrics=await page.evaluate(()=>({dpr:devicePixelRatio,inner:innerWidth,outer:outerWidth,height:innerHeight}));assert.ok(Math.abs(metrics.dpr-zoom)<.02,JSON.stringify({zoom,metrics}));assert.equal(metrics.outer,1440);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      for(const name of ['模型目录','默认选择','检查与记录','设置','上游管理']){
        await page.getByRole('button',{name,exact:true}).click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,name+' zoom '+zoom);
      }
      const add=page.getByRole('button',{name:'＋ 添加上游',exact:true});await add.focus();await page.keyboard.press('Enter');const dialog=page.getByRole('dialog');await dialog.waitFor();assert.equal(await dialog.getByLabel('API 地址（URL）').evaluate(el=>el===document.activeElement),true);
      await page.getByText('名称与备注（可选）',{exact:true}).click();await dialog.getByLabel('备注',{exact:true}).fill('浏览器缩放下的长中文备注。'.repeat(100));
      const bounds=await dialog.boundingBox();assert.ok(bounds.x>=0&&bounds.width<=metrics.inner&&bounds.y>=0&&bounds.height<=metrics.height,JSON.stringify({zoom,bounds,metrics}));
      assert.equal(await dialog.getByRole('button',{name:'保存上游',exact:true}).isVisible(),true);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await actionFits(dialog,'保存上游');await actionFits(dialog,'取消');
      await capture('upstream-zoom-'+zoom+'.png');await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await add.evaluate(el=>el===document.activeElement),true);
      await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();const model=page.getByRole('dialog');await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();await model.locator('.contract-group').nth(1).locator('summary').first().click();await model.getByRole('button',{name:'填写明确的多媒体参考合同',exact:true}).scrollIntoViewIfNeeded();
      const modelBounds=await model.boundingBox();assert.ok(modelBounds.width<=metrics.inner&&modelBounds.height<=metrics.height);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await actionFits(model,'保存模型资料');await actionFits(model,'取消');await capture('model-zoom-'+zoom+'.png');
      await page.keyboard.press('Escape');await model.waitFor({state:'hidden'});await page.getByRole('button',{name:'编辑资料与价格',exact:true}).waitFor();
      results.push({zoom,metrics,navigation_pages:5,keyboard_focus_return:true,upstream_and_model_dialogs_fit:true});
    }finally{await context.close()}
  }
  assert.equal(hash(fs.readFileSync(path.join(root,'config.json'))),before);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,method:'Isolated Chrome settingsPrivate.setDefaultZoom plus getDefaultZoom and actual DPR verification; physical window 1440x1000, viewport:null; no CSS/device emulation',results,page_errors:errors,external_requests:external,configuration_unchanged:true,paid_creates:0,human_screen_reader:'not-performed'},null,2));console.log(JSON.stringify({ok:true,zooms:results.map(r=>r.zoom)}));
})().catch(e=>{console.error(e);process.exitCode=1});
