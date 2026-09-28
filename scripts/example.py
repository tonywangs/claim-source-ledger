#!/usr/bin/env python3
"""Build a synthetic example into a NEW directory through the public CLI."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('output',type=Path)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
ledger=a.output/'example.json'
def cli(*args):
    subprocess.run([sys.executable,'-m','claimledger','--ledger',str(ledger),*args],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
cli('init')
cli('import','notice',str(ROOT/'examples/notice.txt'),'--title','Synthetic Marshbridge notice','--author','Invented Gazette','--date','1842-05-14','--url','https://example.invalid/synthetic-notice')
cli('claim','opening','The synthetic notice says the east canal opened to freight.')
cli('cite','opening-original','opening','notice','The east canal opened to freight on Monday.')
cli('claim','expectation','The council expected reduced cart traffic; the notice supplies no measurements.')
cli('cite','expectation-original','expectation','notice','The council expects the new route to reduce cart traffic.')
cli('cite','measurement-original','expectation','notice','No measurements of travel times were reported.')
cli('claim','unverified','Unverified hypothesis: the opening shortened journeys. No supporting evidence is linked.')
cli('import','revision',str(ROOT/'examples/revised-notice.txt'),'--title','Synthetic corrected transcription')
cli('compare','notice','revision')
cli('accept','opening-relocated','opening-original','revision')
cli('report',str(a.output/'example.html'))
print(a.output/'example.html')
