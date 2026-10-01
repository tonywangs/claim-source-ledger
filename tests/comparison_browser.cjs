const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {execFileSync}=require('node:child_process');
(async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'comparison-browser-'));
  let browser;
  try {
    execFileSync('python3',[path.join(__dirname,'comparison_browser_fixture.py'),dir]);
    browser=await chromium.launch({headless:true,args:['--disable-background-networking']});
    const context=await browser.newContext({offline:true,serviceWorkers:'block'});
    const requests=[],errors=[],dialogs=[];
    await context.route('**/*',route=>{
      if(/^https?:/.test(route.request().url())) {requests.push(route.request().url());return route.abort();}
      return route.continue();
    });
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(String(e)));
    page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
    const url=pathToFileURL(path.join(dir,'comparison/comparison.html')).href;
    await page.goto(url);
    const report=JSON.parse(fs.readFileSync(path.join(dir,'comparison/comparison.json')));
    assert.equal(await page.locator('img,svg,iframe').count(),0);
    assert.equal(await page.locator('script').count(),1);
    assert.equal(await page.evaluate(()=>window.pwned),undefined);
    assert.equal(await page.locator('.finding').count(),report.findings.length);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Skip to findings');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'findings');
    for(const kind of Object.keys(report.summary)) {
      await page.selectOption('#filter',kind);
      assert.equal(await page.locator('.finding:visible').count(),report.summary[kind]);
      assert.equal(await page.locator('#count').textContent(),report.summary[kind]+' visible findings');
    }
    await page.locator('#filter').focus();await page.keyboard.press('Home');await page.keyboard.press('Enter');
    assert.equal(await page.locator('.finding:visible').count(),report.findings.length);
    for(const view of ['before','after','both']) {
      await page.selectOption('#view',view);
      for(const side of ['before','after']) {
        assert.equal(await page.locator('.finding .'+side+':visible').count(),view==='both'||view===side?report.findings.length:0);
      }
    }
    await page.selectOption('#filter','claim_text');
    const target=page.locator('.finding:visible .before .claim-text').first();
    assert.match(await target.textContent(),/<script>window.pwned/);
    const cite=page.locator('.finding:visible a[href^="#evidence-before-"]').first();
    const href=await cite.getAttribute('href');
    await cite.focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),href.slice(1));
    await page.locator(href+' summary').focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator(href+' mark').isVisible(),true);
    assert.match(await page.locator(href+' mark').textContent(),/exact 😀/);
    // Return to an earlier finding hidden by the current filter: navigation must reveal it.
    const back=page.locator(href+' a[href^="#finding-"]').first();
    const anchor=await back.getAttribute('href');
    await back.focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator(anchor).isVisible(),true);
    assert.equal(await page.evaluate(()=>document.activeElement.id),anchor.slice(1));
    for(const link of await page.locator('a').evaluateAll(as=>as.map(a=>a.getAttribute('href')))) {
      assert(link.startsWith('#'));assert.equal(await page.locator(link).count(),1);
    }
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const nojs=await browser.newContext({offline:true,javaScriptEnabled:false,serviceWorkers:'block'});
    const staticPage=await nojs.newPage();await staticPage.goto(url);
    assert.equal(await staticPage.locator('.finding:visible').count(),report.findings.length);
    assert.equal(await staticPage.locator('.finding .before:visible').count(),report.findings.length);
    assert.equal(await staticPage.locator('.finding .after:visible').count(),report.findings.length);
    assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);assert.deepEqual(dialogs,[]);
    console.log(JSON.stringify({browser:await browser.version(),http_requests:requests.length,hostile_script_executions:dialogs.length,
      findings:report.findings.length,filter_kinds:Object.keys(report.summary).length,
      scenarios:['all type filters','native keyboard filter','before/after views','skip link','keyboard citation navigation',
        'context expansion','return to filtered finding','all fragment targets','390px viewport','hostile markup escaping','script hash CSP','JavaScript-disabled reading']}));
  } finally {if(browser) await browser.close();fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
