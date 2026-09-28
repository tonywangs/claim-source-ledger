from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from claimledger import core as c, archive
from claimledger.report import render
root=Path(sys.argv[1])
d=c.new()
hostile='</script><img src="https://example.invalid/probe" onerror="window.pwned=1"><svg onload="window.pwned=2"> & "quote" 😀'
c.import_source(d,'s1','Before '+hostile+' after.','Hostile '+hostile,author=hostile,url='javascript:window.pwned=3')
c.import_source(d,'s2','The ordinary passage.','Second source')
c.append(d,'claims',{'id':'c1','text':'Harbor opening '+hostile})
c.append(d,'claims',{'id':'c2','text':'Railway timetable'})
c.append(d,'claims',{'id':'c3','text':'Unlinked hypothesis'})
c.cite(d,'q1','c1','s1',hostile)
c.cite(d,'q2','c2','s2','ordinary passage')
c.import_source(d,'s3','Revised: '+hostile,'Revised hostile source')
c.relocate(d,'q3','q1','s3')
c.save(root/'ledger.json',d)
archive.export(root/'ledger.json',root/'browser.zip')
archive.restore(root/'browser.zip',root/'restored')
restored=c.load(root/'restored/ledger.json')
assert restored==d
(root/'browser.html').write_bytes(render(restored))
