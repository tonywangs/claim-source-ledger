const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'claimledger-browser-'));
  let browser;
  try {
    execFileSync('python3',[path.join(__dirname,'browser_fixture.py'), dir]);
    browser = await chromium.launch({headless:true, args:['--disable-background-networking']});
    const context = await browser.newContext({offline:true, serviceWorkers:'block'});
    const requests=[], errors=[], dialogs=[];
    await context.route('**/*', route => {
      if (/^https?:/.test(route.request().url())) {requests.push(route.request().url()); return route.abort();}
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror',err=>errors.push(String(err)));
    page.on('dialog',async dialog=>{dialogs.push(dialog.message()); await dialog.dismiss();});
    await page.goto(pathToFileURL(path.join(dir,'browser.html')).href);
    assert.equal(await page.locator('.claim:visible').count(),3);
    assert.equal(await page.locator('#count').textContent(),'3 of 3 claims shown');
    assert.equal(await page.locator('img,svg,iframe').count(),0);
    assert.equal(await page.evaluate(()=>window.pwned),undefined);
    await page.keyboard.press('/');
    assert.equal(await page.locator('#search').evaluate(el=>el===document.activeElement),true);
    await page.keyboard.type('harbor');
    assert.equal(await page.locator('.claim:visible').count(),1);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.claim:visible').count(),3);
    await page.selectOption('#source','s2');
    assert.equal(await page.locator('.claim:visible').count(),1);
    assert.equal(await page.locator('.claim:visible').getAttribute('id'),'claim-c2');
    await page.locator('#search').fill('harbor');
    assert.equal(await page.locator('.claim:visible').count(),0);
    await page.getByRole('button',{name:'Reset filters'}).click();
    assert.equal(await page.locator('.claim:visible').count(),3);
    // Real keyboard citation navigation and return from a source card.
    await page.locator('#citation-q1 a').focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.activeElement.id==='source-s1');
    const summary=page.locator('#source-s1 summary');
    await summary.focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#source-s1 details').getAttribute('open'),'');
    await page.selectOption('#source','s2');
    await page.locator('#source-s1 a').focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.activeElement.id==='citation-q1');
    assert.equal(await page.locator('#claim-c1').isVisible(),true);
    await page.locator('#citation-q1 summary').focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#citation-q1 mark').isVisible(),true);
    assert.match(await page.locator('#citation-q1 mark').textContent(), /<img/);
    // Tab order, skip link, and small viewport layout.
    await page.goto(pathToFileURL(path.join(dir,'browser.html')).href);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Skip to claims');
    await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.activeElement.id==='claims');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.deepEqual(errors,[]); assert.deepEqual(dialogs,[]); assert.deepEqual(requests,[]);
    // The report remains readable when scripting is disabled.
    const nojs=await browser.newContext({javaScriptEnabled:false,offline:true});
    const staticPage=await nojs.newPage();
    await staticPage.goto(pathToFileURL(path.join(dir,'browser.html')).href);
    assert.equal(await staticPage.locator('.claim:visible').count(),3);
    const result={browser:await browser.version(),scenarios:['search and reset','combined source filters',
      'keyboard shortcuts','citation navigation and return','context expansion','skip link',
      '390px viewport','hostile imported text','JavaScript-disabled reading'],http_requests:requests.length,
      hostile_script_executions:dialogs.length,report_bytes:fs.statSync(path.join(dir,'browser.html')).size};
    console.log(JSON.stringify(result));
  } finally {
    if(browser) await browser.close();
    fs.rmSync(dir,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
