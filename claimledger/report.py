"""Self-contained report: imported values only enter escaped text/attributes."""
import base64
import hashlib
from html import escape as e
from .core import audit, MAX_LEDGER, require

SCRIPT = '''
const search = document.querySelector('#search');
const source = document.querySelector('#source');
const cards = [...document.querySelectorAll('.claim')];
function filter() {
  let count = 0;
  for (const card of cards) {
    card.hidden = !(card.textContent.toLowerCase().includes(search.value.toLowerCase()) &&
      (!source.value || card.dataset.sources.split(' ').includes(source.value)));
    if (!card.hidden) count++;
  }
  document.querySelector('#count').textContent = `${count} of ${cards.length} claims shown`;
}
search.addEventListener('input', filter);
source.addEventListener('change', filter);
document.querySelector('#reset').addEventListener('click', () => {
  search.value = ''; source.value = ''; filter(); search.focus();
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault(); search.focus();
  }
  if (event.key === 'Escape' && document.activeElement === search) {
    search.value = ''; filter();
  }
});
function navigate() {
  const target = document.getElementById(location.hash.slice(1));
  if (!target) return;
  const card = target.closest('.claim');
  if (card && card.hidden) {search.value = ''; source.value = ''; filter();}
  let parent = target.parentElement;
  while (parent) {if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement;}
  target.focus(); target.scrollIntoView();
}
window.addEventListener('hashchange', navigate);
filter(); navigate();
'''
STYLE = '''
:root{color-scheme:light; font:17px/1.6 system-ui,sans-serif;color:#182c36;background:#f3f5f4}
*{box-sizing:border-box}body{max-width:1100px;margin:0 auto;padding:2rem;overflow-wrap:anywhere}h1{font-size:2.6rem;line-height:1.15;letter-spacing:-.04em}
h2{line-height:1.3}header{border-bottom:3px solid #176b62;padding-bottom:1rem}
.eyebrow{color:#176b62;font-weight:700;text-transform:uppercase;letter-spacing:.12em;font-size:.8rem}
.tools{display:flex;gap:1rem;flex-wrap:wrap;background:#fff;padding:1rem;margin:1.5rem 0;border-radius:.5rem}
label{display:flex;flex-direction:column;font-weight:600;min-width:0;flex:1}input,select,button{font:inherit;padding:.45rem;border:1px solid #657b84;border-radius:.25rem;max-width:100%;min-width:0}
button{background:#176b62;color:white;cursor:pointer;align-self:end}article{background:white;border:1px solid #c4d3d1;border-radius:.5rem;padding:1.4rem;margin:1rem 0}
a{color:#075b9b}blockquote{border-left:4px solid #176b62;margin:1rem 0;padding:.6rem 1rem;background:#eef6f3}
pre,.excerpt{white-space:pre-wrap;overflow-wrap:anywhere}pre{font:inherit}code{overflow-wrap:anywhere}
.context{color:#455b65}mark{background:#f9e5a5;color:#182c36}.muted{color:#455b65;font-size:.9rem}
:focus-visible{outline:3px solid #8c4100;outline-offset:4px}[hidden]{display:none!important}
.warning{border-left:4px solid #9a5800;padding-left:1rem}summary{cursor:pointer;font-weight:600}
.skip{position:absolute;left:-10000px}.skip:focus{position:static}
@media(max-width:600px){body{padding:1rem}h1{font-size:2rem}.tools{display:block}label,button{margin:.5rem 0}}
@media print{.tools,.skip{display:none}article{break-inside:avoid}body{background:white}}
'''

def render(data):
    result = audit(data)
    require(result['ok'], 'repair ledger integrity errors before exporting')
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'sha256-{script_hash}\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           '<title>Claim Source Ledger — evidence report</title><style>'+STYLE+'</style></head><body>',
           '<a class="skip" href="#claims">Skip to claims</a><header><p class="eyebrow">Offline research evidence</p><h1>Claim Source Ledger</h1>',
           '<p>Citation integrity is not factual truth. An exact quotation does not establish that it supports a claim.</p>',
           f'<p>{len(data["claims"])} claims · {len(data["sources"])} source snapshots · {len(data["citations"])} citations</p></header>',
           '<div class="tools"><label>Search claims and quotations<input id="search" type="search" placeholder="Search…" aria-keyshortcuts="/"></label>',
           '<label>Source snapshot<select id="source"><option value="">All sources</option>']
    for s in data['sources']:
        out.append(f'<option value="{e(s["id"])}">{e(s["title"])} ({e(s["id"])})</option>')
    out += ['</select></label><button id="reset" type="button">Reset filters</button></div>',
            '<p class="muted">Keyboard: / focuses search; Escape clears search. Tab and Enter follow citations and open source text.</p>',
            '<p id="count" role="status" aria-live="polite"></p><noscript>All claims are visible. Search and filters require JavaScript.</noscript>',
            '<main id="claims" tabindex="-1"><h2>Authored claims</h2>']
    for c in data['claims']:
        links = [x for x in data['citations'] if x['claim']==c['id']]
        sources = ' '.join(sorted({x['source'] for x in links}))
        out.append(f'<article class="claim" id="claim-{c["id"]}" data-sources="{sources}" tabindex="-1"><h3>{e(c["text"])}</h3><p class="muted">Claim {c["id"]}</p>')
        if not links:
            out.append('<p class="warning">No evidence linked.</p>')
        for x in links:
            out.append(f'<section id="citation-{x["id"]}" tabindex="-1"><h4>Citation {x["id"]}</h4><blockquote class="excerpt">{e(x["quote"])}</blockquote>')
            out.append(f'<p><a href="#source-{x["source"]}">Source {x["source"]}</a> · code points [{x["start"]}, {x["end"]})</p>')
            if x['supersedes']:
                out.append(f'<p>Accepted relocation of <a href="#citation-{x["supersedes"]}">{x["supersedes"]}</a>; original retained.</p>')
            out.append(f'<details><summary>Excerpt context</summary><p class="excerpt context">{e(x["prefix"])}<mark>{e(x["quote"])}</mark>{e(x["suffix"])}</p></details></section>')
        out.append('</article>')
    out.append('</main><section aria-labelledby="sources-heading"><h2 id="sources-heading">Immutable source snapshots</h2>')
    for s in data['sources']:
        out.append(f'<article id="source-{s["id"]}" tabindex="-1"><h3>{e(s["title"])}</h3><p>{e(s["author"])} · {e(s["date"])}</p><p class="muted">Source {s["id"]} · SHA-256 <code>{s["sha256"]}</code></p>')
        out.append(f'<p>Reference URL (not fetched): <span>{e(s["url"])}</span></p><p>Cited by: ')
        for c in data['citations']:
            if c['source']==s['id']:
                out.append(f'<a href="#citation-{c["id"]}">{c["id"]}</a> ')
        out.append(f'</p><details><summary>Full snapshot text</summary><pre>{e(s["text"])}</pre></details></article>')
    out.append('</section><script>'+SCRIPT+'</script></body></html>')
    payload = ''.join(out).encode('utf-8')
    require(len(payload) <= MAX_LEDGER, 'report exceeds 8 MiB; use a smaller collection')
    return payload
