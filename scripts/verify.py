#!/usr/bin/env python3
"""Full local verification. Never installs dependencies or fetches source data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'results'
RESULTS.mkdir(exist_ok=True)
env=os.environ.copy()
if 'PLAYWRIGHT_BROWSERS_PATH' not in env and Path('/tmp/claimledger-browsers').is_dir():
    env['PLAYWRIGHT_BROWSERS_PATH']='/tmp/claimledger-browsers'
started=time.perf_counter()
log=[]
def run(args):
    p=subprocess.run(args,cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log.append('$ '+' '.join(args)+'\n'+p.stdout)
    print(p.stdout,end='',flush=True)
    (RESULTS/'tests.log').write_text('\n'.join(log),encoding='utf-8')
    if p.returncode:
        raise SystemExit(p.returncode)
    return p.stdout

# Remove old summary evidence first; a failed rerun must not look successful.
for name in ('verification.json','benchmark.json','browser.json','archive-benchmark.json'):
    (RESULTS/name).unlink(missing_ok=True)
run([sys.executable,'-m','unittest','discover','-s','tests','-v'])
browser=json.loads(run(['node','tests/browser.cjs']))
(RESULTS/'browser.json').write_text(json.dumps(browser,indent=2,sort_keys=True)+'\n',encoding='utf-8')
benchmark=json.loads(run([sys.executable,'scripts/benchmark.py']))
(RESULTS/'benchmark.json').write_text(json.dumps(benchmark,indent=2,sort_keys=True)+'\n',encoding='utf-8')
archive_benchmark=json.loads(run([sys.executable,'scripts/archive_benchmark.py']))
(RESULTS/'archive-benchmark.json').write_text(json.dumps(archive_benchmark,indent=2,sort_keys=True)+'\n',encoding='utf-8')
with tempfile.TemporaryDirectory() as folder:
    example=Path(folder)/'example'
    run([sys.executable,'scripts/example.py',str(example)])
    audited=json.loads(run([sys.executable,'-m','claimledger','--ledger',str(example/'example.json'),'audit']))
    assert audited['ok']
    assert audited['issues']==[{'code':'claim_without_evidence','id':'unverified','severity':'warning'}]
    example_bytes=(example/'example.html').stat().st_size
summary={'passed':True,'elapsed_seconds':time.perf_counter()-started,
         'oracle_seed':728193,'oracle_cases':480,'archive_seed':390274,'archive_round_trips':240,'example_report_bytes':example_bytes,
         'checks':['unit and seeded oracle','isolated installed CLI with socket operations blocked',
                   'network-blocked Chromium on restored report','240 archive round trips and hostile/failure regressions','bounded archive workload','bounded workload','synthetic CLI example']}
(RESULTS/'verification.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
