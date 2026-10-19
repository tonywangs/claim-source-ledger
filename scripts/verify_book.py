#!/usr/bin/env python3
"""Focused offline verification of the real historical book and its saved editions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from build_book import ROOT, BOOK, build_text, sha


def main():
    saved = BOOK / 'editions'
    manifest = json.loads((saved / 'manifest.json').read_text())
    for name, expected in manifest['inputs'].items():
        assert sha((ROOT / name).read_bytes()) == expected, 'stale build input: ' + name
    assert {p.name for p in saved.iterdir()} == set(manifest['files']) | {'manifest.json'}
    for name, record in manifest['files'].items():
        data = (saved / name).read_bytes()
        assert len(data) == record['bytes'] and sha(data) == record['sha256'], 'changed edition: ' + name
    built = build_text()
    for name, raw in built.items():
        assert raw == (saved / name).read_bytes(), 'non-reproducible text: ' + name
    # Rebuild through the documented CLI into a new location, including the PDF.
    with tempfile.TemporaryDirectory(prefix='verify-atlantic-book-') as tmp:
        output = Path(tmp) / 'edition'
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_book.py'), str(output)], check=True, cwd=ROOT)
        for name, raw in built.items():
            assert raw == (output / name).read_bytes(), 'CLI reconstruction changed: ' + name
        subprocess.run(['node', str(ROOT / 'scripts/verify_book.cjs'), str(output)], check=True, cwd=ROOT)
    subprocess.run(['node', str(ROOT / 'scripts/verify_book.cjs'), str(saved)], check=True, cwd=ROOT)
    # Check publication limits for the tracked tree plus new project files.
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    paths = sorted(set(p for p in paths if p))
    sizes = [(ROOT / p).stat().st_size for p in paths]
    assert len(paths) <= 1000 and sum(sizes) <= 32 * 1024 * 1024
    assert max(sizes) <= 10 * 1024 * 1024
    assert not [p for p in paths if p.endswith('.log') and p != 'results/tests.log']
    print(json.dumps({'ok': True, 'deterministic_text_files': list(built),
                      'publication_files': len(paths), 'publication_bytes': sum(sizes)}))


if __name__ == '__main__':
    main()
