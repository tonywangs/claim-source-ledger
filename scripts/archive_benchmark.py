#!/usr/bin/env python3
"""Synthetic bounded archive workload. Stdlib only; no network or paid data."""
import hashlib
import json
from pathlib import Path
import platform
import random
import resource
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from claimledger import core as c, archive as a
from claimledger.report import render

SEED=991827
rng=random.Random(SEED)
started=time.perf_counter()
data=c.new()
for revision in range(20):
    background=''.join(rng.choices('abcde αβ中😀\n',k=9000))
    passages='\r\n'.join(f'Observed passage {revision}:{i}.' for i in range(6))
    text=background+'\r\n'+passages
    c.import_source(data,f's{revision}',text,f'Synthetic source {revision}',url='https://example.invalid/not-fetched')
    c.import_source(data,f'r{revision}','Revised introduction\r\n'+text,f'Revision {revision}')
    for i in range(6):
        ident=f'c{revision}_{i}'; quote=f'Observed passage {revision}:{i}.'
        c.append(data,'claims',{'id':ident,'text':f'Synthetic authored claim {revision}:{i}'})
        c.cite(data,f'q{revision}_{i}',ident,f's{revision}',quote)
        c.relocate(data,f'a{revision}_{i}',f'q{revision}_{i}',f'r{revision}')
setup_seconds=time.perf_counter()-started
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder); ledger=root/'ledger.json'; c.save(ledger,data)
    phases={}
    def timed(name,callback):
        start=time.perf_counter(); result=callback(); phases[name]=time.perf_counter()-start; return result
    first=root/'first.zip'; second=root/'second.zip'
    timed('export_seconds',lambda:a.export(ledger,first))
    verified=timed('verify_seconds',lambda:a.verify(first))
    timed('restore_seconds',lambda:a.restore(first,root/'restored'))
    restored=c.load(root/'restored/ledger.json')
    assert restored==data
    expected={s['sha256']:s['text'].encode() for s in data['sources']}
    assert {p.stem:p.read_bytes() for p in (root/'restored/snapshots').iterdir()}==expected
    timed('reexport_seconds',lambda:a.export(root/'restored/ledger.json',second))
    assert first.read_bytes()==second.read_bytes()
    report=timed('report_seconds',lambda:render(restored))
    summary={'seed':SEED,'sources':40,'claims':120,'citations':240,
             'setup_seconds':setup_seconds,'phases':phases,
             'elapsed_seconds':time.perf_counter()-started,
             'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
             'ledger_bytes':ledger.stat().st_size,'report_bytes':len(report),
             'report_sha256':hashlib.sha256(report).hexdigest(),
             'archive':verified,'byte_identical_reexport':True,'independent_records_and_snapshots_equal':True,
             'environment':{'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),
                            'libc':platform.libc_ver(),'zip_method':'ZIP_STORED','archive_format':1}}
print(json.dumps(summary,sort_keys=True,indent=2))
