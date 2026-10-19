// Print only local, script-free book HTML. No network requests are permitted.
const fs = require('fs');
const path = require('path');
const {pathToFileURL} = require('url');
if (!process.env.PLAYWRIGHT_BROWSERS_PATH && fs.existsSync('/tmp/claimledger-browsers')) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = '/tmp/claimledger-browsers';
}
const {chromium} = require('playwright');
(async () => {
  const dir = path.resolve(process.argv[2]);
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({javaScriptEnabled: false});
    await context.route('**/*', route => route.request().url().startsWith('file:') ? route.continue() : route.abort());
    const page = await context.newPage();
    await page.goto(pathToFileURL(path.join(dir, 'book.html')).href);
    await page.pdf({path: path.join(dir, 'book.pdf'), preferCSSPageSize: true, printBackground: true,
      tagged: true, outline: true, displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="width:100%;text-align:center;font:8px sans-serif;color:#50636a"><span class="pageNumber"></span></div>'});
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
