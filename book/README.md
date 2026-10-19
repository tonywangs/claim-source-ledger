# A Line That Could Hold

A complete short history of the Atlantic cable attempts, 1854–1866: seven
chapters, a preface and source note, 44 exact evidence excerpts, and four retained
source texts. It covers the failed attempts, the short-lived 1858 connection,
the 1865 loss, and the successful 1866 laying and recovery.

**Read now:** [HTML book](editions/book.html) · [PDF book](editions/book.pdf) ·
[searchable evidence edition](editions/evidence.html) · [manuscript](manuscript.md).
Open the HTML directly in a browser; no server or account is needed. The PDF
includes the complete narrative, excerpt notes, bibliography, internal citation
links, bookmarks, and page numbers. Keep `book.html` and `evidence.html` together
when copying the reading edition. The PDF is independently readable. Its
bibliographic web links require a connection only if followed.

The narrative is approximately 5,700 words; the PDF also includes the evidence
appendix. This is a source-based short history, not a novel discovery or a
comprehensive social or economic history. Interpretive paragraphs are labeled.
The [source guide](SOURCES.md) records dependence, transcription choices, access
gaps, and unresolved questions. Exact citation checks do **not** establish truth.

## Rebuild locally

The checked-in editions need no build tools to read. Text reconstruction needs
Python 3.10+ on Linux. PDF generation additionally needs Node.js 20+ and the pinned
Playwright Chromium package; the PDF verification dependency is also pinned in
`package-lock.json`. The checked edition used Node 24, Chromium 141, and DejaVu
Serif/Sans on Linux. Install the developer tools once (network required):

```sh
npm ci --ignore-scripts --cache /tmp/claimledger-npm-cache
PLAYWRIGHT_BROWSERS_PATH=/tmp/claimledger-browsers npx playwright install chromium
```

Chromium's system libraries and fonts must already be installed by the host.
The scripts use that temporary browser cache if present, or Playwright's usual
cache / your `PLAYWRIGHT_BROWSERS_PATH`. They never install tools automatically.
Then choose a **new** destination:

```sh
python3 scripts/build_book.py /tmp/atlantic-book
```

Open `/tmp/atlantic-book/book.html` or `/tmp/atlantic-book/book.pdf`. The build
validates the source hashes and quotations, creates a native Claim Source Ledger,
and produces the reading and evidence editions. All research inputs are already
in this checkout; the build does not fetch sources, call a model, or use a network
service. Existing output directories are refused. Linux atomic no-clobber
publication is inherited from the ledger; a failed normal build cleans its stage.

For Python-only HTML and evidence output, without Chromium:

```sh
python3 scripts/build_book.py /tmp/atlantic-book-html --html-only
```

To verify the checked-in editions and reproduce a second complete edition:

```sh
python3 scripts/verify_book.py
```

This checks raw and extracted source hashes, source extraction, every exact
quotation, native ledger audit, byte-identical text reconstruction, all 63
narrative paragraphs in HTML and PDF, all 44 exact PDF excerpts, chapter headings, PDF text bounds and
portable links, bookmarks, citation navigation, keyboard access, and mobile
layout with network access blocked in Chromium. It also checks the repository's
file and aggregate size limits. This is a focused check; the pre-existing
software's historical test results remain unchanged. It is not a screen-reader
or PDF/UA conformance audit and does not automate factual judgment.

## Editing and reproducibility

Edit `manuscript.md`; paragraph-ending `[^evidence-id]` references resolve through
`evidence.json`. The small renderer supports headings and plain paragraphs, with
these explicit citations; it is not a general Markdown renderer. Every paragraph
in a historical chapter must select evidence. Labels beginning `Interpretation.`
are rendered visibly. Preface/editorial source notes are retained in `reading.json`
but are not falsely represented as cited historical claims in the ledger.

`book/sources/catalog.json` pins every source and raw input by SHA-256. The
extractor in `scripts/book_sources.py` reproduces Russell and banquet snapshots
from retained HTML/OCR; the two manual excerpts are checked against retained
facsimiles by human inspection. See [SOURCES.md](SOURCES.md). Do not silently
replace a source revision: retain the provenance and reconsider affected claims.

`editions/manifest.json` records exact build input hashes and output hashes.
`evidence.json` in that directory is a native ledger, independently auditable with
`python3 -m claimledger --ledger book/editions/evidence.json audit`.
`reading.json` records paragraph identity, interpretation labels, notes, and
bibliographic provenance. HTML, JSON, and evidence output are deterministic from
the saved inputs. PDF metadata and platform fonts can change PDF bytes or page
breaks; bit-identical PDF output across builds or platforms is not promised.
The verifier checks the actual PDF content and navigation instead.

After a source or renderer edit, build into a new directory, inspect the result,
and replace the saved edition only when ready. `verify_book.py` deliberately
fails on stale saved editions rather than silently rewriting them.
