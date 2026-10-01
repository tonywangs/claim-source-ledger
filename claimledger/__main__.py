import argparse
import json
from pathlib import Path
import sys
from . import core, archive, manuscript, comparison
from .report import render

def parser():
    p = argparse.ArgumentParser(description='Offline exact-excerpt evidence ledger. Integrity is not truth.')
    p.add_argument('--ledger', type=Path, default=Path('ledger.json'))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init', help='create an empty ledger; never overwrite')
    imp = sub.add_parser('import', help='import a local UTF-8 snapshot')
    imp.add_argument('id'); imp.add_argument('file', type=Path)
    imp.add_argument('--title', required=True)
    for name in ('author','date','url'):
        imp.add_argument('--'+name, default='')
    claim = sub.add_parser('claim')
    claim.add_argument('id'); claim.add_argument('text')
    cite = sub.add_parser('cite')
    for name in ('id','claim','source','quote'):
        cite.add_argument(name)
    cite.add_argument('--start', type=int, help='zero-based Unicode code-point offset')
    sub.add_parser('audit', help='deterministic JSON; exit 1 for errors, warnings do not fail')
    sub.add_parser('cleanup', help='remove abandoned ledger temporary files under the writer lock')
    comp = sub.add_parser('compare')
    comp.add_argument('source'); comp.add_argument('target')
    reloc = sub.add_parser('accept', help='append a relocation, retaining the original citation')
    reloc.add_argument('id'); reloc.add_argument('citation'); reloc.add_argument('target')
    report = sub.add_parser('report')
    report.add_argument('output', type=Path)
    exp = sub.add_parser('export', help='create a deterministic offline archive; never overwrite')
    exp.add_argument('output', type=Path)
    check = sub.add_parser('verify', help='verify an archive offline, without restoring it')
    check.add_argument('archive', type=Path)
    restore = sub.add_parser('restore', help='restore an archive into a new directory (Linux)')
    restore.add_argument('archive', type=Path)
    restore.add_argument('destination', type=Path)
    ms = sub.add_parser("manuscript", help="build an ordered manuscript into a fresh directory (Linux)")
    ms.add_argument("specification", type=Path)
    ms.add_argument("destination", type=Path)
    diff = sub.add_parser('manuscript-compare', help='compare two saved manuscript bundles offline into a fresh directory')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('destination', type=Path)
    diff.add_argument('--seconds', type=float, default=comparison.MAX_SECONDS)
    diff.add_argument('--work', type=int, default=comparison.MAX_WORK)
    return p

def run(a):
    if a.command == 'manuscript-compare':
        print(core.encoded(comparison.export(a.before, a.after, a.destination, a.seconds, a.work)).decode(), end='')
        return 0
    path = a.ledger.absolute()
    if a.command == 'manuscript':
        print(core.encoded(manuscript.export(path, a.specification, a.destination)).decode(), end='')
        return 0
    if a.command in ('export', 'verify', 'restore'):
        if a.command == 'export':
            result = archive.export(path, a.output)
        elif a.command == 'verify':
            result = archive.verify(a.archive)
        else:
            result = archive.restore(a.archive, a.destination)
        print(core.encoded(result).decode(), end='')
        return 0
    if a.command == 'cleanup':
        with core.locked(path):
            print(core.encoded({'removed':core.cleanup(path)}).decode(), end='')
        return 0
    if a.command == 'audit':
        try:
            result = core.audit(core.load(path))
        except (core.LedgerError, ValueError, OSError, UnicodeError, RecursionError) as exc:
            result = {'version':1,'ok':False,'issues':[{'code':'unreadable_ledger','id':'','severity':'error','message':str(exc)}]}
        print(core.encoded(result).decode(), end='')
        return 0 if result['ok'] else 1
    if a.command in ('report','compare'):
        data = core.load(path); core.valid(data)
        if a.command == 'compare':
            result = core.compare(data, a.source, a.target)
        else:
            core.atomic_write(a.output, render(data))
            result = {'report':str(a.output)}
    else:
        with core.locked(path):
            if a.command == 'init':
                data = core.new(); result = {'ledger':str(path)}
            else:
                data = core.load(path); core.valid(data)
                if a.command == 'import':
                    result = core.import_source(data,a.id,core.read_source(a.file),a.title,a.author,a.date,a.url)
                    result = {k:v for k,v in result.items() if k != 'text'}
                elif a.command == 'claim':
                    result = core.append(data,'claims',{'id':a.id,'text':a.text})
                elif a.command == 'cite':
                    result = core.cite(data,a.id,a.claim,a.source,a.quote,a.start)
                elif a.command == 'accept':
                    result = core.relocate(data,a.id,a.citation,a.target)
            core.save(path,data,replace=a.command != 'init')
    print(core.encoded(result).decode(), end='')
    return 0

def main():
    try:
        return run(parser().parse_args())
    except (core.LedgerError, OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(f'claimledger: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
