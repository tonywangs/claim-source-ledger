"""Independent round-trip comparisons and hostile archive/failure regressions."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from claimledger import archive as a, core as c

ROOT = Path(__file__).resolve().parents[1]
SEED = 390274
CASES = 240


def fixture(index=0, rng=None):
    rng = rng or random.Random(SEED+index)
    prefix = ''.join(rng.choices(['😀','α','中','e\u0301','\r\n','\n','\r','\ufeff',' '], k=rng.randrange(1,30)))
    quote = f'passage {index} 😀'
    original = prefix+quote+' / '+quote+'\r\n'
    revised = 'Revised\r\n'+quote+'\n終'
    data = c.new()
    c.import_source(data,'original',original,'Original 😀','Sample author','2000-01-01','https://example.invalid/not-fetched')
    c.import_source(data,'revised',revised,'Revision')
    c.import_source(data,'duplicate',original,'Same bytes, different metadata')
    c.import_source(data,'empty','','Empty snapshot')
    c.append(data,'claims',{'id':'claim','text':'A synthetic authored claim'})
    c.append(data,'claims',{'id':'unlinked','text':'No supporting evidence'})
    c.cite(data,'first','claim','original',quote,len(prefix))
    c.cite(data,'second','claim','original',quote,len(prefix)+len(quote)+3)
    c.relocate(data,'accepted','first','revised')
    c.import_source(data,'final','Final introduction '+revised,'Second revision')
    c.relocate(data,'final-citation','accepted','final')
    return data


class ArchiveTests(unittest.TestCase):
    def test_seeded_round_trips(self):
        rng = random.Random(SEED)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index in range(CASES):
                with self.subTest(case=index):
                    original = fixture(index,rng)
                    # Expected records and bytes do not use archive serialization or verification.
                    expected = copy.deepcopy(original)
                    snapshots = {hashlib.sha256(s['text'].encode()).hexdigest(): s['text'].encode()
                                 for s in original['sources']}
                    ledger = root/'input.json'
                    ledger.write_text(json.dumps(original,ensure_ascii=True),encoding='utf-8')
                    first, second = root/f'{index}.zip', root/f'{index}-again.zip'
                    a.export(ledger,first)
                    ledger.write_text(json.dumps(original,ensure_ascii=False,indent=4),encoding='utf-8')
                    a.export(ledger,second)
                    self.assertEqual(first.read_bytes(),second.read_bytes())
                    self.assertTrue(a.verify(first)['ok'])
                    destination = root/f'restored-{index}'
                    a.restore(first,destination)
                    actual = json.loads((destination/'ledger.json').read_bytes())
                    self.assertEqual(actual,expected)
                    self.assertEqual({p.stem:p.read_bytes() for p in (destination/'snapshots').iterdir()},snapshots)
                    for citation in actual['citations']:
                        source = next(s for s in actual['sources'] if s['id']==citation['source'])
                        chars = tuple(source['text'])
                        self.assertEqual(tuple(citation['quote']), chars[citation['start']:citation['end']])
                    self.assertEqual(actual['citations'][-1]['supersedes'],'accepted')
                    again = root/f'{index}-restored.zip'
                    a.export(destination/'ledger.json',again)
                    self.assertEqual(first.read_bytes(),again.read_bytes())

    def assert_rejected(self, raw):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root/'bad.zip'; archive.write_bytes(raw)
            destination = root/'restored'
            with self.assertRaises((c.LedgerError,ValueError,UnicodeError,RecursionError)):
                a.verify(archive)
            with self.assertRaises((c.LedgerError,ValueError,UnicodeError,RecursionError)):
                a.restore(archive,destination)
            self.assertFalse(destination.exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()),['bad.zip'])

    def files(self):
        raw = a.build(fixture())
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return {info.filename:z.read(info) for info in z.infolist()}

    def reseal(self, files):
        files = dict(files); files.pop('manifest.json',None)
        files['manifest.json'] = a.manifest(files)
        return a.pack(files)

    def test_corruption_and_allowlist(self):
        raw = a.build(fixture())
        for bad in (b'',raw[:20],raw[:-1],raw+b'trailer',b'prefix'+raw,raw[:70]+bytes([raw[70]^1])+raw[71:]):
            self.assert_rejected(bad)
        for name in ('../escape','/absolute','C:/drive','snapshots/../escape','snapshots\\escape',
                     'ledger.json/','report.html','snapshots/'+'a'*64+'.txt/','./ledger.json'):
            files = self.files(); files[name] = b'bad'
            self.assert_rejected(self.reseal(files))
        for name in ('ledger.json','manifest.json',next(n for n in self.files() if n.startswith('snapshots/'))):
            files=self.files(); del files[name]; self.assert_rejected(a.pack(files))
        files=self.files(); files['ledger.json']+=b' '; self.assert_rejected(a.pack(files))
        files=self.files(); files['snapshots/'+'0'*64+'.txt']=b'unreferenced'; self.assert_rejected(self.reseal(files))
        files=self.files(); name=next(n for n in files if n.startswith('snapshots/'))
        files[name]=b'changed'; self.assert_rejected(self.reseal(files))

    def test_manifest_and_ledger_validation(self):
        for value in (None,[],{}, {'format':'claim-source-ledger','version':2,'files':{}},
                      {'format':'claim-source-ledger','version':True,'files':{}}):
            files=self.files(); files['manifest.json']=c.encoded(value); self.assert_rejected(a.pack(files))
        for raw in (b'{"version":1,"version":1}',b'NaN',b'\xff',b'['*2000):
            files=self.files(); files['manifest.json']=raw; self.assert_rejected(a.pack(files))
        for key,value in (('source','missing'),('claim','missing'),('quote','wrong'),('prefix','wrong'),
                          ('supersedes','first'),('start',True)):
            files=self.files(); data=json.loads(files['ledger.json']); data['citations'][0][key]=value
            files['ledger.json']=c.encoded(data); self.assert_rejected(self.reseal(files))
        for version in (2,True):
            files=self.files(); data=json.loads(files['ledger.json']); data['version']=version
            files['ledger.json']=c.encoded(data); self.assert_rejected(self.reseal(files))
        files=self.files(); meta=json.loads(files['manifest.json']); meta['files']['ledger.json']['bytes']=True
        files['manifest.json']=c.encoded(meta); self.assert_rejected(a.pack(files))
        files=self.files(); files['ledger.json']=json.dumps(json.loads(files['ledger.json'])).encode()
        self.assert_rejected(self.reseal(files))

    def test_seeded_single_bit_corruption(self):
        raw=a.build(fixture())
        rng=random.Random(83719)
        for index in rng.sample(range(len(raw)),256):
            bad=bytearray(raw); bad[index] ^= 1 << rng.randrange(8)
            with self.subTest(byte=index): self.assert_rejected(bytes(bad))

    def test_past_end_offset_is_not_a_valid_excerpt(self):
        data=c.new(); c.import_source(data,'s','whole','Title')
        c.append(data,'claims',{'id':'c','text':'Claim'}); c.cite(data,'q','c','s','whole')
        data['citations'][0]['end']=100
        # Python slices silently clip; integrity validation must not.
        self.assertFalse(c.audit(data)['ok'])
        files={'ledger.json':c.encoded(data),'snapshots/'+data['sources'][0]['sha256']+'.txt':b'whole'}
        self.assert_rejected(self.reseal(files))

    def test_zip_structure(self):
        for kind in ('duplicate','symlink','directory','fifo','deflate','comment','extra','time','nul'):
            with self.subTest(kind=kind):
                out=io.BytesIO()
                with zipfile.ZipFile(out,'w') as z:
                    for name,content in sorted(self.files().items()):
                        info=zipfile.ZipInfo(name); info.create_system=3
                        info.external_attr=(stat.S_IFREG|0o600)<<16
                        if name=='ledger.json':
                            if kind in ('symlink','directory','fifo'):
                                info.external_attr=({'symlink':stat.S_IFLNK,'directory':stat.S_IFDIR,'fifo':stat.S_IFIFO}[kind]|0o600)<<16
                            if kind=='deflate': info.compress_type=zipfile.ZIP_DEFLATED
                            if kind=='comment': info.comment=b'comment'
                            if kind=='extra': info.extra=b'\x01\x00\x00\x00'
                            if kind=='time': info.date_time=(2020,1,1,0,0,0)
                            if kind=='nul': info.filename='ledger.json\x00hidden'
                        z.writestr(info,content)
                        if name=='ledger.json' and kind=='duplicate': z.writestr(info,content)
                self.assert_rejected(out.getvalue())
        raw=bytearray(a.build(fixture()))
        # Falsify EOCD count, local filename, flags, and central directory size.
        for offset in (-12,30,6,-10):
            bad=raw.copy(); bad[offset]^=1; self.assert_rejected(bytes(bad))

    def test_directory_preflight_precedes_zip_parser(self):
        raw=bytearray(a.build(fixture()))
        directory=struct.unpack_from('<I',raw,len(raw)-6)[0]
        # An embedded ZIP64 locator in a comment can make a general ZIP reader
        # reinterpret the end record. Non-profile names/extras/comments must be
        # refused before the reader allocates a directory from those fields.
        for offset in (directory+30,directory+32):
            bad=raw.copy(); bad[offset]=1
            with patch.object(zipfile,'ZipFile',side_effect=AssertionError('parser called before preflight')):
                with self.assertRaises(c.LedgerError): a.inspect_bytes(bytes(bad))
        bad=raw.copy(); bad[directory+46]=ord('/')
        with patch.object(zipfile,'ZipFile',side_effect=AssertionError('parser called before preflight')):
            with self.assertRaises(c.LedgerError): a.inspect_bytes(bytes(bad))

    def test_limits(self):
        raw=a.build(fixture())
        for name,limit in (('MAX_ARCHIVE',len(raw)-1),('MAX_EXPANDED',100),('MAX_FILES',2),
                           ('MAX_MANIFEST',10),('MAX_DIRECTORY',10)):
            with patch.object(a,name,limit): self.assert_rejected(raw)
        with patch.object(c,'MAX_SOURCE',1): self.assert_rejected(raw)
        with patch.object(c,'MAX_LEDGER',1): self.assert_rejected(raw)
        with patch('claimledger.report.MAX_LEDGER',1): self.assert_rejected(raw)
        # A valid exact bound succeeds; one byte less fails above.
        with patch.object(a,'MAX_ARCHIVE',len(raw)):
            self.assertEqual(a.inspect_bytes(raw)[0],fixture())
        with tempfile.TemporaryDirectory() as folder:
            fifo=Path(folder)/'fifo'; os.mkfifo(fifo)
            with self.assertRaises(c.LedgerError): a.verify(fifo)

    def test_export_coordination_and_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ledger=root/'ledger.json'; c.save(ledger,fixture())
            output=root/'archive.zip'
            with c.locked(ledger):
                with self.assertRaises(BlockingIOError): a.export(ledger,output)
            self.assertFalse(output.exists())
            original=a.build
            def mutate(data):
                raw=original(data); ledger.write_bytes(c.encoded(c.new())); return raw
            with patch.object(a,'build',side_effect=mutate):
                with self.assertRaisesRegex(c.LedgerError,'changed during export'): a.export(ledger,output)
            self.assertFalse(output.exists())
            a.export(ledger,output); before=output.read_bytes()
            with self.assertRaises(c.LedgerError): a.export(ledger,output)
            self.assertEqual(output.read_bytes(),before)
            link=root/'link'; link.symlink_to(output)
            with self.assertRaises(c.LedgerError): a.export(ledger,link)
            for operation in ('fsync','link'):
                target=root/'failed.zip'
                with patch.object(os,operation,side_effect=OSError('interrupted')):
                    with self.assertRaises(OSError): a.export(ledger,target)
                self.assertFalse(target.exists())
                self.assertEqual(list(root.glob('.*.tmp-*')),[])

    def test_restore_failures_cancellation_and_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'archive.zip'; source.write_bytes(a.build(fixture()))
            destination=root/'restored'
            for operation in ('atomic_write','fsync','commit'):
                target = (c,'atomic_write') if operation=='atomic_write' else (os,'fsync') if operation=='fsync' else (a,'commit_directory')
                for error in (OSError('interrupted'),KeyboardInterrupt(),SystemExit(1)):
                    with patch.object(*target,side_effect=error):
                        with self.assertRaises(type(error)): a.restore(source,destination)
                    self.assertFalse(destination.exists())
                    self.assertEqual(list(root.glob('.*.restore-*')),[])
            # Failure after at least one successfully written file.
            original=c.atomic_write; calls=[]
            def partial(*args,**kwargs):
                calls.append(args)
                if len(calls)==2: raise OSError('second write failed')
                return original(*args,**kwargs)
            with patch.object(c,'atomic_write',side_effect=partial):
                with self.assertRaises(OSError): a.restore(source,destination)
            self.assertFalse(destination.exists()); self.assertEqual(list(root.glob('.*.restore-*')),[])
            # A competing empty directory must also survive the commit race.
            commit=a.commit_directory
            def race(stage,dest):
                dest.mkdir(); commit(stage,dest)
            with patch.object(a,'commit_directory',side_effect=race):
                with self.assertRaises(FileExistsError): a.restore(source,destination)
            self.assertTrue(destination.is_dir()); self.assertEqual(list(destination.iterdir()),[])
            destination.rmdir()
            a.restore(source,destination); before=(destination/'ledger.json').read_bytes()
            with self.assertRaises(c.LedgerError): a.restore(source,destination)
            self.assertEqual((destination/'ledger.json').read_bytes(),before)
            for kind in ('file','symlink','dangling'):
                target=root/kind
                if kind=='file': target.write_bytes(b'keep')
                else: target.symlink_to(destination if kind=='symlink' else root/'absent')
                with self.assertRaises(c.LedgerError): a.restore(source,target)
                self.assertTrue(os.path.lexists(target))
            self.assertEqual(list(root.glob('.*.restore-*')),[])

    def test_kill_before_and_after_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'archive.zip'; source.write_bytes(a.build(fixture()))
            for when in ('before','after'):
                destination=root/when
                script='''import os,signal,sys
from claimledger import archive as a
original=a.commit_directory
def kill(stage,destination):
    if sys.argv[3]=='after': original(stage,destination)
    os.kill(os.getpid(),signal.SIGKILL)
a.commit_directory=kill
a.restore(sys.argv[1],sys.argv[2])
'''
                result=subprocess.run([sys.executable,'-c',script,str(source),str(destination),when],cwd=ROOT,capture_output=True)
                self.assertEqual(result.returncode,-signal.SIGKILL)
                if when=='before':
                    self.assertFalse(destination.exists())
                    stages=list(root.glob('.before.restore-*')); self.assertEqual(len(stages),1)
                    self.assertEqual(json.loads((stages[0]/'ledger.json').read_bytes()),fixture())
                    # Recovery is retry into a fresh destination, never publishing an orphan.
                    a.restore(source,destination)
                self.assertEqual(json.loads((destination/'ledger.json').read_bytes()),fixture())
                self.assertEqual(list(root.glob('.after.restore-*')),[])


if __name__ == '__main__':
    unittest.main()
