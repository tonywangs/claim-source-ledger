#!/usr/bin/env python3
"""Bounded reproducible comparison workload; measured process RSS includes setup."""
import copy
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
from claimledger import core as c, manuscript as m, comparison as d

SEED=441908

def main():
    started=time.perf_counter(); rng=random.Random(SEED)
    data=c.new()
    for n in range(12):
        text=f'Synthetic source {n}\r\n'+('😀 e\u0301 bounded excerpt\r\n'*600)
        data['sources'].append(dict(id=f's{n}',text=text,title=f'Synthetic revision {n}',author='',date='',url='',sha256=c.digest(text)))
    for n in range(300):
        data['claims'].append(dict(id=f'c{n}',text=f'Synthetic authored claim {n}. This is sample data.'))
        source=data['sources'][n%12]; start=source['text'].index('bounded'); quote='bounded excerpt'; end=start+len(quote)
        data['citations'].append(dict(id=f'q{n}',claim=f'c{n}',source=source['id'],start=start,end=end,quote=quote,
            prefix=source['text'][max(0,start-80):start],suffix=source['text'][end:end+80],supersedes=None))
    spec={'version':1,'title':'Bounded comparison sample','sections':[
        {'heading':f'Section {s}', 'claims':[{'id':f'c{n}','citations':[f'q{n}',f'q{n}']} for n in range(s*30,(s+1)*30)]}
        for s in range(10)]}
    revised,second=copy.deepcopy(data),copy.deepcopy(spec)
    for claim in rng.sample(revised['claims'],100): claim['text']+=' Revised authored wording.'
    second['sections'].reverse()
    for source in revised['sources']:
        source['text']='Revision\r\n'+source['text']; source['sha256']=c.digest(source['text'])
    for citation in revised['citations']:
        citation['start']+=10; citation['end']+=10
        text=next(s['text'] for s in revised['sources'] if s['id']==citation['source'])
        citation['prefix']=text[max(0,citation['start']-80):citation['start']]
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for label,ledger,specification in [('before',data,spec),('after',revised,second)]:
            c.save(root/(label+'.json'),ledger); (root/(label+'-spec.json')).write_bytes(c.encoded(specification))
            m.export(root/(label+'.json'),root/(label+'-spec.json'),root/label)
        def files(path): return {p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob('*') if p.is_file()}
        inputs={label:files(root/label) for label in ('before','after')}
        setup=time.perf_counter()-started; start=time.perf_counter()
        d.export(root/'before',root/'after',root/'comparison'); elapsed=time.perf_counter()-start
        d.export(root/'before',root/'after',root/'repeat')
        output=files(root/'comparison'); assert output==files(root/'repeat')
        assert inputs=={label:files(root/label) for label in ('before','after')}
        report=json.loads(output['comparison.json'])
        result={'environment':{'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),'libc':platform.libc_ver()},
            'seed':SEED,'workload':{'claims_per_bundle':300,'sources_per_bundle':12,'citation_selections_per_bundle':600,'sections_per_bundle':10,'text_changes':100},
            'input_bytes':{label:sum(map(len,values.values())) for label,values in inputs.items()},
            'input_hashes':{label:report['inputs'][label]['sha256'] for label in inputs},
            'setup_seconds':setup,'comparison_seconds':elapsed,'total_seconds':time.perf_counter()-started,
            'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'rss_scope':'entire process including setup, two manuscript builds, input copies and two comparisons; Linux ru_maxrss',
            'repeat_identical':True,'inputs_unchanged':True,'output_bytes':sum(map(len,output.values())),
            'findings':len(report['findings']),'summary':report['summary'],
            'artifacts':{name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in sorted(output.items())}}
        print(json.dumps(result,indent=2,sort_keys=True))


if __name__=='__main__': main()
