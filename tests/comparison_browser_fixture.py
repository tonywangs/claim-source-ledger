from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_comparison import pair, save_bundle
from claimledger import comparison as d
root=Path(sys.argv[1])
a,b=pair(63)
save_bundle(root/'before',*a); save_bundle(root/'after',*b)
d.export(root/'before',root/'after',root/'comparison')
