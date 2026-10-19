// Exercise the real reading edition, its evidence links, and every PDF paragraph.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const {pathToFileURL} = require('url');
if (!process.env.PLAYWRIGHT_BROWSERS_PATH && fs.existsSync('/tmp/claimledger-browsers')) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = '/tmp/claimledger-browsers';
}
const {chromium} = require('playwright');
const compact = text => text.normalize('NFC').replace(/\s+/gu, '');
(async () => {
  const dir = path.resolve(process.argv[2]);
  const reading = JSON.parse(fs.readFileSync(path.join(dir, 'reading.json')));
  const browser = await chromium.launch({headless: true});
  let localLinks = 0;
  try {
    const context = await browser.newContext({javaScriptEnabled: false});
    const unexpected = [];
    await context.route('**/*', route => {
      if (route.request().url().startsWith('file:')) return route.continue();
      unexpected.push(route.request().url());
      return route.abort();
    });
    const page = await context.newPage();
    await page.goto(pathToFileURL(path.join(dir, 'book.html')).href);
    const links = await page.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
    const ids = await page.locator('[id]').evaluateAll(nodes => nodes.map(n => n.id));
    assert.equal(ids.length, new Set(ids).size, 'duplicate HTML ID');
    for (const href of links.filter(h => h.startsWith('#'))) {
      assert(ids.includes(href.slice(1)), `broken anchor ${href}`);
      localLinks++;
    }
    for (const section of reading.sections) {
      for (const paragraph of section.paragraphs) {
        const actual = await page.locator('#' + paragraph.id).textContent();
        assert.equal(compact(actual.replace(/\[\d+\]/g, '')), compact(paragraph.text));
      }
    }
    await page.keyboard.press('Tab');
    assert.equal(await page.locator(':focus').textContent(), 'Skip to contents');
    await page.keyboard.press('Enter');
    assert(page.url().endsWith('#contents'));
    await page.locator('sup a').first().click();
    assert(page.url().includes('#note-'));
    await page.locator(page.url().slice(page.url().indexOf('#')) + ' .back a').first().click();
    assert(page.url().includes('#p01-01'));
    for (const width of [1280, 375]) {
      await page.setViewportSize({width, height: 900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'horizontal overflow');
    }
    const sourceIds = reading.sources.map(s => s.id);
    await page.goto(pathToFileURL(path.join(dir, 'evidence.html')).href);
    for (const id of sourceIds) assert.equal(await page.locator('#source-' + id).count(), 1);
    assert.deepEqual(unexpected, [], 'unexpected external resource request');
  } finally { await browser.close(); }

  const {getDocument} = await import('pdfjs-dist/legacy/build/pdf.mjs');
  const pdf = await getDocument({data: new Uint8Array(fs.readFileSync(path.join(dir, 'book.pdf'))),
    useSystemFonts: true, isEvalSupported: false}).promise;
  const texts = [];
  let internalLinks = 0, externalLinks = 0;
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const text = await page.getTextContent();
    const viewport = page.getViewport({scale: 1});
    const body = text.items.filter(t => t.str && t.transform[5] > 30);
    assert(body.map(t => t.str).join('').length > 30, `empty PDF page ${i}`);
    for (const item of body) {
      assert(item.transform[4] >= -1 && item.transform[4] + item.width <= viewport.width + 1,
        `clipped horizontal text page ${i}: ${item.str}`);
      assert(item.transform[5] < viewport.height, `clipped vertical text page ${i}`);
    }
    texts.push(body.map(t => t.str).join(' '));
    for (const annotation of await page.getAnnotations()) {
      if (annotation.subtype !== 'Link') continue;
      if (annotation.dest) internalLinks++;
      const url = annotation.url || annotation.unsafeUrl;
      if (url) {
        assert(/^https:\/\//.test(url), `nonportable PDF link: ${url}`);
        externalLinks++;
      }
    }
  }
  const pdfText = compact(texts.join(' ').replace(/\[\d+\]/g, ''));
  let paragraphs = 0;
  for (const section of reading.sections) {
    assert(pdfText.includes(compact(section.heading)), `missing PDF chapter ${section.heading}`);
    for (const paragraph of section.paragraphs) {
      assert(pdfText.includes(compact(paragraph.text)), `missing or damaged PDF paragraph ${paragraph.id}`);
      paragraphs++;
    }
  }
  const ledger = JSON.parse(fs.readFileSync(path.join(dir, 'evidence.json')));
  const excerpts = [...new Set(ledger.citations.map(c => c.quote))];
  for (const quote of excerpts) {
    assert(pdfText.includes(compact(quote)), 'missing or damaged PDF evidence excerpt: ' + quote.slice(0, 70));
  }
  for (const source of reading.sources) {
    assert(pdfText.includes(compact(source.title)), 'missing PDF bibliography entry: ' + source.id);
  }
  const outline = await pdf.getOutline();
  assert(outline && outline.length > 0, 'missing PDF outline');
  assert(internalLinks >= reading.note_order.length, 'missing PDF citation links');
  assert(externalLinks >= reading.sources.length, 'missing PDF bibliography URLs');
  console.log(JSON.stringify({ok: true, paragraphs, exact_pdf_excerpts: excerpts.length, pdf_pages: pdf.numPages,
    html_internal_links: localLinks, pdf_internal_links: internalLinks, pdf_external_links: externalLinks,
    network_requests: 0, viewport_widths: [1280, 375]}));
  await pdf.destroy();
})().catch(error => {console.error(error); process.exitCode = 1;});
