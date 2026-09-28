# Claim Source Ledger

A local evidence notebook for researchers who need to answer: **Which exact
source passage did I cite, and does that citation still match this revision?**

Import UTF-8 files, author claims, attach exact quotations, compare revisions,
export an offline HTML report, and back up or restore a verified archive. Source snapshots and original citations remain
in the ledger. Nothing fetches source URLs, calls an inference service, or sends
research data anywhere.

**Citation integrity is not factual truth.** A valid citation establishes an exact
text match in a stored snapshot. It does not establish authenticity, accuracy,
source quality, or whether the quotation supports the authored claim.

## Quick start

Requires Python 3.10+ on Linux or macOS (POSIX file locks). Transactional archive
restoration currently requires Linux; see [ARCHIVE.md](ARCHIVE.md). No runtime packages.
From this checkout, `python3 -m claimledger` works immediately. To install a
standalone executable, without pip or internet access:

```sh
python3 scripts/install.py --prefix /tmp/claimledger-install
/tmp/claimledger-install/bin/claimledger --help
```

The installer refuses an existing executable. Choose a new prefix for an upgrade.
Keep the ledger and report in a working directory outside this checkout:

```sh
mkdir /tmp/canal-research
python3 -m claimledger --ledger /tmp/canal-research/evidence.json init
python3 -m claimledger --ledger /tmp/canal-research/evidence.json import notice examples/notice.txt \
  --title 'Synthetic Marshbridge notice' --author 'Invented Gazette' --date 1842-05-14
python3 -m claimledger --ledger /tmp/canal-research/evidence.json claim opening \
  'The synthetic notice says the east canal opened to freight.'
python3 -m claimledger --ledger /tmp/canal-research/evidence.json cite opening-original opening notice \
  'The east canal opened to freight on Monday.'
python3 -m claimledger --ledger /tmp/canal-research/evidence.json audit
python3 -m claimledger --ledger /tmp/canal-research/evidence.json report /tmp/canal-research/report.html
```

Open `report.html` locally in a browser. Search covers claim text and citation text;
source filtering selects claims with at least one citation to that snapshot.
Original and accepted citations both count. Follow source links and return links
or expand context. `/` focuses search; Escape clears it; Tab and Enter navigate.
The report includes every full snapshot and is therefore as sensitive as the
ledger. Sharing a report shares its source text and metadata.

The sample documents are **invented teaching material**, not historical evidence.
For a fuller example, including an unsupported claim and a retained relocation:

```sh
python3 scripts/example.py /tmp/claimledger-example
```

That command requires a new output directory. The resulting HTML and JSON can be
read without the checkout. A warning for the deliberately unsupported claim is
expected.

## Portable backups

Export all records, original citations, revision relationships, and immutable
snapshots into one deterministic archive:

```sh
python3 -m claimledger --ledger /tmp/canal-research/evidence.json export /tmp/evidence.zip
python3 -m claimledger verify /tmp/evidence.zip
python3 -m claimledger restore /tmp/evidence.zip /tmp/recovered-evidence
python3 -m claimledger --ledger /tmp/recovered-evidence/ledger.json audit
python3 -m claimledger --ledger /tmp/recovered-evidence/ledger.json report /tmp/recovered-report.html
```

Choose absent archive and restore paths. Verification is fully offline and checks
structure, SHA-256 hashes, references, quotations, and report limits. Restore
publishes a complete new directory atomically; it never replaces an existing
ledger. Identical ledger state produces byte-identical archives. Hashes detect
corruption, not authenticity or factual truth. See [ARCHIVE.md](ARCHIVE.md) for the
bounded version-1 format, compatibility, backup and recovery instructions, Linux
restore requirement, and crash/power-loss limits.

## Revising a source

A snapshot is never updated through the CLI. Import the revised text under a new
identifier, then explicitly compare it:

```sh
python3 -m claimledger --ledger /tmp/canal-research/evidence.json import revision examples/revised-notice.txt \
  --title 'Synthetic corrected transcription'
python3 -m claimledger --ledger /tmp/canal-research/evidence.json compare notice revision
python3 -m claimledger --ledger /tmp/canal-research/evidence.json accept opening-relocated opening-original revision
```

`compare` never changes the ledger. Its labels mean:

| Label | Definition |
| --- | --- |
| `unchanged` | The exact quotation remains at its original code-point position, even if other matches exist or surrounding text changed. |
| `uniquely_relocatable` | The original position no longer matches and exactly one occurrence exists elsewhere. |
| `ambiguous` | The original position no longer matches and two or more occurrences exist. |
| `missing` | No exact occurrence exists. |

Comparison returns the first 64 candidate offsets and `positions_truncated` when
there are more. It uses overlapping matches. Context is shown for human inspection;
it is not a fuzzy matching or disambiguation heuristic. A relocated citation gets
fresh context from the target snapshot. `accept` accepts only unchanged or uniquely
relocatable quotations and appends a new citation whose `supersedes` field points
to the retained original. Accepting the same snapshot is rejected. If a revision
is ambiguous, inspect it and create a new citation with `cite --start N`; that is
a separately authored citation, not an automatic acceptance.

`cite` requires a unique exact match unless `--start` supplies a matching,
zero-based Unicode code-point offset. For example, in `😀 canal`, `canal` starts
at 2, not at UTF-8 byte 5 or JavaScript UTF-16 position 3. No normalization occurs:
CRLF counts as two code points, composed/decomposed accents differ, and a UTF-8
BOM is retained. Use quoted shell arguments; for complex quotations a Python
caller can invoke the CLI with a subprocess argument list.

## Audit, storage, and recovery

`audit` emits deterministic, sorted JSON. Exit codes: 0 for success (including
warnings), 1 for audit errors, 2 for other command/input failures. It detects bad
schema/version, duplicate identifiers, snapshot hash changes, incorrect excerpts
or stored context, dangling references, invalid relocation chains, and claims
without evidence. Missing evidence is a warning. It does not detect edits to the
original import path: that file is no longer authoritative. Import and compare a
new snapshot to evaluate source changes.

All mutations validate the complete collection and publish one JSON file by an
atomic replacement on the same local filesystem. Writers take a nonblocking
advisory lock; a busy ledger returns an error. Failed validation, fsync, or rename
leaves the previous file unchanged. Output creation uses a no-clobber atomic link;
existing ledgers, reports, and symlink outputs are refused. Back up the JSON file
as you would any research document. Do not run uncooperative writers or edit a
ledger while a command is using it.

A process kill before publication can leave a mode-0600 `.NAME.tmp-XXXXXXXX`
file. With a valid ledger in place, this command removes its abandoned temporary
files while holding the writer lock:

```sh
python3 -m claimledger --ledger /tmp/canal-research/evidence.json cleanup
```

The stable `.lock` file is intentionally retained; never delete it while writers
may be running. A killed report export can similarly leave a temporary file in
its output directory; inspect and delete it manually once the exporter has ended.
There is no promise of survival across power loss or filesystem failure: the
containing directory is not fsynced. Network/distributed filesystems and concurrent
external editors are not supported. The CLI preserves snapshots by convention;
hashes are not signatures and cannot expose coordinated malicious edits to both
text and hashes.

## Format and limits

See [FORMAT.md](FORMAT.md) for the version-1 schema. Identifiers are user-assigned,
stable, globally unique across all three collections, and match
`[a-z][a-z0-9_-]{0,63}`. Every operation that would exceed a limit fails before
publishing a new ledger:

- Each decoded source: at most 512 KiB in original UTF-8 bytes.
- Ledger file and generated report: each at most 8 MiB, including JSON escaping
  and HTML expansion. A valid large ledger can exceed the report limit; export
  then fails without creating the output. Archive export and verification also
  enforce the report limit.
- At most 1,000 sources, 1,000 claims, and 1,000 citations per ledger.
- Claims and each bibliographic field: at most 16,384 code points. Titles and
  claims must be nonempty; author, date, and URL may be empty.
- Exact quotations: nonempty, at most 512 Ki code points and within a source.
  Stored prefix and suffix: up to 80 code points each.

Only regular UTF-8 text files are imported. There is no PDF, HTML extraction,
OCR, binary format support, markdown interpretation, or URL download. Converting
other formats is a separate research step; preserve and describe that process.
Control characters and line endings are preserved in JSON; browsers may visually
normalize them. The report is not an exact byte viewer. Dates and URLs are opaque
metadata, not validated bibliographic identifiers; URLs are displayed as text.

The report uses semantic landmarks, visible focus, labeled controls, native
links/details elements, and a live result count. It remains readable without
JavaScript, with all claims visible. Automated Chromium checks cover keyboard
interaction, mobile overflow, and hostile text; no screen-reader audit or claim
of WCAG conformance has been made. Large reports are rendered in full rather than
virtualized. English-only UI; search uses case folding in the browser, not
language-aware tokenization.

## Verification

Runtime installation is offline. Full developer verification additionally needs
Node.js 18+ and the pinned Playwright Chromium test dependency. One-time setup
(downloads test tools, not research data):

```sh
npm ci --ignore-scripts --cache /tmp/claimledger-npm-cache
PLAYWRIGHT_BROWSERS_PATH=/tmp/claimledger-browsers npx --cache /tmp/claimledger-npm-cache playwright install chromium
```

Then run the single verification command:

```sh
python3 scripts/verify.py
```

It uses the browser cache above when present, otherwise Playwright's default
cache or your `PLAYWRIGHT_BROWSERS_PATH`. It never installs missing dependencies
and fails if browser verification cannot run. Some hosts need Chromium system
libraries installed by their administrator.

The checks include 240 archive round trips (seed 390274), 256 archive bit
corruptions (seed 83719), restoration failure/collision/cancellation tests, and
480 reproducible citation cases (seed 728193) against an independent
brute-force tuple-window oracle, paired corruption cases, Unicode, repeated and
overlapping passages, CRLF, changed quotations, insertion/removal, conflicting
identifiers, malformed inputs, documented limits, lock contention, interrupted
writes, crash cleanup, and an isolated installed executable with socket
operations blocked. Browser tests block network access and exercise search,
filters, restored citations and relocation links, keyboard controls, hostile imported text, and no-JavaScript
reading. A bounded workload records actual runtime, peak Python process RSS,
file sizes, seed, and environment. These are observations of this machine, not
capacity guarantees or a benchmark against other products.

Current machine-readable evidence lives in [results/verification.json](results/verification.json),
[results/benchmark.json](results/benchmark.json),
[results/archive-benchmark.json](results/archive-benchmark.json), [results/browser.json](results/browser.json),
and [results/tests.log](results/tests.log). Verification overwrites those files. The previous milestone evidence is
preserved in [results/baseline/](results/baseline/).
For the Python-only checks: `python3 -m unittest discover -s tests -v`.

## Related work

This is an intentionally small workflow implementation, not a novel anchoring
algorithm. The [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/)
describes quotation/context and position selectors. This ledger uses similar
ideas but is not JSON-LD or a conformant Web Annotation serialization; its offsets
apply to the unnormalized imported text.

[Hypothesis's open-source client](https://github.com/hypothesis/client) implements
web annotation in a much broader browser context. [Zotero's PDF reader and note
editor](https://www.zotero.org/support/pdf_reader) integrate annotations with a
reference library. This project concentrates on local immutable plain-text
snapshots, authored claim links, explicit revision acceptance, and portable
reports. It does not replace either product's document reading or bibliography
management features. These primary sources were inspected on 2026-09-28; no
performance comparison or novelty claim is made.
