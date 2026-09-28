#!/usr/bin/env python3
"""Deterministic bounded input; measured wall time and Linux peak process RSS."""
import hashlib
import json
from pathlib import Path
import resource
import platform
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from claimledger import core as c, manuscript as m

started=time.perf_counter()
data=c.new()
for n in range(12):
    text='Sample revision '+str(n)+'\r\n'+('😀 e\u0301 bounded sample passage\n'*700)
    # Construct fixtures directly to avoid measuring repeated mutation audits.
    data['sources'].append(dict(id=f's{n}',text=text,title=f'Synthetic source {n}',author='',date='',url='',sha256=c.digest(text)))
for n in range(300):
    data['claims'].append({'id':f'c{n}','text':f'Synthetic claim {n}: an illustrative statement, not a research result.'})
    source=data['sources'][n%12]; start=source['text'].index('bounded'); quote='bounded sample passage'
    end=start+len(quote)
    data['citations'].append(dict(id=f'q{n}',claim=f'c{n}',source=source['id'],start=start,end=end,quote=quote,
        prefix=source['text'][max(0,start-80):start],suffix=source['text'][end:end+80],supersedes=None))
spec={'version':1,'title':'Bounded synthetic manuscript','sections':[
    {'heading':f'Section {s+1}','claims':[{'id':f'c{n}','citations':[f'q{n}',f'q{n}']} for n in range(s*30,(s+1)*30)]}
    for s in range(10)]}
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder); ledger=root/'ledger.json'; specification=root/'spec.json'
    c.save(ledger,data); specification.write_bytes(c.encoded(spec))
    setup_seconds=time.perf_counter()-started
    build_start=time.perf_counter()
    m.export(ledger,specification,root/'first')
    build_seconds=time.perf_counter()-build_start
    m.export(ledger,specification,root/'second')
    files={str(p.relative_to(root/'first')):p.read_bytes() for p in (root/'first').rglob('*') if p.is_file()}
    second={str(p.relative_to(root/'second')):p.read_bytes() for p in (root/'second').rglob('*') if p.is_file()}
    assert files==second
    result={'environment':{'python':sys.version,'platform':platform.platform()},'workload':{'sources':12,'claims':300,'citation_selections':600,'sections':10},
      'input_bytes':ledger.stat().st_size,'setup_seconds':setup_seconds,'build_seconds':build_seconds,
      'total_seconds':time.perf_counter()-started,'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
      'rss_scope':'entire benchmark process, including setup and two builds; Linux ru_maxrss',
      'repeat_identical':True,'output_bytes':sum(map(len,files.values())),
      'artifacts':{name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in sorted(files.items())}}
print(json.dumps(result,indent=2,sort_keys=True))
