#!/usr/bin/env python3
"""Bounded reproducible in-process workload; not a throughput claim for all ledgers."""
import json
from pathlib import Path
import platform
import random
import resource
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from claimledger import core as c
from claimledger.report import render

rng=random.Random(42051)
started=time.perf_counter()
d=c.new()
for i in range(16):
    lines=[f'Record {i:02d}-{j:03d}: '+''.join(rng.choices('abcdef αβ中😀',k=48))+'.\r\n' for j in range(80)]
    c.import_source(d,f's{i}',''.join(lines),f'Synthetic archive {i}',author='Seeded generator')
for i in range(128):
    c.append(d,'claims',{'id':f'c{i}','text':f'Synthetic claim {i}: inspect the cited record.'})
    source=d['sources'][i%16]
    quote=source['text'].split('\r\n')[i//16]
    c.cite(d,f'q{i}',f'c{i}',source['id'],quote)
author_seconds=time.perf_counter()-started
with tempfile.TemporaryDirectory() as folder:
    p=Path(folder)/'collection.json'
    c.save(p,d)
    load_start=time.perf_counter(); loaded=c.load(p); result=c.audit(loaded)
    audit_seconds=time.perf_counter()-load_start
    assert result['ok'] and not result['issues']
    report_start=time.perf_counter(); report=render(loaded)
    report_seconds=time.perf_counter()-report_start
    c.atomic_write(Path(folder)/'report.html',report)
    revision='Inserted heading\n'+d['sources'][0]['text']
    compared=[c.classify(x,revision) for x in d['citations'] if x['source']=='s0']
    assert all(x['status']=='uniquely_relocatable' for x in compared)
    output={'workload':{'seed':42051,'sources':16,'claims':128,'citations':128,'records_per_source':80},
            'timing_seconds':{'authoring':author_seconds,'load_and_audit':audit_seconds,'render':report_seconds,'total':time.perf_counter()-started},
            'ledger_bytes':p.stat().st_size,'report_bytes':len(report),
            'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            'environment':{'python':platform.python_version(),'platform':platform.platform(),'machine':platform.machine()},
            'scope':'One fresh Python process, in-process authoring with validation after every append; RSS includes interpreter. Installed CLI and browser tested separately.'}
print(json.dumps(output,indent=2,sort_keys=True))
