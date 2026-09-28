"""Independent ordered resolver, failure injection, and installed offline workflow."""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from claimledger import core as c, manuscript as m, archive as a

ROOT = Path(__file__).resolve().parents[1]
SEED = 681203
CASES = 240
HOSTILE = '<img src="https://example.invalid/x" onerror="alert(1)"><script>window.pwned=1</script> & [x](javascript:alert(1))'


def fixture(index=0):
    rng = random.Random(SEED + index)
    data = c.new()
    quote = 'Exact 😀 e\u0301 中 '+HOSTILE
    prefix = ''.join(rng.choices(['😀', 'α', '\r', '\n', '\r\n', '\ufeff'], k=20))
    for sid, text in [('v1', prefix+quote+'\r\n'+quote), ('v2', 'Revised\r\n'+quote+'\n終')]:
        c.import_source(data, sid, text, 'Title '+HOSTILE, 'Sample author', '', 'https://example.invalid')
    for ident in ('c1','c2','uncited'):
        c.append(data, 'claims', {'id': ident, 'text': ident+' authored '+HOSTILE})
    c.cite(data, 'q1', 'c1', 'v1', quote, len(prefix))
    c.relocate(data, 'q2', 'q1', 'v2')
    c.cite(data, 'q3', 'c2', 'v1', quote, len(prefix)+len(quote)+2)
    sections = [{'heading': 'First '+HOSTILE, 'claims': [{'id':'c1','citations':['q2','q1','q2']}, {'id':'uncited','citations':[]}]},
                {'heading': 'Second 😀', 'claims': [{'id':'c2','citations':['q3']}, {'id':'c1','citations':[]}]}]
    rng.shuffle(sections)
    for section in sections:
        rng.shuffle(section['claims'])
    return data, {'version':1,'title':'Sample manuscript '+str(index), 'sections':sections}


def reference(data, spec):
    # Deliberately linear lookups and tuple windows, no production resolver/audit.
    rows, selected = [], []
    for section in spec['sections']:
        found = []
        for item in section['claims']:
            claim = next(x for x in data['claims'] if x['id']==item['id'])
            for ident in item['citations']:
                cite = next(x for x in data['citations'] if x['id']==ident)
                assert cite['claim'] == claim['id']
                src = next(x for x in data['sources'] if x['id']==cite['source'])
                assert hashlib.sha256(src['text'].encode()).hexdigest() == src['sha256']
                assert tuple(cite['quote']) == tuple(src['text'])[cite['start']:cite['end']]
                if cite not in selected:
                    selected.append(copy.deepcopy(cite))
            found.append({'id':claim['id'],'text':claim['text'],'citations':item['citations'][:], 'uncited':not item['citations']})
        rows.append({'heading':section['heading'],'claims':found})
    return rows, sorted(selected, key=lambda x:x['id'])


class ManuscriptTests(unittest.TestCase):
    def test_seeded_reference_and_repeatability(self):
        for index in range(CASES):
            with self.subTest(case=index):
                data, spec = fixture(index)
                before = copy.deepcopy((data,spec))
                expected, citations = reference(data,spec)
                files = m.build(data,spec)
                self.assertEqual(files,m.build(data,spec))
                self.assertEqual((data,spec),before)
                manifest = json.loads(files['manifest.json'])
                self.assertEqual(manifest['sections'],expected)
                self.assertEqual(manifest['citations'],citations)
                self.assertEqual(manifest['specification'],spec)
                self.assertEqual([s['id'] for s in manifest['sources']],['v1','v2'])
                for name, info in manifest['files'].items():
                    self.assertEqual(info,{'bytes':len(files[name]),'sha256':hashlib.sha256(files[name]).hexdigest()})
                for source in data['sources']:
                    self.assertEqual(files['snapshots/'+source['sha256']+'.txt'],source['text'].encode())
                self.assertNotIn(b'<img',files['manuscript.html'])
                self.assertNotIn(b'<script>',files['manuscript.html'])
                self.assertNotIn(b'[x](javascript:',files['manuscript.md'])
                # Missing selections must fail, even in otherwise valid randomized cases.
                broken = copy.deepcopy(spec)
                broken['sections'][0]['claims'][0]['citations']=['absent']
                with self.assertRaises(c.LedgerError): m.build(data,broken)
                broken['sections'][0]['claims'][0]['id']='absent'
                with self.assertRaises(c.LedgerError): m.build(data,broken)

    def test_validation_and_limits(self):
        data,spec = fixture()
        for key,value in [('version',2),('version',True),('title',''),('sections',[]),('extra',1)]:
            bad=copy.deepcopy(spec); bad[key]=value
            with self.assertRaises(c.LedgerError): m.build(data,bad)
        for key,value in [('source','absent'),('quote','wrong'),('start',True),('end',99999),('prefix','wrong')]:
            bad=copy.deepcopy(data); bad['citations'][0][key]=value
            with self.assertRaises(c.LedgerError): m.build(bad,spec)
        bad=copy.deepcopy(data); bad['sources'][0]['text']+='altered'
        with self.assertRaises(c.LedgerError): m.build(bad,spec)
        bad=copy.deepcopy(data); bad['version']=2
        with self.assertRaises(c.LedgerError): m.build(bad,spec)
        bad=copy.deepcopy(spec); bad['sections'][0]['claims']=[{'id':'c2','citations':['q1']}]
        with self.assertRaisesRegex(c.LedgerError,'another claim'): m.build(data,bad)
        for name in ('MAX_SPEC','MAX_CLAIMS','MAX_SELECTIONS','MAX_SOURCES','MAX_SNAPSHOT_BYTES','MAX_OUTPUT','MAX_SECTIONS'):
            with patch.object(m,name,1):
                with self.assertRaises(c.LedgerError): m.build(data,spec)
        files=m.build(data,spec); size=sum(map(len,files.values()))
        with patch.object(m,'MAX_OUTPUT',size): self.assertEqual(files,m.build(data,spec))
        with patch.object(m,'MAX_OUTPUT',size-1):
            with self.assertRaises(c.LedgerError): m.build(data,spec)

    def inputs(self,root):
        data,spec=fixture()
        ledger, specification = root/'ledger.json',root/'spec.json'
        c.save(ledger,data); specification.write_bytes(c.encoded(spec))
        return ledger,specification

    def test_input_lock_and_unchanged_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ledger,spec=self.inputs(root); dest=root/'out'
            before=(ledger.read_bytes(),spec.read_bytes())
            with c.locked(ledger):
                with self.assertRaises(BlockingIOError): m.export(ledger,spec,dest)
            self.assertFalse(dest.exists())
            m.export(ledger,spec,dest)
            self.assertEqual(before,(ledger.read_bytes(),spec.read_bytes()))
            original=m.build
            def mutate(data,specification):
                result=original(data,specification); ledger.write_bytes(c.encoded(c.new())); return result
            with patch.object(m,'build',side_effect=mutate):
                with self.assertRaisesRegex(c.LedgerError,'changed during'): m.export(ledger,spec,root/'changed')
            self.assertFalse((root/'changed').exists())

    def test_transaction_failures_and_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ledger,spec=self.inputs(root); dest=root/'out'
            for target in ((c,'encoded'),(c,'atomic_write'),(os,'fsync'),(m,'commit_directory')):
                for error in (OSError('interrupted'),KeyboardInterrupt(),SystemExit(1)):
                    with patch.object(*target,side_effect=error):
                        with self.assertRaises(type(error)): m.export(ledger,spec,dest)
                    self.assertFalse(dest.exists())
                    self.assertEqual(list(root.glob('.out.manuscript-*')),[])
            encode=c.encoded
            def serialization_failure(value):
                if isinstance(value,dict) and value.get('format')=='claim-source-ledger-manuscript':
                    raise TypeError('manifest serialization failed')
                return encode(value)
            with patch.object(c,'encoded',side_effect=serialization_failure):
                with self.assertRaises(TypeError): m.export(ledger,spec,dest)
            self.assertFalse(dest.exists()); self.assertEqual(list(root.glob('.out.manuscript-*')),[])
            original=c.atomic_write; calls=[]
            def partial(*args,**kwargs):
                calls.append(args)
                if len(calls)==2: raise OSError('second write failed')
                return original(*args,**kwargs)
            with patch.object(c,'atomic_write',side_effect=partial):
                with self.assertRaises(OSError): m.export(ledger,spec,dest)
            self.assertFalse(dest.exists()); self.assertEqual(list(root.glob('.out.manuscript-*')),[])
            original_commit=m.commit_directory
            def race(stage,destination):
                destination.mkdir(); (destination/'keep').write_text('keep'); original_commit(stage,destination)
            with patch.object(m,'commit_directory',side_effect=race):
                with self.assertRaises(FileExistsError): m.export(ledger,spec,dest)
            self.assertEqual((dest/'keep').read_text(),'keep')
            self.assertEqual(list(root.glob('.out.manuscript-*')),[])
            for kind in ('file','link','dangling','directory'):
                out=root/kind
                if kind=='file': out.write_bytes(b'keep')
                elif kind=='directory': out.mkdir()
                else: out.symlink_to(dest if kind=='link' else root/'missing')
                with self.assertRaises(c.LedgerError): m.export(ledger,spec,out)
                self.assertTrue(os.path.lexists(out))

    def test_bad_spec_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ledger,spec=self.inputs(root)
            for raw in (b'{"version":1,"version":1}',b'NaN',b'\xff',b'['*2000,b' '*(m.MAX_SPEC+1)):
                spec.write_bytes(raw)
                with self.assertRaises((ValueError,RecursionError)): m.export(ledger,spec,root/'out')
                self.assertFalse((root/'out').exists())
            spec.unlink(); os.mkfifo(spec)
            with self.assertRaises(c.LedgerError): m.export(ledger,spec,root/'out')

    def test_process_kill_at_commit_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ledger,spec=self.inputs(root)
            expected=m.build(c.load(ledger),c.load(spec))
            for when in ('before','after'):
                dest=root/when
                script='''import os,signal,sys
from claimledger import manuscript as m
original=m.commit_directory
def kill(stage,dest):
    if sys.argv[4]=='after': original(stage,dest)
    os.kill(os.getpid(),signal.SIGKILL)
m.commit_directory=kill
m.export(*sys.argv[1:4])
'''
                proc=subprocess.run([sys.executable,'-c',script,str(ledger),str(spec),str(dest),when],cwd=ROOT,capture_output=True)
                self.assertEqual(proc.returncode,-signal.SIGKILL)
                if when=='before':
                    self.assertFalse(dest.exists())
                    self.assertEqual(len(list(root.glob('.before.manuscript-*'))),1)
                    m.export(ledger,spec,dest)
                actual={str(p.relative_to(dest)):p.read_bytes() for p in dest.rglob('*') if p.is_file()}
                self.assertEqual(actual,expected)
                self.assertEqual(list(root.glob('.after.manuscript-*')),[])

    def test_installed_cli_archive_roundtrip_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--prefix',str(root/'install')],check=True,capture_output=True)
            # sitecustomize fails closed if the application tries any socket operation.
            (root/'sitecustomize.py').write_text("import socket\ndef denied(*a,**k): raise RuntimeError('network forbidden')\nsocket.socket=denied\nsocket.create_connection=denied\n")
            env=dict(os.environ,PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1')
            cli=root/'install/bin/claimledger'; ledger=root/'ledger.json'
            def run(*args, ledger_path=ledger):
                return subprocess.run([str(cli),'--ledger',str(ledger_path),*map(str,args)],cwd=root,env=env,check=True,capture_output=True)
            run('init')
            source=root/'source.txt'; source.write_bytes('Sample 😀\r\nexact excerpt\r\n'.encode())
            run('import','v1',source,'--title','Sample source')
            run('claim','c1','An authored claim'); run('claim','c2','An uncited claim')
            run('cite','q1','c1','v1','exact excerpt')
            source.write_bytes('Revised\nexact excerpt\n'.encode()); run('import','v2',source,'--title','Revised')
            run('accept','q2','q1','v2')
            spec=root/'spec.json'; spec.write_bytes(c.encoded({'version':1,'title':'Installed example','sections':[{'heading':'Findings','claims':[{'id':'c1','citations':['q1','q2']},{'id':'c2','citations':[]}]}]}))
            run('manuscript',spec,root/'first')
            run('export',root/'archive.zip'); run('verify',root/'archive.zip'); run('restore',root/'archive.zip',root/'restored')
            run('manuscript',spec,root/'second',ledger_path=root/'restored/ledger.json')
            first={str(p.relative_to(root/'first')):p.read_bytes() for p in (root/'first').rglob('*') if p.is_file()}
            second={str(p.relative_to(root/'second')):p.read_bytes() for p in (root/'second').rglob('*') if p.is_file()}
            self.assertEqual(first,second)
            self.assertEqual(json.loads(first['manifest.json'])['sections'][0]['claims'][1]['uncited'],True)


if __name__=='__main__': unittest.main()
