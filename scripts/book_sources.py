#!/usr/bin/env python3
"""Reproduce readable source snapshots from checked-in historical inputs (offline)."""
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class RussellText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        ident = attrs.get('id', '')
        if ident == 'page_001':
            self.active = True
        if self.active and re.fullmatch(r'page_\d+', ident):
            self.parts.append('\n\n[Printed page ' + str(int(ident[5:])) + ']\n\n')
        if self.active and tag in ('p', 'h1', 'h2', 'h3', 'tr', 'br'):
            self.parts.append('\n\n')

    def handle_data(self, data):
        if self.active:
            if 'END OF THE PROJECT GUTENBERG EBOOK' in data:
                self.active = False
            else:
                self.parts.append(re.sub(r'\s+', ' ', data))


def snapshots():
    parser = RussellText()
    parser.feed((ROOT / 'book/sources/raw/russell.html').read_text())
    russell = '\n\n'.join(p.strip() for p in ''.join(parser.parts).split('\n\n') if p.strip()) + '\n'
    # Retain OCR spelling, hyphenation, and page numbers. Only whitespace changes.
    banquet = (ROOT / 'book/sources/raw/banquet.txt').read_text()
    banquet = '\n\n'.join(re.sub(r'\s+', ' ', p).strip() for p in re.split(r'\n\s*\n', banquet) if p.strip()) + '\n'
    return {'russell': russell, 'banquet': banquet}


if __name__ == '__main__':
    for name, text in snapshots().items():
        path = ROOT / 'book/sources' / (name + '.txt')
        path.write_text(text, encoding='utf-8')
        print(path.relative_to(ROOT))
