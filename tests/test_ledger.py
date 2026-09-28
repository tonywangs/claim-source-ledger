import copy
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from claimledger import core as c
from claimledger.report import render

ROOT = Path(__file__).resolve().parents[1]

class LedgerTests(unittest.TestCase):
    def fixture(self):
        data = c.new()
        c.import_source(data,'s1','α😀 First\r\nSecond e\u0301.','Test')
        c.append(data,'claims',{'id':'c1','text':'An authored claim'})
        c.cite(data,'q1','c1','s1','Second')
        return data

    def test_seeded_independent_oracle(self):
        """Brute-force tuple windows, not production str.find or classify."""
        rng = random.Random(728193)
        statuses = set()
        for i in range(480):
            prefix = ''.join(rng.choices(['α','😀','e\u0301','\r\n','\n',' ','中'], k=rng.randrange(1,14)))
            quote = f'PASSAGE-{i}'
            original = prefix + quote + '\r\nEnding'
            start = len(prefix)
            variants = [original, 'INSERTED'+original, original+quote,
                        quote+'---'+quote, original.replace(quote,'changed'),
                        original[start:], original.replace('\r\n','\n'), '']
            revised = variants[i % len(variants)]
            chars, needle = tuple(revised), tuple(quote)
            positions = [j for j in range(len(chars)-len(needle)+1) if chars[j:j+len(needle)] == needle]
            expected = ('unchanged' if tuple(revised[start:start+len(quote)]) == needle else
                        'missing' if len(positions)==0 else
                        'uniquely_relocatable' if len(positions)==1 else 'ambiguous')
            data = c.new()
            c.import_source(data,'s1',original,'Original')
            c.import_source(data,'s2',revised,'Revision')
            c.append(data,'claims',{'id':'c1','text':'Sample'})
            citation = c.cite(data,'q1','c1','s1',quote,start)
            self.assertEqual((citation['start'],citation['end']),(start,start+len(quote)))
            self.assertTrue(c.audit(data)['ok'])
            result = c.compare(data,'s1','s2')['citations'][0]
            self.assertEqual(result,{'citation':'q1','status':expected,'positions':positions,'positions_truncated':False}, i)
            statuses.add(expected)
            old = copy.deepcopy(citation)
            if expected in ('unchanged','uniquely_relocatable'):
                new = c.relocate(data,'q2','q1','s2')
                self.assertEqual(revised[new['start']:new['end']],quote)
                self.assertEqual(citation,old)
            else:
                with self.assertRaises(c.LedgerError): c.relocate(data,'q2','q1','s2')
            # Independently inject an invalid identifier/reference/quotation in every case.
            bad = copy.deepcopy(data)
            mode = i % 4
            if mode == 0:
                bad['claims'].append(copy.deepcopy(bad['claims'][0])); code = 'duplicate_id'
            elif mode == 1:
                bad['citations'][0]['source']='absent'; code = 'dangling_source'
            elif mode == 2:
                bad['citations'][0]['quote']='wrong'; code = 'excerpt_mismatch'
            else:
                bad['sources'][0]['text']+='!'; code = 'source_hash'
            self.assertIn(code,{x['code'] for x in c.audit(bad)['issues']})
        self.assertEqual(statuses,{'unchanged','uniquely_relocatable','ambiguous','missing'})

    def test_overlapping_and_ambiguous(self):
        d = c.new(); c.import_source(d,'s','aaaa','Title'); c.append(d,'claims',{'id':'c','text':'Claim'})
        self.assertEqual(c.matches('aaaa','aa'),[0,1,2])
        with self.assertRaises(c.LedgerError): c.cite(d,'q','c','s','aa')
        self.assertEqual(c.cite(d,'q','c','s','aa',1)['start'],1)
        with self.assertRaises(c.LedgerError): c.cite(d,'q2','c','s','aa',-1)
        with self.assertRaises(c.LedgerError): c.cite(d,'q2','c','s','',0)

    def test_audit_corruptions(self):
        for key,value,code in [('claim','absent','dangling_claim'),('source','absent','dangling_source'),
                              ('quote','wrong','excerpt_mismatch'),('prefix','wrong','context_mismatch'),
                              ('suffix','wrong','context_mismatch'),('supersedes','absent','dangling_supersedes')]:
            d = self.fixture(); d['citations'][0][key]=value
            self.assertIn(code,{i['code'] for i in c.audit(d)['issues']})
        d=self.fixture(); d['citations'][0]['supersedes']='q1'
        self.assertIn('relocation_cycle',{i['code'] for i in c.audit(d)['issues']})
        d=self.fixture(); d['claims'].append({'id':'c2','text':'Unlinked'})
        self.assertEqual(c.audit(d)['issues'],[{'code':'claim_without_evidence','id':'c2','severity':'warning'}])
        self.assertEqual(c.encoded(c.audit(d)),c.encoded(c.audit(copy.deepcopy(d))))

    def test_malformed_schema(self):
        malformed = [None,[],{}, {'version':True,'sources':[],'claims':[],'citations':[]}]
        for field,value in [('start',True),('start',-1),('end',1.2),('quote',''),('id','<script>'),('prefix','x'*81),('quote','\ud800')]:
            d=self.fixture(); d['citations'][0][field]=value; malformed.append(d)
        for d in malformed:
            self.assertFalse(c.audit(d)['ok'])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.json'
            for raw in [b'{"version":1,"version":1}', b'NaN', b'\xff', b'{', b'['*2000]:
                p.write_bytes(raw)
                with self.assertRaises((ValueError,RecursionError)): c.load(p)

    def test_limits(self):
        d=c.new(); c.import_source(d,'s','a'*c.MAX_SOURCE,'Boundary')
        self.assertTrue(c.audit(d)['ok'])
        with self.assertRaises(c.LedgerError): c.import_source(c.new(),'s','😀'*(c.MAX_SOURCE//4+1),'Too large')
        d=c.new(); d['claims']=[{'id':f'c{i}','text':'x'} for i in range(c.MAX_ITEMS)]
        self.assertTrue(c.audit(d)['ok'])
        d['claims'].append({'id':'extra','text':'x'}); self.assertFalse(c.audit(d)['ok'])
        d=c.new(); d['claims']=[{'id':'c','text':'a'*(c.MAX_TEXT+1)}]; self.assertFalse(c.audit(d)['ok'])
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'large'; p.write_bytes(b'a'*(c.MAX_SOURCE+1))
            with self.assertRaises(c.LedgerError): c.read_source(p)
            p.write_bytes(b' '*(c.MAX_LEDGER+1))
            with self.assertRaises(c.LedgerError): c.load(p)
            p.write_bytes(b'previous')
            with patch.object(c,'MAX_LEDGER',10):
                with self.assertRaises(c.LedgerError): c.save(p,c.new(),replace=True)
            self.assertEqual(p.read_bytes(),b'previous')

    def test_atomic_failures_and_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger'; c.save(p,self.fixture()); old=p.read_bytes()
            for target in ('fsync','replace'):
                with patch.object(os,target,side_effect=OSError('simulated interruption')):
                    with self.assertRaises(OSError): c.save(p,c.new(),replace=True)
                self.assertEqual(p.read_bytes(),old)
                self.assertEqual(list(Path(folder).glob('.*.tmp-*')),[])
            with patch.object(os,'link',side_effect=OSError('simulated interruption')):
                with self.assertRaises(OSError): c.save(Path(folder)/'new',c.new())
            self.assertEqual(list(Path(folder).glob('.*.tmp-*')),[])
            with self.assertRaises(c.LedgerError): c.save(p,c.new())
            link=Path(folder)/'symlink'; link.symlink_to(p)
            with self.assertRaises(c.LedgerError): c.save(link,c.new(),replace=True)
            self.assertEqual(p.read_bytes(),old)
            with c.locked(p):
                with self.assertRaises(BlockingIOError):
                    with c.locked(p): pass
            with c.locked(p): pass

    def test_killed_writer_keeps_valid_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger'; c.save(p,self.fixture()); old=p.read_bytes()
            # Kill at the commit boundary after the temporary file has been fsynced.
            script = '''import os,signal,sys
from claimledger import core
os.replace=lambda *a: os.kill(os.getpid(),signal.SIGKILL)
with core.locked(sys.argv[1]): core.save(sys.argv[1],core.new(),replace=True)
'''
            proc=subprocess.run([sys.executable,'-c',script,str(p)],cwd=ROOT,capture_output=True)
            self.assertEqual(proc.returncode,-9)
            self.assertEqual(p.read_bytes(),old); self.assertTrue(c.audit(c.load(p))['ok'])
            with c.locked(p):
                leftovers=list(Path(folder).glob('.ledger.tmp-*'))
                self.assertEqual(len(leftovers),1)
                self.assertEqual(c.cleanup(p),[leftovers[0].name])
            self.assertEqual(list(Path(folder).glob('.ledger.tmp-*')),[])

    def test_bounded_repeated_passage_and_nonregular_input(self):
        result=c.classify({'id':'q','quote':'a','start':1000},'a'*c.MAX_SOURCE)
        self.assertEqual(result['status'],'unchanged')
        self.assertEqual(len(result['positions']),64)
        self.assertTrue(result['positions_truncated'])
        with tempfile.TemporaryDirectory() as folder:
            fifo=Path(folder)/'fifo'; os.mkfifo(fifo)
            with self.assertRaises(c.LedgerError): c.read_source(fifo)

    def test_hostile_report(self):
        d=self.fixture(); d['claims'][0]['text']='</script><img src=https://example.invalid onerror=alert(1)>'
        html=render(d).decode()
        self.assertNotIn('<img',html); self.assertIn('&lt;img',html)
        self.assertEqual(render(d),render(d))
        with patch('claimledger.report.MAX_LEDGER',10):
            with self.assertRaises(c.LedgerError): render(d)

class InstalledWorkflow(unittest.TestCase):
    def test_offline_installed_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); prefix=root/'installation'
            subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--prefix',str(prefix)],check=True,capture_output=True)
            executable=prefix/'bin/claimledger'
            ledger=root/'ledger.json'
            # Isolated Python, no checkout import path. Audit hook rejects every socket operation.
            runner='''import sys,runpy
sys.addaudithook(lambda event,args: (_ for _ in ()).throw(RuntimeError("network forbidden")) if event.startswith("socket.") else None)
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name="__main__")
'''
            def cli(*args,code=0):
                p=subprocess.run([sys.executable,'-I','-c',runner,str(executable),'--ledger',str(ledger),*args],cwd=root,capture_output=True,text=True)
                self.assertEqual(p.returncode,code,p.stderr+p.stdout)
                return json.loads(p.stdout) if p.stdout else None
            cli('init'); original=ledger.read_bytes(); cli('init',code=2); self.assertEqual(ledger.read_bytes(),original)
            source=root/'source.txt'; source.write_bytes('😀\r\nCanal opened. Canal opened.\r\n'.encode())
            cli('import','s1',str(source),'--title','Synthetic canal notice','--url','https://example.invalid/never-fetched')
            cli('claim','c1','The synthetic notice repeats the opening.')
            before=ledger.read_bytes(); cli('cite','q1','c1','s1','Canal opened.',code=2); self.assertEqual(ledger.read_bytes(),before)
            cli('cite','q1','c1','s1','Canal opened.','--start','3')
            self.assertTrue(cli('audit')['ok'])
            revision=root/'revision.txt'; revision.write_text('Revised: Canal opened.',encoding='utf-8')
            cli('import','s2',str(revision),'--title','Synthetic revision')
            self.assertEqual(cli('compare','s1','s2')['citations'][0]['status'],'uniquely_relocatable')
            before=ledger.read_bytes(); cli('compare','s1','s2'); self.assertEqual(ledger.read_bytes(),before)
            cli('accept','q2','q1','s2'); self.assertEqual(len(c.load(ledger)['citations']),2)
            report=root/'report.html'; cli('report',str(report)); rendered=report.read_bytes()
            cli('report',str(report),code=2); self.assertEqual(report.read_bytes(),rendered)
            cli('report',str(ledger),code=2); self.assertTrue(cli('audit')['ok'])
            before=ledger.read_bytes()
            for args in [('claim','c1','Duplicate'),('claim','bad id','Bad'),('cite','q3','missing','s1','Canal opened.'),('accept','q3','q1','s1')]:
                cli(*args,code=2); self.assertEqual(ledger.read_bytes(),before)
            source.write_bytes(b'\xff'); cli('import','s3',str(source),'--title','Bad',code=2); self.assertEqual(ledger.read_bytes(),before)
            source.write_bytes(b'a'*(c.MAX_SOURCE+1)); cli('import','s3',str(source),'--title','Oversize',code=2); self.assertEqual(ledger.read_bytes(),before)
            ledger.write_text('{malformed',encoding='utf-8'); self.assertFalse(cli('audit',code=1)['ok'])
            cli('claim','c2','No write',code=2); self.assertEqual(ledger.read_text(),'{malformed')
            ledger.write_bytes(before)
            result=subprocess.run([str(executable),'--ledger',str(ledger),'audit'],cwd=root,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(list(root.glob('.*.tmp-*')),[])

if __name__ == '__main__':
    unittest.main()
