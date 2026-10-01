"""Offline comparison semantics v1. IDs are asserted identity, never inferred identity."""
import base64
from collections import Counter
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time

from . import core as c, manuscript as m
from .archive import parse, sha, commit_directory

MAX_INPUT = 16 * 1024 * 1024  # per bundle, all files including manifest
MAX_OUTPUT = 16 * 1024 * 1024  # both output files together
MAX_WORK = 64 * 1024 * 1024  # canonical bytes visited by comparison projections
MAX_SECONDS = 30.0
NOTICE = ('Absence is relative only to these bundles. Citation integrity does not establish '
          'factual support, authenticity, or truth. IDs assert identity; they do not prove it.')
OFFSETS = 'zero-based Unicode code points; start inclusive, end exclusive; no normalization'
FIELDS = {'format', 'version', 'ledger_sha256', 'spec_sha256', 'specification', 'notice',
          'offsets', 'sections', 'citations', 'sources', 'files'}


class Budget:
    def __init__(self, seconds=MAX_SECONDS, work=MAX_WORK):
        c.require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= MAX_SECONDS,
                  'runtime limit must be positive and at most 30 seconds')
        c.require(type(work) is int and 0 < work <= MAX_WORK, 'invalid comparison-work limit')
        self.deadline = time.monotonic() + seconds
        self.work, self.limit = 0, work

    def check(self, amount=0):
        self.work += amount
        c.require(self.work <= self.limit, 'comparison-work limit exhausted; no report published')
        c.require(time.monotonic() < self.deadline, 'runtime limit exhausted; no report published')

    def value(self, value):
        raw = encode(value, self)
        self.check(len(raw))
        return raw

    def different(self, before, after):
        return self.value(before) != self.value(after)


def encode(value, budget):
    """Bound serialization incrementally, including before final byte concatenation."""
    pieces, size = [], 0
    for piece in json.JSONEncoder(ensure_ascii=False, sort_keys=True, indent=2).iterencode(value):
        raw = piece.encode('utf-8')
        size += len(raw)
        c.require(size + 1 <= MAX_OUTPUT, 'output byte limit exceeded')
        budget.check()
        pieces.append(raw)
    return b''.join(pieces) + b'\n'


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)


def inventory(root, expected, budget):
    """Only the two fixed directory levels; no traversal of imported paths or links."""
    for folder, names in [(root, {'manifest.json', 'manuscript.md', 'manuscript.html', 'snapshots'}),
                          (root/'snapshots', {x.split('/')[1] for x in expected if x.startswith('snapshots/')})]:
        c.require(not folder.is_symlink() and folder.is_dir(), 'bundle directory must not be a symlink')
        found = set()
        with os.scandir(folder) as entries:
            for entry in entries:
                budget.check()
                c.require(entry.name in names, 'unexpected bundle entry')
                c.require(not entry.is_symlink(), 'bundle symlinks are unsupported')
                found.add(entry.name)
        c.require(found == names, 'bundle file set mismatch')


def read_file(root_fd, name, limit):
    # Every component is opened relative to a pinned directory, without following links.
    parent = os.dup(root_fd)
    try:
        components = name.split('/')
        for component in components[:-1]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = nxt
        fd = os.open(components[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            c.require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'bundle input must be a regular file')
            raw = stream.read(limit + 1)
        c.require(len(raw) <= limit, 'input-byte limit exceeded')
        return raw
    finally:
        os.close(parent)


def load_bundle(root, budget):
    root = Path(root).absolute()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        raw = read_file(fd, 'manifest.json', MAX_INPUT)
        budget.check()
        doc = parse(raw)
        c.require(isinstance(doc, dict) and set(doc) == FIELDS, 'invalid manuscript manifest fields')
        c.require(doc['format'] == 'claim-source-ledger-manuscript' and type(doc['version']) is int
                  and doc['version'] == 1, 'unsupported manuscript bundle version')
        c.require(doc['notice'] == m.NOTICE and doc['offsets'] == OFFSETS, 'unsupported manuscript conventions')
        c.require(valid_hash(doc['ledger_sha256']) and valid_hash(doc['spec_sha256']), 'invalid provenance hash')
        m.spec_schema(doc['specification'])
        c.require(doc['spec_sha256'] == sha(c.encoded(doc['specification'])), 'specification hash mismatch')
        c.require(isinstance(doc['sections'], list) and len(doc['sections']) == len(doc['specification']['sections']),
                  'resolved section count mismatch')
        claims = {}
        selected = set()
        for section, spec in zip(doc['sections'], doc['specification']['sections']):
            budget.check()
            c.require(isinstance(section, dict) and set(section) == {'heading', 'claims'}
                      and section['heading'] == spec['heading'] and isinstance(section['claims'], list)
                      and len(section['claims']) == len(spec['claims']), 'resolved section mismatch')
            for row, chosen in zip(section['claims'], spec['claims']):
                c.require(isinstance(row, dict) and set(row) == {'id', 'text', 'citations', 'uncited'}, 'invalid resolved claim')
                c.require(row['id'] == chosen['id'] and row['citations'] == chosen['citations']
                          and type(row['uncited']) is bool and row['uncited'] == (not chosen['citations']),
                          'resolved selection mismatch')
                c.require(c.string(row['text']), 'invalid selected claim text')
                c.require(row['id'] not in claims or claims[row['id']] == row['text'], 'inconsistent repeated claim text')
                claims[row['id']] = row['text']
                selected.update(chosen['citations'])
        c.require(isinstance(doc['sources'], list) and len(doc['sources']) <= m.MAX_SOURCES, 'source-count limit exceeded')
        c.require(isinstance(doc['citations'], list) and len(doc['citations']) <= c.MAX_ITEMS, 'invalid citations')
        # Schema-check metadata before deriving snapshot paths.
        sources = []
        for source in doc['sources']:
            c.require(isinstance(source, dict) and set(source) == {'id','title','author','date','url','sha256'}
                      and valid_hash(source['sha256']), 'invalid source metadata')
            sources.append(dict(source, text=''))
        data = {'version': 1, 'claims': [{'id': k, 'text': v} for k, v in sorted(claims.items())],
                'citations': doc['citations'], 'sources': sources}
        c.schema(data)
        expected = {'manuscript.md', 'manuscript.html'} | {'snapshots/'+s['sha256']+'.txt' for s in sources}
        c.require(isinstance(doc['files'], dict) and set(doc['files']) == expected, 'manifest file set mismatch')
        inventory(root, expected, budget)
        files = {'manifest.json': {'bytes': len(raw), 'sha256': sha(raw)}}
        total = len(raw)
        snapshots = {}
        for name in sorted(expected):
            budget.check()
            record = doc['files'][name]
            c.require(isinstance(record, dict) and set(record) == {'bytes','sha256'}
                      and type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_INPUT
                      and valid_hash(record['sha256']), 'invalid file record')
            limit = min(MAX_INPUT-total, c.MAX_SOURCE if name.startswith('snapshots/') else MAX_INPUT)
            content = read_file(fd, name, limit)
            total += len(content)
            c.require(record == {'bytes': len(content), 'sha256': sha(content)}, 'bundle file hash or size mismatch')
            files[name] = record
            if name.startswith('snapshots/'):
                snapshots[name] = content.decode('utf-8')
        for source in sources:
            source['text'] = snapshots['snapshots/'+source['sha256']+'.txt']
        c.require(sum(len(s['text'].encode('utf-8')) for s in sources) <= m.MAX_SNAPSHOT_BYTES, 'source-byte limit exceeded')
        report = c.audit(data)
        # A manuscript intentionally omits unselected relocation ancestors.
        errors = [i for i in report['issues'] if i['severity'] == 'error' and i['code'] != 'dangling_supersedes']
        c.require(not errors, 'selected evidence integrity errors: '+json.dumps(errors))
        citations = {x['id']: x for x in doc['citations']}
        c.require(set(citations) == selected, 'selected citation set mismatch')
        c.require({x['source'] for x in citations.values()} == {s['id'] for s in sources}, 'selected source set mismatch')
        for section in doc['sections']:
            for row in section['claims']:
                c.require(all(citations[q]['claim'] == row['id'] for q in row['citations']), 'citation belongs to another claim')
        # Self-reference is not an omitted ancestor, even if an audit implementation changes.
        c.require(all(q['supersedes'] not in set(claims) | {s['id'] for s in sources}
                      for q in citations.values()), 'ancestry references a non-citation record')
        c.require(all(q['supersedes'] != q['id'] for q in citations.values()), 'citation ancestry cycle')
        budget.check()
        return {'manifest': doc, 'hashes': files, 'sha256': sha(c.encoded(files)), 'bytes': total}
    finally:
        os.close(fd)


def recheck(root, bundle, budget):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        inventory(Path(root), set(bundle['hashes'])-{'manifest.json'}, budget)
        for name, record in sorted(bundle['hashes'].items()):
            budget.check()
            raw = read_file(fd, name, record['bytes'])
            c.require(len(raw) == record['bytes'] and sha(raw) == record['sha256'], 'bundle changed during comparison')
    finally:
        os.close(fd)


def project(bundle, budget):
    doc = bundle['manifest']
    sources = {s['id']: s for s in doc['sources']}
    evidence = {}
    for citation in doc['citations']:
        # Citation identity and lineage are separate from the selected evidence itself.
        evidence[citation['id']] = {
            'revision': budget.value(sources[citation['source']]),
            'excerpt': budget.value({k: citation[k] for k in ('quote','start','end','prefix','suffix')}),
            'lineage': citation['supersedes']}
    groups = {}
    order = []
    for si, section in enumerate(doc['sections'], 1):
        for pos, row in enumerate(section['claims'], 1):
            budget.check()
            group = groups.setdefault(row['id'], {'text': row['text'], 'occurrences': []})
            group['occurrences'].append({'section': si, 'heading': section['heading'], 'position': pos,
                                         'citations': row['citations']})
            order.append(row['id'])
    return groups, evidence, order


def compare(before, after, budget):
    left, le, lo = project(before, budget)
    right, re_, ro = project(after, budget)
    findings = []
    def add(kind, ident, old, new):
        findings.append({'kind': kind, 'id': ident, 'before': old, 'after': new})
    bd, ad = before['manifest'], after['manifest']
    if budget.different(bd['specification']['title'], ad['specification']['title']):
        add('title', '', bd['specification']['title'], ad['specification']['title'])
    headings = [[s['heading'] for s in doc['sections']] for doc in (bd, ad)]
    if budget.different(*headings):
        add('sections', '', *headings)
    if budget.different(lo, ro):
        add('claim_order', '', lo, ro)
    for ident in sorted(left.keys() | right.keys()):
        budget.check()
        old, new = left.get(ident), right.get(ident)
        if old is None or new is None:
            add('added' if old is None else 'absent', ident, old, new)
            continue
        if budget.different(old['text'], new['text']):
            add('claim_text', ident, old['text'], new['text'])
        rows = (old['occurrences'], new['occurrences'])
        placements = [[{k: x[k] for k in ('section','heading','position')} for x in items] for items in rows]
        choices = [[x['citations'] for x in items] for items in rows]
        changed_occurrences = False
        for kind, values in [('placement', placements), ('citation_selection', choices)]:
            if budget.different(*values):
                add(kind, ident, *values)
                changed_occurrences = True
        if max(map(len, rows)) > 1 and changed_occurrences:
            add('ambiguous_occurrences', ident, len(rows[0]), len(rows[1]))
        # Compare sets: repeated selection changes are reported above, not duplicated here.
        qids = [sorted({q for row in items for q in row['citations']}) for items in rows]
        common = sorted(set(qids[0]) & set(qids[1]))
        for kind, key in [('source_revision','revision'), ('excerpt','excerpt')]:
            sets = [sorted({e[q][key] for q in ids}) for e, ids in zip((le,re_), qids)]
            budget.check(sum(len(x) for items in sets for x in items))
            if sets[0] != sets[1] or any(le[q][key] != re_[q][key] for q in common):
                add(kind, ident, qids[0], qids[1])
        # Retain which excerpt belongs to which source, even when the individual sets agree.
        pairs = [sorted({(e[q]['revision'], e[q]['excerpt']) for q in ids}) for e, ids in zip((le,re_), qids)]
        budget.check(sum(len(a)+len(b) for items in pairs for a,b in items))
        if pairs[0] != pairs[1] or any((le[q]['revision'], le[q]['excerpt']) !=
                                      (re_[q]['revision'], re_[q]['excerpt']) for q in common):
            add('source_evidence', ident, qids[0], qids[1])
        common = sorted(set(qids[0]) & set(qids[1]))
        lineage = [q for q in common if le[q]['lineage'] != re_[q]['lineage']]
        if lineage:
            add('citation_lineage', ident, {q: le[q]['lineage'] for q in lineage}, {q: re_[q]['lineage'] for q in lineage})
    ambiguous_sections = any(len(x) != len(set(x)) for x in headings)
    # Provenance changes are not silently collapsed into authored-content equality.
    provenance = [{k: doc[k] for k in ('ledger_sha256','spec_sha256')} for doc in (bd, ad)]
    if budget.different(*provenance):
        add('provenance', '', *provenance)
    findings.sort(key=lambda x: (x['id'], x['kind']))
    outcome = 'differences' if findings else 'no_semantic_changes'
    return {'format': 'claim-source-ledger-comparison', 'version': 1, 'complete': True, 'outcome': outcome,
            'notice': NOTICE, 'identity': 'claim ID; occurrences compared as ordered groups without cross-bundle pairing',
            'section_identity': 'positional; headings are authored text, not stable identifiers',
            'ambiguous_section_headings': ambiguous_sections,
            'inputs': {side: {k: bundle[k] for k in ('sha256','bytes','hashes')} for side,bundle in [('before',before),('after',after)]},
            'summary': dict(sorted(Counter(x['kind'] for x in findings).items())), 'findings': findings,
            'before': {'title': bd['specification']['title'], 'claims': left, 'citations': bd['citations'], 'sources': bd['sources']},
            'after': {'title': ad['specification']['title'], 'claims': right, 'citations': ad['citations'], 'sources': ad['sources']}}


SCRIPT = """'use strict';
const filter=document.getElementById('filter'), view=document.getElementById('view');
function apply(){let count=0;for(const row of document.querySelectorAll('.finding')){
row.hidden=filter.value!=='all'&&!row.dataset.kinds.split(' ').includes(filter.value);if(!row.hidden)count++;}
document.getElementById('count').textContent=count+' visible findings';document.body.dataset.view=view.value;}
filter.addEventListener('change',apply);view.addEventListener('change',apply);
document.addEventListener('click',event=>{const link=event.target.closest('a');if(!link)return;
const href=link.getAttribute('href');if(!href.startsWith('#finding-'))return;
const target=document.getElementById(href.slice(1));if(target&&target.hidden){filter.value='all';apply();}});apply();
"""


def render(result, budget):
    esc = html.escape
    parts, size = [], 0
    def put(text):
        nonlocal size
        raw = text.encode('utf-8')
        size += len(raw)
        c.require(size <= MAX_OUTPUT, 'output byte limit exceeded')
        budget.check()
        parts.append(raw)
    script_hash = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    put('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'sha256-'+script_hash+
        '\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Manuscript comparison</title><style>'
        'body{font:17px/1.6 system-ui;max-width:100ch;margin:2rem auto;padding:0 1rem;color:#17252b;background:white;overflow-wrap:anywhere}'
        'pre,.authored{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem}'
        'article{border-top:1px solid #899;padding:1rem 0}a{color:#075ea4}a:focus-visible,select:focus-visible,summary:focus-visible,:target{outline:3px solid #b65d00}'
        '[hidden]{display:none!important}body[data-view="before"] .after,body[data-view="after"] .before{display:none}'
        'body[data-view="before"] .pair,body[data-view="after"] .pair{grid-template-columns:1fr}'
        'select{font:inherit;margin:0.5rem}@media(max-width:650px){.pair{grid-template-columns:1fr}}'
        '</style></head><body><a href="#findings">Skip to findings</a><h1>Manuscript comparison</h1><p>'+esc(NOTICE)+'</p>'
        '<p>Outcome: <strong>'+result['outcome']+'</strong>. Analysis complete under version 1 semantics.</p>'
        '<p>Repeated claims are ordered groups. Their occurrences have no stable cross-bundle identity. '
        'Section positions include shifts caused by insertions; headings do not identify sections.</p>')
    if result['ambiguous_section_headings']:
        put('<p>Repeated section headings: section identity is ambiguous; only positions are compared.</p>')
    put('<noscript><p>JavaScript is disabled: all findings and both sides remain readable; filters require JavaScript.</p></noscript>'
        '<label for="filter">Finding type</label><select id="filter"><option value="all">All findings</option>')
    for kind in result['summary']:
        put('<option value="'+kind+'">'+kind.replace('_',' ')+'</option>')
    put('</select><label for="view">View</label><select id="view"><option value="both">Before and after</option>'
        '<option value="before">Before</option><option value="after">After</option></select>'
        '<p id="count" role="status" aria-live="polite"></p><main id="findings" tabindex="-1"><h2>Findings</h2>')
    if not result['findings']:
        put('<p>No semantic changes under the documented comparison rules. Input byte equality is recorded separately by hashes.</p>')
    backlinks = {}
    for index, finding in enumerate(result['findings'], 1):
        ident, kind = finding['id'], finding['kind']
        put(f'<article class="finding" id="finding-{index}" tabindex="-1" data-kinds="{kind}"><h3>'+esc(kind.replace('_',' ')+(' — '+ident if ident else ''))+'</h3>')
        if kind == 'ambiguous_occurrences':
            put('<p>Occurrence matching is ambiguous. Counts and ordered selections are shown; no particular occurrence is labeled moved or edited.</p>')
        put('<div class="pair">')
        for side in ('before','after'):
            value = finding[side]
            put('<section class="'+side+'"><h4>'+side.title()+'</h4><pre>'+esc(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))+'</pre>')
            group = result[side]['claims'].get(ident)
            if group:
                put('<p class="authored claim-text">'+esc(group['text'])+'</p><p>Selected excerpts: ')
                ids = sorted({q for row in group['occurrences'] for q in row['citations']})
                for q in ids:
                    backlinks.setdefault((side,q),set()).add(index)
                    put(f'<a href="#evidence-{side}-{q}">{q}</a> ')
                if not ids:
                    put('Uncited claim')
                put('</p>')
            put('</section>')
        put('</div></article>')
    put('</main><section aria-label="Evidence"><h2>Evidence excerpts</h2>')
    for side in ('before','after'):
        sources = {s['id']: s for s in result[side]['sources']}
        for citation in sorted(result[side]['citations'], key=lambda q:q['id']):
            budget.check()
            q, source = citation['id'], sources[citation['source']]
            put(f'<article id="evidence-{side}-{q}" tabindex="-1"><h3>{side.title()} — {q}</h3>'
                '<p class="authored">'+esc(source['title'])+'</p><p>Revision '+source['id']+'; SHA-256 '+source['sha256']+
                f'; Unicode [{citation["start"]}, {citation["end"]})</p><pre class="quote">'+esc(citation['quote'])+
                '</pre><details><summary>Excerpt context and metadata</summary><pre>'+esc(citation['prefix'])+'<mark>'+esc(citation['quote'])+'</mark>'+esc(citation['suffix'])+
                '</pre><pre>'+esc(json.dumps(source,ensure_ascii=False,indent=2))+'</pre></details><p>Return to finding: ')
            for index in sorted(backlinks.get((side,q),set())):
                put(f'<a href="#finding-{index}">{index}</a> ')
            put('</p></article>')
    put('</section><script>'+SCRIPT+'</script></body></html>\n')
    return b''.join(parts)


def export(before, after, destination, seconds=MAX_SECONDS, work=MAX_WORK):
    budget = Budget(seconds, work)
    before, after, destination = map(lambda x: Path(x).absolute(), (before, after, destination))
    c.require(not os.path.lexists(destination), 'comparison destination already exists')
    # Outputs inside inputs would mutate their inventory after validation.
    c.require(all(not destination.resolve().is_relative_to(p.resolve()) for p in (before,after)), 'output must be outside input bundles')
    left, right = load_bundle(before,budget), load_bundle(after,budget)
    result = compare(left,right,budget)
    files = {'comparison.json': encode(result,budget), 'comparison.html': render(result,budget)}
    c.require(sum(map(len,files.values())) <= MAX_OUTPUT, 'output byte limit exceeded')
    recheck(before,left,budget)
    recheck(after,right,budget)
    stage = Path(tempfile.mkdtemp(prefix='.'+destination.name+'.comparison-', dir=destination.parent))
    try:
        for name, raw in sorted(files.items()):
            budget.check()
            c.atomic_write(stage/name,raw)
        fd = os.open(stage,os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        summary = {'destination':str(destination), 'outcome':result['outcome'], 'complete':True,
                   'findings':len(result['findings']), 'bytes':sum(map(len,files.values())),
                   'files':{name:{'bytes':len(raw),'sha256':sha(raw)} for name,raw in sorted(files.items())}}
        budget.check()
        commit_directory(stage,destination)
        return summary
    finally:
        shutil.rmtree(stage,ignore_errors=True)
