#!/usr/bin/env python3
"""Build the historical book and ledger from pinned inputs, without network access."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from claimledger import core, report
from book_sources import snapshots

BOOK = ROOT / 'book'
REF = re.compile(r'\[\^([a-z][a-z0-9-]*)\]')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs():
    catalog = json.loads((BOOK / 'sources/catalog.json').read_text())
    sources = catalog['sources']
    evidence = json.loads((BOOK / 'evidence.json').read_text())
    assert len({e['id'] for e in evidence}) == len(evidence), 'duplicate evidence ID'
    for source in sources:
        raw = (BOOK / 'sources' / source['snapshot']).read_bytes()
        assert sha(raw) == source['sha256'], 'snapshot changed: ' + source['id']
        source['text'] = raw.decode('utf-8')
        for original in source['raw']:
            data = (BOOK / 'sources' / original['path']).read_bytes()
            assert len(data) == original['bytes'] and sha(data) == original['sha256'], 'raw source changed'
    for ident, extracted in snapshots().items():
        assert extracted == next(s['text'] for s in sources if s['id'] == ident), 'extraction changed'
    text = (BOOK / 'manuscript.md').read_text()
    blocks = text.strip().split('\n\n')
    assert blocks[0].startswith('# ')
    title = blocks.pop(0)[2:]
    sections = []
    for block in blocks:
        if block.startswith('## '):
            sections.append({'heading': block[3:], 'paragraphs': []})
        else:
            assert sections, 'paragraph before section'
            refs = REF.findall(block)
            kind = 'interpretation' if block.startswith('Interpretation.') else ('sourced' if refs else 'editorial')
            assert not sections[-1]['heading'].startswith('Chapter ') or refs, 'uncited historical paragraph'
            sections[-1]['paragraphs'].append({'text': REF.sub('', block).strip(), 'markdown': block,
                                              'refs': refs, 'kind': kind})
    used = {r for s in sections for p in s['paragraphs'] for r in p['refs']}
    assert used == {e['id'] for e in evidence}, 'missing or unused evidence'
    return title, sections, sources, evidence


def build_text():
    title, sections, sources, evidence = inputs()
    lookup = {e['id']: e for e in evidence}
    by_source = {s['id']: s for s in sources}
    ledger = core.new()
    for source in sources:
        core.import_source(ledger, source['id'], source['text'], source['title'], source['author'], source['date'], source['url'])
    order, numbers, backlinks = [], {}, {}
    for si, section in enumerate(sections, 1):
        for pi, paragraph in enumerate(section['paragraphs'], 1):
            ident = f'p{si:02d}-{pi:02d}'
            paragraph['id'] = ident
            if paragraph['refs']:
                core.append(ledger, 'claims', {'id': ident, 'text': paragraph['text']})
            for ri, ref in enumerate(paragraph['refs'], 1):
                if ref not in numbers:
                    order.append(ref)
                    numbers[ref] = len(order)
                    backlinks[ref] = []
                backlinks[ref].append(ident)
                item = lookup[ref]
                core.cite(ledger, f'cite-{ident}-{ri}', ident, item['source'], item['quote'])
    audit = core.audit(ledger)
    assert audit['ok'] and not audit['issues'], audit
    e = html.escape
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           '<title>' + e(title) + ' — The Atlantic Cable, 1854–1866</title><style>',
           (BOOK / 'style.css').read_text(), '</style></head><body><a class="skip" href="#contents">Skip to contents</a><main>',
           '<header class="cover"><div class="eyebrow">A short history · 1854–1866</div><h1>' + e(title) + '</h1>',
           '<p class="subtitle">The Atlantic cable, from failed attempts to a working connection</p><div class="rule"></div>',
           '<p class="edition">Research edition · October 2026<br>Chapters, exact source excerpts, and an offline evidence ledger</p></header>',
           '<nav id="contents" aria-label="Contents"><h2>Contents</h2><ol>']
    for si, section in enumerate(sections, 1):
        out.append(f'<li><a href="#chapter-{si}">{e(section["heading"])}</a></li>')
    out.append('<li><a href="#notes">Notes and exact excerpts</a></li><li><a href="#bibliography">Bibliography and provenance</a></li></ol></nav>')
    for si, section in enumerate(sections, 1):
        out.append(f'<section class="chapter" aria-labelledby="chapter-{si}"><h2 id="chapter-{si}">{e(section["heading"])}</h2>')
        for paragraph in section['paragraphs']:
            content = REF.sub(lambda m: f'<sup><a href="#note-{m[1]}" aria-label="Note {numbers[m[1]]}">[{numbers[m[1]]}]</a></sup>', e(paragraph['markdown']))
            if paragraph['kind'] == 'interpretation':
                content = content.replace('Interpretation.', '<span class="label">Interpretation.</span>', 1)
            out.append(f'<p id="{paragraph["id"]}" class="{paragraph["kind"]}">{content}</p>')
        out.append('</section>')
    out.append('<section class="notes" aria-labelledby="notes"><h2 id="notes">Notes and exact excerpts</h2><p>Quotations match the saved source text, including OCR errors and inserted page markers. A match establishes citation integrity, not historical truth. Locations refer to the printed work unless labeled “scan”.</p><ol>')
    for ref in order:
        item = lookup[ref]
        source = by_source[item['source']]
        start = source['text'].index(item['quote'])
        end = start + len(item['quote'])
        line = source['text'][:start].count('\n') + 1
        out.append(f'<li id="note-{ref}"><span class="note-meta"><a href="#bib-{source["id"]}">{e(source["author"])}</a>, {e(item["locator"])}.</span>')
        out.append('<blockquote>' + e(item['quote']) + '</blockquote>')
        if item['note']:
            out.append('<p>' + e(item['note']) + '</p>')
        out.append(f'<p class="note-meta">Snapshot {e(source["snapshot"])} · line {line} · Unicode code points [{start}, {end}). <span class="screen-only"><a href="evidence.html#source-{source["id"]}">Full retained text in companion evidence edition</a>.</span></p>')
        out.append('<div class="back">Return: ' + ' '.join(f'<a href="#{p}">{p}</a>' for p in backlinks[ref]) + '</div></li>')
    out.append('</ol></section><section class="bibliography" aria-labelledby="bibliography"><h2 id="bibliography">Bibliography and provenance</h2>')
    for source in sources:
        out.append(f'<article id="bib-{source["id"]}"><h3>{e(source["title"])}</h3><p>{e(source["author"])} · {e(source["date"])}.</p>')
        for field in ('edition', 'role', 'transformation'):
            out.append('<p>' + e(source[field]) + '</p>')
        out.append(f'<p>Public source: <a href="{e(source["url"], quote=True)}">{e(source["url"])}</a><br>Retrieved {source["accessed"]}. No network access is needed to read or rebuild this edition from its saved inputs.</p>')
        out.append(f'<p class="hash">Snapshot SHA-256: {source["sha256"]}</p></article>')
    out.append('</section><footer>Prepared with Claim Source Ledger. Historical research and narrative assisted by AI; factual judgments remain limited by the cited record. Source files, build instructions, and documented gaps accompany the repository edition. No claim of new historical discovery is made.</footer></main></body></html>')
    summary = {'title': title, 'sections': [{k: v for k, v in s.items()} for s in sections],
               'sources': [{k: v for k, v in s.items() if k != 'text'} for s in sources],
               'note_order': order, 'audit': audit}
    return {'book.html': ''.join(out).encode(), 'evidence.html': report.render(ledger),
            'evidence.json': core.encoded(ledger), 'reading.json': core.encoded(summary)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new output directory')
    parser.add_argument('--html-only', action='store_true', help='omit PDF; Python standard library only')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; choose a new directory')
    files = build_text()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.book-', dir=args.output.parent) as temp:
        stage = Path(temp) / 'edition'
        stage.mkdir()
        for name, raw in files.items():
            (stage / name).write_bytes(raw)
        if not args.html_only:
            subprocess.run(['node', str(ROOT / 'scripts/book_pdf.cjs'), str(stage.resolve())], cwd=ROOT, check=True)
        tracked_inputs = ['book/manuscript.md', 'book/evidence.json', 'book/style.css', 'book/sources/catalog.json',
                          'scripts/book_sources.py', 'scripts/build_book.py', 'scripts/book_pdf.cjs', 'package-lock.json']
        tracked_inputs += [str(p.relative_to(ROOT)) for p in sorted((BOOK / 'sources').rglob('*')) if p.is_file()]
        tracked_inputs += ['claimledger/core.py', 'claimledger/report.py']
        manifest = {'version': 1, 'format': 'atlantic-cable-book',
                    'reproducibility': 'Text outputs deterministic from pinned inputs. PDF metadata and font rendering can vary by environment; PDF byte identity is not promised.',
                    'inputs': {p: sha((ROOT / p).read_bytes()) for p in sorted(set(tracked_inputs))},
                    'files': {p.name: {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in sorted(stage.iterdir())}}
        (stage / 'manifest.json').write_bytes(core.encoded(manifest))
        # Use the existing no-clobber publication primitive on Linux.
        from claimledger.archive import commit_directory
        commit_directory(stage, args.output)
    print(args.output / 'book.html')


if __name__ == '__main__':
    main()
