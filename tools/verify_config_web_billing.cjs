// Synthetic Web transactions and delayed local responses only; never generation.
const {chromium}=require(process.env.VC_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
(async()=>{
  const origin=process.env.VC_WEB_TEST_ORIGIN||'http://127.0.0.1:18787';
  const fixture=path.resolve(process.env.VC_WEB_FIXTURE_DIR||path.join(__dirname,'../_local/web-m1-20261113'));
  const out=path.join(fixture,'billing-explanations');fs.mkdirSync(out,{recursive:true});
  const digest=()=>crypto.createHash('sha256').update(fs.readFileSync(path.join(fixture,'config.json'))).digest('hex');
  const browser=await chromium.launch({headless:true,executablePath:process.env.VC_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  await page.route('**/*',r=>{if(r.request().url().startsWith(origin+'/'))return r.continue();external.push(r.request().url());return r.abort()});
  async function api(route,body){return page.evaluate(async ({route,body})=>{
    const headers={'X-VC-Client':'1'};
    if(body!==undefined){const s=await(await fetch('/api/session',{headers})).json();headers['Content-Type']='application/json';headers['X-VC-CSRF']=s.csrf_token}
    const response=await fetch('/api/'+route,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw new Error(JSON.stringify(result));return result;
  },{route,body})}
  async function price(id,pricing){const c=await api('catalog'),p=await api('changes/preview',{operation:'binding.update',id,values:{pricing},expected_token:c.summary.token});await api('changes/commit',{preview_token:p.preview_token})}
  async function compare(){await page.getByRole('button',{name:'比较所选接入',exact:true}).click();await page.locator('.comparison-grid article').first().waitFor();assert.equal(await page.locator('.comparison-grid article').count(),2)}
  async function delayed(route,action,edit){
    let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);
    await page.route('**/api/'+route,async r=>{const response=await r.fetch();seen();await gate;await r.fulfill({response})},{times:1});
    const done=page.waitForResponse(r=>r.url()===origin+'/api/'+route);
    await action();await started;await edit();release();await done;
    await page.getByRole('button',{name:'比较所选接入',exact:true}).waitFor();
    await page.waitForFunction(()=>![...document.querySelectorAll('button')].find(b=>b.textContent==='按任务筛选')?.disabled);
  }
  try{
    await page.goto(origin);await page.getByRole('table',{name:'模型列表'}).waitFor();
    const catalog=await api('catalog'),videos=catalog.bindings.filter(b=>b.kind==='video'&&b.adapter!=='unconfigured').slice(0,2),images=catalog.bindings.filter(b=>b.kind==='image'&&b.adapter!=='unconfigured').slice(0,2);
    assert.equal(videos.length,2);assert.equal(images.length,2);
    await price(videos[0].id,{currency:'USD',status:'confirmed',per_request:1,per_second:.22,minimum_seconds:7,round_seconds:5});
    await price(videos[1].id,{currency:'USD',status:'confirmed',tiers:[{when:{},per_request:2},{when:{resolution:'720p'},per_request:3}]});
    await price(images[0].id,{currency:'USD',per_image:.04});await price(images[1].id,{currency:'USD',per_image:.08,status:'unverified'});
    await page.reload();await page.getByRole('table',{name:'模型列表'}).waitFor();await page.getByRole('button',{name:'模型目录',exact:true}).click();
    await page.getByRole('searchbox',{name:'搜索模型'}).fill(images[0].remote_model);
    await page.locator('tbody tr').filter({hasText:images[0].upstream_name}).first().click();
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();let model=page.getByRole('dialog');
    await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    let budget=model.locator('.contract-group').nth(3);await budget.locator('summary').click();
    const enter=async (name,value)=>{const input=budget.getByLabel(name,{exact:true});await input.fill(value);await input.press('Tab')};
    assert.equal(await budget.getByLabel('预算每张价格（仅图片）',{exact:true}).inputValue(),'0.04');
    await enter('预算每请求价格','0.01');await budget.getByRole('button',{name:'添加价格档位',exact:true}).click();
    await enter('档位 1 操作','text-to-image');await enter('档位 1 每张价格（仅图片）','0.06');await enter('档位 1 每请求价格','0.02');
    const pending=JSON.parse(await model.getByLabel('预算价格、条件档位和计费规则',{exact:true}).inputValue());
    assert.equal(pending.per_image,.04);assert.equal(pending.tiers[0].per_image,.06);
    assert.match(await budget.innerText(),/省略数量时保持未知/);
    const committed=page.waitForResponse(r=>r.url()===origin+'/api/changes/commit');await model.getByRole('button',{name:'保存模型资料',exact:true}).click();assert.equal((await committed).status(),200);await model.waitFor({state:'hidden'});
    await page.getByRole('button',{name:'编辑资料与价格',exact:true}).click();model=page.getByRole('dialog');await model.getByText('按明确文档维护协议、参数与报价（可选）',{exact:true}).click();
    budget=model.locator('.contract-group').nth(3);await budget.locator('summary').click();
    assert.equal(await budget.getByLabel('预算每张价格（仅图片）',{exact:true}).inputValue(),'0.04');
    assert.equal(await budget.getByLabel('档位 1 每张价格（仅图片）',{exact:true}).inputValue(),'0.06');
    await model.getByRole('button',{name:'取消',exact:true}).click();
    const before=digest();await page.reload();await page.getByRole('table',{name:'模型列表'}).waitFor();await page.getByRole('button',{name:'模型目录',exact:true}).click();
    await page.getByText('按任务条件筛选与比较（可选）',{exact:true}).click();
    for(const video of videos)await page.locator('.comparison-picker input').evaluateAll((els,id)=>els.find(e=>e.value===id).click(),video.id);
    await page.getByRole('spinbutton',{name:'任务秒数',exact:true}).fill('6');await compare();
    const cards=page.locator('.comparison-grid');assert.match(await cards.innerText(),/USD 3\.2/);assert.match(await cards.innerText(),/0\.22\/秒 × 10 计费秒/);assert.match(await cards.innerText(),/多个价格档位同时匹配/);
    const tierStates=[];
    for(const [resolution,expected] of [['','missing-context'],['1080p','unique'],['720p','overlap']]){
      await page.getByRole('textbox',{name:'任务分辨率',exact:true}).fill(resolution);await compare();
      const fields=await cards.locator('article').nth(1).locator('dl').evaluate(el=>Object.fromEntries(
        [...el.querySelectorAll('dt')].map(node=>[node.textContent,node.nextElementSibling.textContent])));
      if(expected==='unique')assert.equal(fields['本次估算（非实付）'],'USD 2');
      else assert.equal(fields['本次估算（非实付）'],'未知，不能用于硬预算');
      assert.match(fields['本次计费说明'],expected==='missing-context'?/缺少匹配档位所需参数：分辨率/:expected==='overlap'?/多个价格档位同时匹配/:/使用第 1 档/);
      tierStates.push({resolution,state:expected,estimate:fields['本次估算（非实付）'],explanation:fields['本次计费说明']});
      if(expected==='missing-context'){
        await page.getByRole('button',{name:'按任务筛选',exact:true}).click();await page.locator('.fit-results p').first().waitFor();
        assert.match(await page.locator('.fit-results').innerText(),/计费：缺少匹配档位所需参数：分辨率/);
      }
    }
    await page.getByRole('spinbutton',{name:'任务秒数',exact:true}).fill('11');assert.equal(await page.locator('.comparison-grid article').count(),0);
    await delayed('catalog/compare',()=>page.getByRole('button',{name:'比较所选接入',exact:true}).click(),()=>page.getByRole('spinbutton',{name:'任务秒数',exact:true}).fill('8'));
    assert.equal(await page.locator('.comparison-grid article').count(),0,'Late comparison must not resurrect old inputs');
    await compare();await page.locator('.comparison-picker input:checked').first().uncheck();assert.equal(await page.locator('.comparison-grid article').count(),0);
    await page.getByRole('button',{name:'按任务筛选',exact:true}).click();await page.locator('.fit-results p').first().waitFor();
    assert.match(await page.locator('.fit-results').innerText(),/计费：/);
    await delayed('catalog/filter',()=>page.getByRole('button',{name:'按任务筛选',exact:true}).click(),()=>page.getByRole('spinbutton',{name:'任务秒数',exact:true}).fill('7'));
    assert.equal(await page.locator('.fit-results p').count(),0,'Late filter must not resurrect old inputs');
    await page.getByRole('combobox',{name:'任务操作',exact:true}).selectOption('text-to-image');assert.equal(await page.getByRole('spinbutton',{name:'任务秒数',exact:true}).count(),0);
    for(const checkbox of await page.locator('.comparison-picker input:checked').all())await checkbox.uncheck();
    for(const picture of images)await page.locator('.comparison-picker input').evaluateAll((els,id)=>els.find(e=>e.value===id).click(),picture.id);
    await compare();assert.match(await cards.innerText(),/USD 0\.08/);assert.match(await cards.innerText(),/0\.02\/次 \+ 0\.06\/张 × 1 请求出图张数/);assert.match(await cards.innerText(),/预算价格尚未核实/);
    await page.getByRole('button',{name:'按任务筛选',exact:true}).click();await page.locator('.fit-results p').first().waitFor();
    assert.match(await page.locator('.fit-results').innerText(),/0\.06\/张 × 1 请求出图张数/);
    assert.equal(await page.getByRole('alert').count(),0);await page.screenshot({path:path.join(out,'image-comparison.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'image-comparison-mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.equal(digest(),before);
    const current=await api('catalog'),item=current.bindings.find(b=>b.id===images[0].id);
    const preview=await api('changes/preview',{operation:'binding.update',id:item.id,values:{adapter_options:{...item.adapter_options,image_request_fields:[]}},expected_token:current.summary.token});await api('changes/commit',{preview_token:preview.preview_token});
    const omittedBefore=digest(),omitted=await api('catalog/compare',{bindings:images.map(i=>i.id),scenario:{operation:'text-to-image'}}),fit=await api('catalog/filter',{scenario:{operation:'text-to-image'}});
    assert.equal(omitted.cards[0].fields['本次估算（非实付）'],'未知，不能用于硬预算');assert.match(omitted.cards[0].fields['本次计费说明'],/不能按供应商默认值估价/);
    assert.equal(fit.rows.find(r=>r.id===item.id).fit.quote.calculation.reason,'image_count_unknown');assert.equal(digest(),omittedBefore);
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    const result={ok:true,checks:['exact additive minimum/rounding formula','ambiguous tiers remain unknown','general tier cannot hide unresolved possible overlap in comparison/filter','explicit nonmatching context yields unique rate; matching context yields overlap','scenario and selected-bindings invalidate old results','delayed comparison/filter cannot resurrect old inputs','structured per-image base/tier fields save and reopen intact','image tiers replace base rates and add requested-count and request fees','omitted transmitted n remains unknown in compare/filter','image comparison omits video duration','unverified price reason visible','390px no overflow','all inspection actions leave configuration unchanged'],tier_states:tierStates,image_pricing:{base:.04,tier:.06,per_request:.02,requested_images:1,estimate:.08,omitted_n:'unknown',actual_payment:'unknown'},page_errors:errors,external_requests:external,paid_creates:0};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(e){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({alerts:await page.getByRole('alert').allTextContents(),errors},null,2));throw e}
  finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
