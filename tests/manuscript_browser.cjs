const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {execFileSync}=require('node:child_process');
(async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'manuscript-browser-'));
  let browser;
  try {
    execFileSync('python3',[path.join(__dirname,'manuscript_browser_fixture.py'),dir]);
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
    await page.goto(pathToFileURL(path.join(dir,'bundle/manuscript.html')).href);
    assert.equal(await page.locator('img,svg,iframe,script').count(),0);
    assert.equal(await page.evaluate(()=>window.pwned),undefined);
    assert.equal(await page.locator('.uncited').count(),2);
    const manifest=JSON.parse(fs.readFileSync(path.join(dir,'bundle/manifest.json')));
    assert.deepEqual(await page.locator('article[id^="claim-"] > .authored').allTextContents(),
      manifest.sections.flatMap(s=>s.claims.map(c=>c.text)));
    assert.deepEqual(await page.locator('section[id^="section-"] > h2').allTextContents(),
      manifest.sections.map(s=>s.heading));
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Skip to manuscript');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'manuscript');
    const link=page.locator('a[href="#citation-q2"]').first();
    await link.focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'citation-q2');
    await page.locator('#citation-q2 summary').focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('#citation-q2 mark').isVisible(),true);
    assert.match(await page.locator('#citation-q2 mark').textContent(),/<img/);
    await page.locator('#citation-q2 a[href="#source-v2"]').focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'source-v2');
    await page.locator('#source-v2 summary').focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('#source-v2 pre').isVisible(),true);
    const back=page.locator('#citation-q2 a[href^="#claim-"]');
    const anchor=(await back.first().getAttribute('href')).slice(1);
    await back.first().focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),anchor);
    for(const href of await page.locator('a').evaluateAll(links=>links.map(a=>a.getAttribute('href')))) {
      assert(href.startsWith('#'));
      assert.equal(await page.locator(href).count(),1);
    }
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const nojs=await browser.newContext({offline:true,javaScriptEnabled:false});
    const staticPage=await nojs.newPage();
    await staticPage.goto(pathToFileURL(path.join(dir,'bundle/manuscript.html')).href);
    assert.equal(await staticPage.locator('.quote').count(),3);
    assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);assert.deepEqual(dialogs,[]);
    console.log(JSON.stringify({browser:await browser.version(),http_requests:requests.length,hostile_script_executions:dialogs.length,
      scenarios:['ordered claims','explicit uncited labels','skip link','keyboard citation and return','excerpt expansion','snapshot navigation',
        'all fragment targets','390px viewport','hostile markup escaping','JavaScript-disabled reading']}));
  } finally {if(browser) await browser.close();fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
