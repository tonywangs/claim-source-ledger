"""Versioned, offline evidence storage. No network operations."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_SOURCE = 512 * 1024
MAX_LEDGER = 8 * 1024 * 1024
MAX_ITEMS = 1000
MAX_TEXT = 16384
ID = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')

class LedgerError(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise LedgerError(message)

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def read_bytes(path, limit):
    # Nonblocking open prevents a FIFO from hanging before the regular-file check.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'input must be a regular file')
        data = stream.read(limit + 1)
    require(len(data) <= limit, f'input exceeds {limit} bytes')
    return data

def read_source(path):
    return read_bytes(path, MAX_SOURCE).decode('utf-8')

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result

def load(path):
    return json.loads(read_bytes(path, MAX_LEDGER).decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda x: require(False, f'invalid JSON constant: {x}'))

def new():
    return {'version': 1, 'sources': [], 'claims': [], 'citations': []}

def string(value, limit=MAX_TEXT, empty=False):
    return (isinstance(value, str) and (empty or bool(value))
            and len(value) <= limit and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))

def schema(data):
    require(isinstance(data, dict) and set(data) == {'version','sources','claims','citations'}, 'invalid ledger fields')
    require(type(data['version']) is int and data['version'] == 1, 'unsupported ledger version')
    fields = {'sources': {'id','title','author','date','url','text','sha256'},
              'claims': {'id','text'},
              'citations': {'id','claim','source','start','end','quote','prefix','suffix','supersedes'}}
    for kind in fields:
        require(isinstance(data[kind], list) and len(data[kind]) <= MAX_ITEMS, f'invalid {kind} collection (limit {MAX_ITEMS})')
        for item in data[kind]:
            require(isinstance(item, dict) and set(item) == fields[kind], f'invalid {kind} fields')
            require(isinstance(item['id'], str) and ID.fullmatch(item['id']), 'invalid identifier')
            if kind == 'sources':
                require(string(item['text'], MAX_SOURCE, True), 'invalid source text')
                require(len(item['text'].encode('utf-8')) <= MAX_SOURCE, 'source byte limit exceeded')
                for key in ('title','author','date','url'):
                    require(string(item[key], empty=key != 'title'), f'invalid {key}')
                require(isinstance(item['sha256'], str) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'invalid hash')
            elif kind == 'claims':
                require(string(item['text']), 'invalid claim text')
            else:
                for key in ('claim','source'):
                    require(isinstance(item[key], str) and ID.fullmatch(item[key]), f'invalid {key} reference')
                require(item['supersedes'] is None or (isinstance(item['supersedes'], str) and ID.fullmatch(item['supersedes'])), 'invalid supersedes')
                require(type(item['start']) is int and type(item['end']) is int and 0 <= item['start'] < item['end'] <= MAX_SOURCE, 'invalid offsets')
                for key in ('quote','prefix','suffix'):
                    require(string(item[key], MAX_SOURCE if key == 'quote' else 80, key != 'quote'), f'invalid {key}')

def audit(data):
    issues = []
    def issue(code, ident='', severity='error'):
        issues.append({'code': code, 'id': ident, 'severity': severity})
    try:
        schema(data)
    except LedgerError as exc:
        return {'version': 1, 'ok': False, 'issues': [{'code':'schema', 'id':'', 'severity':'error', 'message':str(exc)}]}
    seen = set()
    for kind in ('sources','claims','citations'):
        for item in data[kind]:
            if item['id'] in seen:
                issue('duplicate_id', item['id'])
            seen.add(item['id'])
    sources = {s['id']: s for s in data['sources']}
    claims = {c['id'] for c in data['claims']}
    citations = {c['id']: c for c in data['citations']}
    linked = set()
    for source in sources.values():
        if digest(source['text']) != source['sha256']:
            issue('source_hash', source['id'])
    for c in data['citations']:
        ident = c['id']
        if c['claim'] not in claims:
            issue('dangling_claim', ident)
        else:
            linked.add(c['claim'])
        if c['source'] not in sources:
            issue('dangling_source', ident)
        else:
            text = sources[c['source']]['text']
            if c['end'] > len(text) or text[c['start']:c['end']] != c['quote']:
                issue('excerpt_mismatch', ident)
            if (text[max(0,c['start']-len(c['prefix'])):c['start']] != c['prefix']
                    or text[c['end']:c['end']+len(c['suffix'])] != c['suffix']):
                issue('context_mismatch', ident)
        if c['supersedes'] is not None:
            prev = citations.get(c['supersedes'])
            if prev is None:
                issue('dangling_supersedes', ident)
            elif prev['claim'] != c['claim'] or prev['quote'] != c['quote']:
                issue('invalid_relocation', ident)
            chain, cursor = set(), c
            while cursor and cursor['supersedes'] is not None:
                if cursor['id'] in chain:
                    issue('relocation_cycle', ident)
                    break
                chain.add(cursor['id'])
                cursor = citations.get(cursor['supersedes'])
    for ident in sorted(claims - linked):
        issue('claim_without_evidence', ident, 'warning')
    issues.sort(key=lambda i: (i['id'], i['code']))
    return {'version': 1, 'ok': not any(i['severity']=='error' for i in issues), 'issues': issues}

def valid(data):
    result = audit(data)
    require(result['ok'], 'ledger integrity errors: ' + json.dumps(result['issues']))

def get(data, kind, ident):
    found = [x for x in data[kind] if x['id'] == ident]
    require(len(found) == 1, f'unknown or duplicate {kind} id: {ident}')
    return found[0]

def append(data, kind, item):
    require(not any(x['id']==item['id'] for k in ('sources','claims','citations') for x in data[k]), 'identifier already exists')
    data[kind].append(item)
    valid(data)
    return item

def import_source(data, ident, text, title, author='', date='', url=''):
    return append(data, 'sources', dict(id=ident,text=text,title=title,author=author,date=date,url=url,sha256=digest(text)))

def matches(text, quote, limit=None):
    require(bool(quote), 'quote must not be empty')
    positions, start = [], 0
    while True:
        pos = text.find(quote, start)
        if pos < 0:
            return positions
        positions.append(pos)
        if limit is not None and len(positions) >= limit:
            return positions
        start = pos + 1

def cite(data, ident, claim, source, quote, start=None, supersedes=None):
    get(data, 'claims', claim)
    text = get(data, 'sources', source)['text']
    require(bool(quote), 'quote must not be empty')
    if start is None:
        found = matches(text, quote, limit=2)
        require(len(found)==1, 'quote is missing or ambiguous; supply --start for an ambiguous quote')
        start = found[0]
    require(type(start) is int and start >= 0 and text[start:start+len(quote)] == quote, 'quote disagrees with location')
    end = start + len(quote)
    return append(data, 'citations', dict(id=ident,claim=claim,source=source,start=start,end=end,quote=quote,
        prefix=text[max(0,start-80):start],suffix=text[end:end+80],supersedes=supersedes))

def classify(citation, text):
    # At most 64 displayed candidates plus one sentinel; keep repeated text bounded.
    found = matches(text, citation['quote'], limit=65)
    # Stable position takes precedence even when the same text also occurs elsewhere.
    if text[citation['start']:citation['start']+len(citation['quote'])] == citation['quote']:
        status = 'unchanged'
    elif len(found) == 1:
        status = 'uniquely_relocatable'
    elif found:
        status = 'ambiguous'
    else:
        status = 'missing'
    return {'citation':citation['id'], 'status':status, 'positions':found[:64], 'positions_truncated':len(found)>64}

def compare(data, source, target):
    get(data, 'sources', source)
    text = get(data, 'sources', target)['text']
    return {'version':1,'source':source,'target':target,'citations':[
        classify(c, text) for c in sorted(data['citations'], key=lambda c:c['id']) if c['source']==source]}

def relocate(data, ident, citation, target):
    old = get(data, 'citations', citation)
    require(old['source'] != target, 'target must be a different snapshot')
    text = get(data, 'sources', target)['text']
    result = classify(old, text)
    require(result['status'] in ('unchanged','uniquely_relocatable'), 'cannot accept an ambiguous or missing quotation')
    start = old['start'] if result['status']=='unchanged' else result['positions'][0]
    return cite(data, ident, old['claim'], target, old['quote'], start, old['id'])

@contextlib.contextmanager
def locked(path):
    # Stable lock inode; never unlink it while other processes might hold it.
    lock = Path(str(path)+'.lock')
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(lock, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)

def atomic_write(path, payload, replace=False):
    path = Path(path)
    require(not path.is_symlink(), 'refusing symlink output')
    require(replace or not path.exists(), 'output already exists')
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)  # atomic no-clobber publication
        # The rename/link is the commit point. No fallible operations follow it.
    finally:
        try:
            os.unlink(name)
        except OSError:
            # Cleanup must not turn an already committed mutation into a failure.
            # A crash or changed directory permissions can leave a private temp file.
            pass

def save(path, data, replace=False):
    valid(data)
    payload = encoded(data)
    require(len(payload) <= MAX_LEDGER, 'ledger byte limit exceeded')
    atomic_write(path, payload, replace)

def cleanup(path):
    """Remove abandoned temporary ledger files while the caller holds its lock."""
    path = Path(path)
    valid(load(path))  # Do not discard recovery material without a valid ledger.
    pattern = re.compile(re.escape('.'+path.name+'.tmp-') + r'[a-z0-9_]{8}\Z')
    removed = []
    for candidate in sorted(path.parent.iterdir()):
        if pattern.fullmatch(candidate.name) and stat.S_ISREG(candidate.lstat().st_mode):
            candidate.unlink()
            removed.append(candidate.name)
    return removed
