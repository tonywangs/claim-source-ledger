#!/usr/bin/env python3
"""Install a self-contained executable zipapp, without pip or network access."""
import argparse
from pathlib import Path
import shutil
import tempfile
import zipapp
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claimledger.core import atomic_write

p = argparse.ArgumentParser()
p.add_argument('--prefix', type=Path, required=True)
a = p.parse_args()
bin_dir = a.prefix / 'bin'
bin_dir.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    shutil.copytree(Path(__file__).resolve().parents[1] / 'claimledger', root / 'app' / 'claimledger',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (root / 'app' / '__main__.py').write_text('from claimledger.__main__ import main\nimport sys\nsys.exit(main())\n', encoding='utf-8')
    zipapp.create_archive(root / 'app', root / 'claimledger', interpreter='/usr/bin/env python3')
    target = bin_dir / 'claimledger'
    atomic_write(target, (root / 'claimledger').read_bytes())
    target.chmod(0o755)
print(target)
