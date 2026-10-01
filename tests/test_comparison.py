"""Seeded structural oracle, hostile bundles, bounds, and transactional CLI workflow."""
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

from claimledger import core as c, manuscript as m, comparison as d

ROOT = Path(__file__).resolve().parents[1]
SEED = 908172
CASES = 240
HOSTILE = '<script>window.pwned=1</script><img src="https://example.invalid/evil" onerror="alert(1)"> & 😀 e\u0301'


def pair(index=0):
    rng = random.Random(SEED+index)
    data = c.new()
    quote = 'exact 😀 e\u0301 中 '+HOSTILE
    for n in range(3):
        prefix = ''.join(rng.choices(['\r\n','\n','\r','\ufeff','😀','e\u0301'],k=8))
        text = prefix+quote+'\r\nother excerpt\n'+quote
        c.import_source(data,f's{n}',text,'Synthetic '+HOSTILE)
    for n in range(5):
        ident = f'c{n}'
        c.append(data,'claims',{'id':ident,'text':f'Authored claim {n} '+HOSTILE})
        for j in range(3):
            source = data['sources'][j]
            c.cite(data,f'q{n}_{j}',ident,source['id'],quote,source['text'].index(quote))
    sections = [{'heading':'Section '+str(n), 'claims':[]} for n in range(3)]
    for n in range(5):
        sections[n%3]['claims'].append({'id':f'c{n}','citations':[f'q{n}_0', f'q{n}_1']})
    sections[0]['claims'].append({'id':'c0','citations':['q0_2','q0_2']})
    spec = {'version':1,'title':'Synthetic comparison', 'sections':sections}
    newer, changed = copy.deepcopy(data), copy.deepcopy(spec)
    # Independent switches generate simultaneous changes and an unchanged control.
    mask = index % 64
    if mask & 1:
        newer['claims'][0]['text'] += '\r\nRevised text'
        changed['title'] += ' revised'
    if mask & 2:
        changed['sections'].reverse()
        for section in changed['sections']:
            section['claims'].reverse()
    if mask & 4:
        for section in changed['sections']:
            for row in section['claims']:
                if row['id']=='c0': row['citations']=['q0_2']
        changed['sections'][0]['heading'] = changed['sections'][1]['heading']
    if mask & 8:
        # Same citation IDs, changed snapshot revision bytes and exact offsets.
        for source in newer['sources']:
            source['text'] = 'new\r\n'+source['text']
            source['sha256'] = c.digest(source['text'])
        for citation in newer['citations']:
            source = next(s for s in newer['sources'] if s['id']==citation['source'])
            citation['start'] += 5; citation['end'] += 5
            citation['prefix'] = source['text'][max(0,citation['start']-80):citation['start']]
    if mask & 16:
        for section in changed['sections']:
            section['claims'] = [x for x in section['claims'] if x['id']!='c4']
        newer['claims'].append({'id':'new','text':'Added uncited claim'})
        changed['sections'][0]['claims'].append({'id':'new','citations':[]})
    if mask & 32:
        # Change the exact excerpt while retaining the source ID and snapshot.
        for citation in newer['citations']:
            if citation['claim']=='c1':
                source = next(s for s in newer['sources'] if s['id']==citation['source'])
                start = source['text'].index('other excerpt'); end=start+len('other excerpt')
                citation.update(start=start,end=end,quote='other excerpt',prefix=source['text'][max(0,start-80):start],suffix=source['text'][end:end+80])
    return (data,spec),(newer,changed)


def save_bundle(root, data, spec):
    root.mkdir(); (root/'snapshots').mkdir()
    for name,raw in m.build(data,spec).items():
        (root/name).write_bytes(raw)


def tree(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


def reference(old, new):
    """Linear record lookup, tuples, and direct equality; no production comparison helpers."""
    result=[]
    def emit(kind,ident,a,b): result.append(dict(kind=kind,id=ident,before=a,after=b))
    def records(doc,ident):
        return [(si+1,s['heading'],pos+1,r) for si,s in enumerate(doc['sections'])
                for pos,r in enumerate(s['claims']) if r['id']==ident]
    def group(rows):
        if not rows: return None
        return {'text':rows[0][3]['text'],'occurrences':[dict(section=s,heading=h,position=p,citations=r['citations']) for s,h,p,r in rows]}
    def evidence(doc,ids):
        out={}
        for ident in ids:
            q=next(q for q in doc['citations'] if q['id']==ident)
            s=next(s for s in doc['sources'] if s['id']==q['source'])
            revision=tuple((k,s[k]) for k in sorted(s))
            excerpt=tuple(q[k] for k in ('quote','start','end','prefix','suffix'))
            out[ident]=(revision,excerpt,q['supersedes'])
        return out
    if old['specification']['title']!=new['specification']['title']:
        emit('title','',old['specification']['title'],new['specification']['title'])
    hs=[[s['heading'] for s in doc['sections']] for doc in (old,new)]
    if hs[0]!=hs[1]: emit('sections','',*hs)
    orders=[[r['id'] for s in doc['sections'] for r in s['claims']] for doc in (old,new)]
    if orders[0]!=orders[1]: emit('claim_order','',*orders)
    for ident in sorted(set(orders[0]+orders[1])):
        a,b=records(old,ident),records(new,ident)
        if not a or not b:
            emit('added' if not a else 'absent',ident,group(a),group(b)); continue
        if a[0][3]['text']!=b[0][3]['text']: emit('claim_text',ident,a[0][3]['text'],b[0][3]['text'])
        ps=[[dict(section=s,heading=h,position=p) for s,h,p,r in rows] for rows in (a,b)]
        cs=[[r['citations'] for s,h,p,r in rows] for rows in (a,b)]
        if ps[0]!=ps[1]: emit('placement',ident,*ps)
        if cs[0]!=cs[1]: emit('citation_selection',ident,*cs)
        if max(len(a),len(b))>1 and (ps[0]!=ps[1] or cs[0]!=cs[1]): emit('ambiguous_occurrences',ident,len(a),len(b))
        ids=[sorted(set(q for row in side for q in row)) for side in cs]
        e,f=evidence(old,ids[0]),evidence(new,ids[1])
        shared=set(e)&set(f)
        for label,k in [('source_revision',0),('excerpt',1)]:
            if set(x[k] for x in e.values())!=set(x[k] for x in f.values()) or any(e[q][k]!=f[q][k] for q in shared):
                emit(label,ident,*ids)
        if set(x[:2] for x in e.values())!=set(x[:2] for x in f.values()) or any(e[q][:2]!=f[q][:2] for q in shared):
            emit('source_evidence',ident,*ids)
        lineage=sorted(q for q in shared if e[q][2]!=f[q][2])
        if lineage: emit('citation_lineage',ident,{q:e[q][2] for q in lineage},{q:f[q][2] for q in lineage})
    provenance=[{k:doc[k] for k in ('ledger_sha256','spec_sha256')} for doc in (old,new)]
    if provenance[0]!=provenance[1]: emit('provenance','',*provenance)
    return sorted(result,key=lambda x:(x['id'],x['kind']))


class ComparisonTests(unittest.TestCase):
    def test_seeded_reference_pairs_and_repeatability(self):
        for index in range(CASES):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); old,new=pair(index)
                save_bundle(root/'a',*old); save_bundle(root/'b',*new)
                snapshots=(tree(root/'a'),tree(root/'b'))
                d.export(root/'a',root/'b',root/'out')
                actual=json.loads((root/'out/comparison.json').read_bytes())
                expected=reference(*(json.loads(x['manifest.json']) for x in snapshots))
                self.assertEqual(actual['findings'],expected)
                self.assertTrue(actual['complete'])
                self.assertEqual(actual['outcome'],'differences' if expected else 'no_semantic_changes')
                d.export(root/'a',root/'b',root/'repeat')
                self.assertEqual(tree(root/'out'),tree(root/'repeat'))
                self.assertEqual(snapshots,(tree(root/'a'),tree(root/'b')))
                for side,files in zip(('before','after'),snapshots):
                    for name,raw in files.items():
                        self.assertEqual(actual['inputs'][side]['hashes'][name],{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
                self.assertNotIn(b'<img', (root/'out/comparison.html').read_bytes())

    def inputs(self,root,index=63):
        a,b=pair(index); save_bundle(root/'a',*a); save_bundle(root/'b',*b)
        return root/'a',root/'b',root/'out'

    def test_malformed_and_tampered_bundles(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root); original=tree(a)
            doc=json.loads(original['manifest.json'])
            mutations=[lambda x:x.update(version=True),lambda x:x.update(version=2),lambda x:x.update(extra=1),
                lambda x:x.update(spec_sha256='0'*64),lambda x:x['sections'][0]['claims'][0].update(text=''),
                lambda x:x['sections'][0]['claims'][0].update(uncited=0),
                lambda x:x['sections'][0]['claims'][0].update(citations=['absent']),
                lambda x:x['sections'][0]['claims'][-1].update(text='contradictory repeated text'),
                lambda x:x['citations'][0].update(source='missing'),lambda x:x['citations'][0].update(claim='c1'),
                lambda x:x['citations'][0].update(start=True),lambda x:x['citations'][0].update(end=999999),
                lambda x:x['citations'][0].update(quote='wrong'),lambda x:x['citations'][0].update(prefix='wrong'),
                lambda x:x['citations'][0].update(supersedes=x['citations'][0]['id']),
                lambda x:x['citations'][0].update(supersedes='c0'),
                lambda x:x['sources'][0].update(sha256='../outside'),
                lambda x:x['sources'].append(x['sources'][0]),
                lambda x:x['files'].update({'../outside':{'bytes':1,'sha256':'0'*64}})]
            for mutate in mutations:
                broken=copy.deepcopy(doc); mutate(broken); (a/'manifest.json').write_bytes(c.encoded(broken))
                with self.assertRaises((c.LedgerError,ValueError)): d.export(a,b,out)
                self.assertFalse(out.exists())
            for raw in [b'NaN',b'\xff',b'{"version":1,"version":1}',b'['*2000]:
                (a/'manifest.json').write_bytes(raw)
                with self.assertRaises((ValueError,RecursionError)): d.export(a,b,out)
            for name,raw in original.items(): (a/name).write_bytes(raw)
            for name in original:
                (a/name).write_bytes(original[name]+b'tamper')
                with self.assertRaises(ValueError): d.export(a,b,out)
                (a/name).write_bytes(original[name])
            (a/'extra').write_bytes(b'extra')
            with self.assertRaisesRegex(c.LedgerError,'unexpected'): d.export(a,b,out)
            (a/'extra').unlink()
            (a/'manuscript.md').unlink(); (a/'manuscript.md').symlink_to(b/'manuscript.md')
            with self.assertRaises((c.LedgerError,OSError)): d.export(a,b,out)
            (a/'manuscript.md').unlink(); os.mkfifo(a/'manuscript.md')
            with self.assertRaises(c.LedgerError): d.export(a,b,out)
            self.assertFalse(out.exists())

    def test_limits_and_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            for module,key in [(d,'MAX_INPUT'),(d,'MAX_OUTPUT'),(m,'MAX_CLAIMS'),(m,'MAX_SNAPSHOT_BYTES'),(m,'MAX_SOURCES')]:
                with patch.object(module,key,1):
                    with self.assertRaises(c.LedgerError): d.export(a,b,out)
                self.assertFalse(out.exists())
            for kwargs in [dict(work=1),dict(seconds=1e-12),dict(seconds=float('nan')),dict(seconds=31),dict(work=0)]:
                with self.assertRaises(c.LedgerError): d.export(a,b,out,**kwargs)
                self.assertFalse(out.exists())
            original=d.render
            def expired(*args):
                raw=original(*args); args[1].deadline=0; return raw
            with patch.object(d,'render',side_effect=expired):
                with self.assertRaisesRegex(c.LedgerError,'runtime'): d.export(a,b,out)
            for target in [(d,'render'),(c,'atomic_write'),(os,'fsync'),(d,'commit_directory')]:
                for exc in [OSError('failure'),KeyboardInterrupt(),SystemExit(1)]:
                    with patch.object(*target,side_effect=exc):
                        with self.assertRaises(type(exc)): d.export(a,b,out)
                    self.assertFalse(out.exists()); self.assertEqual(list(root.glob('.out.comparison-*')),[])
            original=d.encode
            def broken(value,budget):
                if isinstance(value,dict) and value.get('format')=='claim-source-ledger-comparison': raise TypeError('serialization')
                return original(value,budget)
            with patch.object(d,'encode',side_effect=broken):
                with self.assertRaises(TypeError): d.export(a,b,out)
            self.assertFalse(out.exists()); self.assertEqual(list(root.glob('.out.comparison-*')),[])
            write=c.atomic_write; calls=[]
            def partial(*args):
                calls.append(args)
                if len(calls)==2: raise OSError('second write')
                return write(*args)
            with patch.object(c,'atomic_write',side_effect=partial):
                with self.assertRaises(OSError): d.export(a,b,out)
            self.assertFalse(out.exists()); self.assertEqual(list(root.glob('.out.comparison-*')),[])
            original_commit=d.commit_directory
            def race(stage,dest):
                dest.mkdir(); (dest/'keep').write_bytes(b'keep'); original_commit(stage,dest)
            with patch.object(d,'commit_directory',side_effect=race):
                with self.assertRaises(FileExistsError): d.export(a,b,out)
            self.assertEqual((out/'keep').read_bytes(),b'keep')
            self.assertEqual(list(root.glob('.out.comparison-*')),[])
            for dest in [a/'nested',out]:
                with self.assertRaises(c.LedgerError): d.export(a,b,dest)

    def test_mutation_recheck_and_output_exact_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            original=d.render
            def mutate(*args):
                raw=original(*args); (a/'manuscript.md').write_bytes(b'changed'); return raw
            with patch.object(d,'render',side_effect=mutate):
                with self.assertRaisesRegex(c.LedgerError,'changed during'): d.export(a,b,out)
            self.assertFalse(out.exists())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            result=d.export(a,b,out)
            with patch.object(d,'MAX_OUTPUT',result['bytes']): d.export(a,b,root/'exact')
            with patch.object(d,'MAX_OUTPUT',result['bytes']-1):
                with self.assertRaises(c.LedgerError): d.export(a,b,root/'small')
            self.assertFalse((root/'small').exists())

    def test_omitted_ancestors_and_swapped_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (data,spec),_=pair()
            # Selected citation may refer to an unselected ancestor.
            original=data['citations'][0]
            source=data['sources'][2]
            c.cite(data,'relocated','c0','s2',original['quote'],source['text'].index(original['quote']),original['id'])
            spec['sections'][0]['claims'][0]['citations']=['relocated']
            save_bundle(root/'a',data,spec)
            d.export(root/'a',root/'a',root/'equal')
            self.assertEqual(json.loads((root/'equal/comparison.json').read_bytes())['outcome'],'no_semantic_changes')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (data,spec),_=pair()
            newer=copy.deepcopy(data)
            x,y=[q for q in newer['citations'] if q['id'] in ('q0_0','q0_1')]
            ox,oy=copy.deepcopy(x),copy.deepcopy(y)
            for key in ('source','start','end','quote','prefix','suffix'): x[key],y[key]=oy[key],ox[key]
            save_bundle(root/'a',data,spec); save_bundle(root/'b',newer,spec)
            d.export(root/'a',root/'b',root/'out')
            kinds=[f['kind'] for f in json.loads((root/'out/comparison.json').read_bytes())['findings'] if f['id']=='c0']
            self.assertIn('source_evidence',kinds)
            self.assertIn('source_revision',kinds)
            self.assertNotIn('citation_selection',kinds)

    def test_presentation_bytes_and_citation_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (data,spec),_=pair()
            save_bundle(root/'a',data,spec); save_bundle(root/'b',data,spec)
            # Hash-consistent imported presentation is opaque data, never executed or embedded.
            raw=b'<script>window.renderedOnlySentinel=1</script>'
            (root/'b/manuscript.html').write_bytes(raw)
            manifest=json.loads((root/'b/manifest.json').read_bytes())
            manifest['files']['manuscript.html']={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            (root/'b/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))
            d.export(root/'a',root/'b',root/'out')
            report=json.loads((root/'out/comparison.json').read_bytes())
            self.assertEqual(report['outcome'],'no_semantic_changes')
            self.assertNotEqual(report['inputs']['before']['sha256'],report['inputs']['after']['sha256'])
            self.assertNotIn(b'renderedOnlySentinel',(root/'out/comparison.html').read_bytes())
            newer,second=copy.deepcopy(data),copy.deepcopy(spec)
            newer['citations'][0]['id']='renamed'
            for section in second['sections']:
                for row in section['claims']:
                    row['citations']=['renamed' if q=='q0_0' else q for q in row['citations']]
            save_bundle(root/'renamed',newer,second)
            d.export(root/'a',root/'renamed',root/'renamed-out')
            kinds=[f['kind'] for f in json.loads((root/'renamed-out/comparison.json').read_bytes())['findings']]
            self.assertIn('citation_selection',kinds)
            self.assertNotIn('source_evidence',kinds)
            self.assertNotIn('source_revision',kinds)
            self.assertNotIn('excerpt',kinds)

    def test_unicode_offsets_independent_and_semantic_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            doc=json.loads((a/'manifest.json').read_bytes())
            for q in doc['citations']:
                source=next(x for x in doc['sources'] if x['id']==q['source'])
                text=(a/'snapshots'/(source['sha256']+'.txt')).read_bytes().decode('utf-8')
                self.assertEqual(tuple(text)[q['start']:q['end']],tuple(q['quote']))
            # Valid integer UTF-8 byte offsets are not code-point offsets.
            q=doc['citations'][0]; source=next(x for x in doc['sources'] if x['id']==q['source'])
            text=(a/'snapshots'/(source['sha256']+'.txt')).read_bytes().decode('utf-8')
            original=copy.deepcopy(doc)
            q['start']=len(text[:q['start']].encode()); q['end']=q['start']+len(q['quote'].encode())
            (a/'manifest.json').write_bytes(c.encoded(doc))
            with self.assertRaisesRegex(c.LedgerError,'integrity'): d.export(a,b,out)
            doc=original
            # Rehash a corrupt source file and its inventory but leave the exact excerpt false.
            source=doc['sources'][0]; name='snapshots/'+source['sha256']+'.txt'
            raw=(a/name).read_bytes().replace(b'exact',b'false'); digest=hashlib.sha256(raw).hexdigest()
            (a/name).unlink(); del doc['files'][name]
            source['sha256']=digest; name='snapshots/'+digest+'.txt'
            (a/name).write_bytes(raw); doc['files'][name]={'bytes':len(raw),'sha256':digest}
            (a/'manifest.json').write_bytes(c.encoded(doc))
            with self.assertRaisesRegex(c.LedgerError,'integrity'): d.export(a,b,out)
            self.assertFalse(out.exists())

    def test_runtime_expiry_during_staging_and_collision_types(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            original=d.Budget.check
            def expire_after_write(budget,amount=0):
                if any(root.glob('.out.comparison-*/comparison.html')): budget.deadline=0
                return original(budget,amount)
            with patch.object(d.Budget,'check',expire_after_write):
                with self.assertRaisesRegex(c.LedgerError,'runtime'): d.export(a,b,out)
            self.assertFalse(out.exists()); self.assertEqual(list(root.glob('.out.comparison-*')),[])
            for kind in ('file','link','dangling','directory'):
                dest=root/kind
                if kind=='file': dest.write_bytes(b'keep')
                elif kind=='directory': dest.mkdir()
                else: dest.symlink_to(a if kind=='link' else root/'missing')
                with self.assertRaises(c.LedgerError): d.export(a,b,dest)
                self.assertTrue(os.path.lexists(dest))

    def test_kill_before_after_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); a,b,out=self.inputs(root)
            d.export(a,b,out); expected=tree(out)
            script='''import os,signal,sys
from claimledger import comparison as d
original=d.commit_directory
def kill(stage,dest):
    if sys.argv[4]=='after': original(stage,dest)
    os.kill(os.getpid(),signal.SIGKILL)
d.commit_directory=kill
d.export(*sys.argv[1:4])
'''
            for when in ('before','after'):
                dest=root/when
                proc=subprocess.run([sys.executable,'-c',script,str(a),str(b),str(dest),when],cwd=ROOT,capture_output=True)
                self.assertEqual(proc.returncode,-signal.SIGKILL)
                if when=='before':
                    self.assertFalse(dest.exists()); self.assertEqual(len(list(root.glob('.before.comparison-*'))),1)
                    d.export(a,b,dest)
                self.assertEqual(tree(dest),expected)

    def test_installed_cli_archive_restoration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),'--prefix',str(root/'install')],check=True,capture_output=True)
            (root/'sitecustomize.py').write_text("import socket\ndef denied(*a,**k): raise RuntimeError('network forbidden')\nsocket.socket=denied\nsocket.create_connection=denied\n")
            env=dict(os.environ,PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1')
            cli=root/'install/bin/claimledger'; ledger=root/'ledger.json'
            def run(*args,ledger_path=ledger):
                return subprocess.run([str(cli),'--ledger',str(ledger_path),*map(str,args)],cwd=root,env=env,check=True,capture_output=True)
            run('init'); source=root/'source.txt'; source.write_bytes('😀\r\nexact excerpt\r\n'.encode())
            run('import','v1',source,'--title','Sample source'); run('claim','c1','A sample authored claim')
            run('cite','q1','c1','v1','exact excerpt')
            spec=root/'spec.json'; payload={'version':1,'title':'Before','sections':[{'heading':'Findings','claims':[{'id':'c1','citations':['q1']}]}]}
            spec.write_bytes(c.encoded(payload)); run('manuscript',spec,root/'before')
            source.write_bytes('Revision\nexact excerpt\n'.encode()); run('import','v2',source,'--title','Revision')
            run('accept','q2','q1','v2'); payload['title']='After'; payload['sections'][0]['claims'][0]['citations']=['q2']
            spec.write_bytes(c.encoded(payload)); run('manuscript',spec,root/'after')
            run('export',root/'archive.zip'); run('restore',root/'archive.zip',root/'restored')
            run('manuscript',spec,root/'rebuilt',ledger_path=root/'restored/ledger.json')
            self.assertEqual(tree(root/'after'),tree(root/'rebuilt'))
            ledger.unlink(); (root/'restored/ledger.json').unlink()
            run('manuscript-compare',root/'before',root/'after',root/'comparison')
            run('manuscript-compare',root/'before',root/'rebuilt',root/'restored-comparison')
            self.assertEqual(tree(root/'comparison'),tree(root/'restored-comparison'))
            report=json.loads((root/'comparison/comparison.json').read_bytes())
            self.assertEqual(report['outcome'],'differences'); self.assertTrue(report['complete'])


if __name__=='__main__': unittest.main()
