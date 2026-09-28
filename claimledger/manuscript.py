"""Version 1 ordered manuscripts; pure resolution followed by no-clobber publication."""
import html
import os
from pathlib import Path
import shutil
import tempfile

from . import core as c
from .archive import parse, sha, commit_directory

MAX_SPEC = 256 * 1024
MAX_SECTIONS = 100
MAX_CLAIMS = 500  # occurrences, including repetitions
MAX_SELECTIONS = 2000
MAX_SOURCES = 100
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT = 16 * 1024 * 1024
NOTICE = 'Citation integrity verifies text and location, not factual support or truth.'


def spec_schema(spec):
    c.require(isinstance(spec, dict) and set(spec) == {'version', 'title', 'sections'}, 'invalid manuscript fields')
    c.require(type(spec['version']) is int and spec['version'] == 1, 'unsupported manuscript version')
    c.require(c.string(spec['title'], 1024), 'invalid manuscript title')
    c.require(isinstance(spec['sections'], list) and 1 <= len(spec['sections']) <= MAX_SECTIONS, 'invalid section count')
    claims = selections = 0
    for section in spec['sections']:
        c.require(isinstance(section, dict) and set(section) == {'heading', 'claims'}, 'invalid section fields')
        c.require(c.string(section['heading'], 1024), 'invalid section heading')
        c.require(isinstance(section['claims'], list), 'invalid ordered claims')
        claims += len(section['claims'])
        c.require(claims <= MAX_CLAIMS, 'claim-count limit exceeded')
        for item in section['claims']:
            c.require(isinstance(item, dict) and set(item) == {'id', 'citations'}, 'invalid claim selection')
            c.require(isinstance(item['id'], str) and c.ID.fullmatch(item['id']), 'invalid claim identifier')
            c.require(isinstance(item['citations'], list), 'invalid citation selections')
            selections += len(item['citations'])
            c.require(selections <= MAX_SELECTIONS, 'citation-selection limit exceeded')
            for ident in item['citations']:
                c.require(isinstance(ident, str) and c.ID.fullmatch(ident), 'invalid citation identifier')
    c.require(claims > 0, 'manuscript requires at least one claim')
    c.require(len(c.encoded(spec)) <= MAX_SPEC, 'specification byte limit exceeded')


def resolve(data, spec):
    spec_schema(spec)
    c.valid(data)  # Include unselected records: no silently ignored corrupt history.
    ledger = c.encoded(data)
    c.require(len(ledger) <= c.MAX_LEDGER, 'ledger byte limit exceeded')
    claims = {x['id']: x for x in data['claims']}
    citations = {x['id']: x for x in data['citations']}
    sources = {x['id']: x for x in data['sources']}
    chosen, selected_sources, sections = {}, {}, []
    for section in spec['sections']:
        rows = []
        for item in section['claims']:
            c.require(item['id'] in claims, 'missing claim: '+item['id'])
            for ident in item['citations']:
                c.require(ident in citations, 'missing citation: '+ident)
                citation = citations[ident]
                c.require(citation['claim'] == item['id'], 'citation belongs to another claim: '+ident)
                chosen[ident] = dict(citation)
                source = sources[citation['source']]
                selected_sources[source['id']] = source
            rows.append({'id': item['id'], 'text': claims[item['id']]['text'],
                         'citations': list(item['citations']), 'uncited': not item['citations']})
        sections.append({'heading': section['heading'], 'claims': rows})
    c.require(len(selected_sources) <= MAX_SOURCES, 'source-count limit exceeded')
    c.require(sum(len(s['text'].encode('utf-8')) for s in selected_sources.values()) <= MAX_SNAPSHOT_BYTES,
              'selected-source byte limit exceeded')
    return {'format': 'claim-source-ledger-manuscript', 'version': 1,
            'ledger_sha256': sha(ledger), 'spec_sha256': sha(c.encoded(spec)),
            'specification': spec, 'notice': NOTICE,
            'offsets': 'zero-based Unicode code points; start inclusive, end exclusive; no normalization',
            'sections': sections, 'citations': [chosen[k] for k in sorted(chosen)],
            'sources': [{k: v for k, v in selected_sources[ident].items() if k != 'text'}
                        for ident in sorted(selected_sources)]}, selected_sources


class BoundedText:
    def __init__(self):
        self.parts, self.size = [], 0

    def add(self, text):
        raw = text.encode('utf-8')
        self.size += len(raw)
        c.require(self.size <= MAX_OUTPUT, 'output byte limit exceeded')
        self.parts.append(raw)

    def bytes(self):
        return b''.join(self.parts)


def literal(text):
    # Numeric entities cannot introduce Markdown syntax, links, or raw HTML.
    # All punctuation, newlines, and controls are literal data in authored text.
    return ''.join(ch if ch.isalnum() or ch == ' ' else f'&#{ord(ch)};' for ch in text)


def build(data, spec):
    manifest, sources = resolve(data, spec)
    md, page = BoundedText(), BoundedText()
    esc = html.escape
    md.add('# '+literal(spec['title'])+'\n\n'+NOTICE+'\n\n')
    page.add('<!doctype html><html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
             '<title>'+esc(spec['title'])+'</title><style>'
             'body{max-width:72ch;margin:2rem auto;padding:0 1rem;font:18px/1.6 system-ui;color:#17252b;background:#fff;overflow-wrap:anywhere}'
             'pre,.authored{white-space:pre-wrap;overflow-wrap:anywhere}pre{font:inherit}'
             'a{color:#075ea4}a:focus-visible,:target{outline:3px solid #cc6d00;outline-offset:3px}'
             '.uncited{font-weight:bold;color:#803b00}section,article{margin:2rem 0}code{overflow-wrap:anywhere}'
             '</style></head><body><a href="#manuscript">Skip to manuscript</a>'
             '<header><h1 class="authored">'+esc(spec['title'])+'</h1><p>'+NOTICE+'</p></header>'
             '<nav aria-label="Contents"><ol>')
    for i, section in enumerate(manifest['sections'], 1):
        page.add(f'<li><a href="#section-{i}">'+esc(section['heading'])+'</a></li>')
    page.add('</ol></nav><main id="manuscript" tabindex="-1">')
    backlinks = {}
    occurrence = 0
    for i, section in enumerate(manifest['sections'], 1):
        md.add('## '+literal(section['heading'])+'\n\n')
        page.add(f'<section id="section-{i}" tabindex="-1"><h2 class="authored">'+esc(section['heading'])+'</h2>')
        for row in section['claims']:
            occurrence += 1
            anchor = f'claim-{occurrence}'
            md.add(literal(row['text']))
            page.add(f'<article id="{anchor}" tabindex="-1"><p class="authored">'+esc(row['text'])+'</p>')
            if row['uncited']:
                md.add(' **[Uncited claim]**')
                page.add('<p class="uncited">Uncited claim</p>')
            else:
                page.add('<p aria-label="Selected citations">')
                for ident in row['citations']:
                    backlinks.setdefault(ident, []).append(occurrence)
                    md.add(' ['+literal(ident)+f'](#citation-{ident})')
                    page.add(f'<a href="#citation-{ident}">[{ident}]</a> ')
                page.add('</p>')
            md.add('\n\n')
            page.add('</article>')
        page.add('</section>')
    md.add('## Verified excerpts\n\n')
    page.add('<section aria-label="Verified excerpts"><h2>Verified excerpts</h2>')
    for citation in manifest['citations']:
        ident, sid = citation['id'], citation['source']
        source = sources[sid]
        location = f"{sid}; Unicode [{citation['start']}, {citation['end']}); SHA-256 {source['sha256']}"
        md.add(f'<a id="citation-{ident}"></a>\n\n### '+literal(ident)+'\n\n'+literal(location)+'\n\n'+literal(citation['quote'])+'\n\n')
        md.add(f'[Source snapshot](snapshots/{source["sha256"]}.txt)\n\n')
        page.add(f'<article id="citation-{ident}" tabindex="-1"><h3>{ident}</h3><p>'+esc(location)+'</p>'
                 '<pre class="quote">'+esc(citation['quote'])+'</pre><details><summary>Excerpt context</summary><pre>'+
                 esc(citation['prefix'])+'<mark>'+esc(citation['quote'])+'</mark>'+esc(citation['suffix'])+'</pre></details>'+
                 f'<p><a href="#source-{sid}">Source revision {sid}</a></p><p>Return to claim: ')
        for n in dict.fromkeys(backlinks[ident]):
            page.add(f'<a href="#claim-{n}">{n}</a> ')
        page.add('</p></article>')
    page.add('</section><section aria-label="Source snapshots"><h2>Source snapshots</h2>')
    for sid, source in sorted(sources.items()):
        page.add(f'<article id="source-{sid}" tabindex="-1"><h3 class="authored">'+esc(source['title'])+'</h3><p>Revision '+sid+
                 '; SHA-256 <code>'+source['sha256']+'</code></p><p class="authored">'+esc(source['author'])+' '+esc(source['date'])+
                 '</p><p class="authored">Recorded URL (not fetched): '+esc(source['url'])+'</p>'
                 '<details><summary>Full snapshot</summary><pre>'+esc(source['text'])+'</pre></details></article>')
    page.add('</section></main></body></html>\n')
    files = {'manuscript.md': md.bytes(), 'manuscript.html': page.bytes()}
    for source in sources.values():
        files['snapshots/'+source['sha256']+'.txt'] = source['text'].encode('utf-8')
    manifest['files'] = {name: {'bytes': len(raw), 'sha256': sha(raw)} for name, raw in sorted(files.items())}
    files['manifest.json'] = c.encoded(manifest)
    c.require(sum(map(len, files.values())) <= MAX_OUTPUT, 'output byte limit exceeded')
    return files


def export(ledger, specification, destination):
    ledger, specification, destination = map(lambda p: Path(p).absolute(), (ledger, specification, destination))
    # Read specification once; the manifest records its canonical content.
    spec = parse(c.read_bytes(specification, MAX_SPEC))
    c.require(not os.path.lexists(destination), 'manuscript destination already exists')
    with c.locked(ledger):
        before = c.read_bytes(ledger, c.MAX_LEDGER)
        files = build(parse(before), spec)
        c.require(c.read_bytes(ledger, c.MAX_LEDGER) == before, 'ledger changed during manuscript build')
        staging = Path(tempfile.mkdtemp(prefix='.'+destination.name+'.manuscript-', dir=destination.parent))
        try:
            (staging/'snapshots').mkdir(mode=0o700)
            for name, raw in sorted(files.items()):
                c.atomic_write(staging/name, raw)
            for folder in (staging/'snapshots', staging):
                fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            result = {'destination': str(destination), 'files': len(files),
                      'bytes': sum(map(len, files.values())), 'manifest_sha256': sha(files['manifest.json'])}
            commit_directory(staging, destination)  # Only commit point; never replace.
            return result
        finally:
            shutil.rmtree(staging, ignore_errors=True)
