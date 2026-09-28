import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claimledger import core as c, manuscript as m
from test_manuscript import fixture
root=Path(sys.argv[1])
data,spec=fixture()
c.save(root/'ledger.json',data)
(root/'spec.json').write_bytes(c.encoded(spec))
m.export(root/'ledger.json',root/'spec.json',root/'bundle')
