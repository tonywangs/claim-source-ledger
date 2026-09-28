# Offline manuscripts, version 1

A manuscript is an authored ordering of ledger claims with explicit citation
selections. The builder produces `manuscript.md`, self-contained
`manuscript.html`, `manifest.json`, and selected full UTF-8 source snapshots.
It checks citation integrity, not factual support, authenticity, or truth.
No model, service, bibliography download, or private data is required.

## Complete synthetic example

From a checkout with Python 3.10+ on Linux, choose a directory that does not exist:

```sh
python3 scripts/example.py /tmp/manuscript-example
```

This creates a ledger, imports two invented notices, authors three claims,
records three original citations, accepts a relocation, and produces the existing
report plus a manuscript. Open
`/tmp/manuscript-example/manuscript/manuscript.html` locally. The manuscript cites
both revisions for the opening claim, includes an explicitly uncited hypothesis,
and omits the third claim by author choice. Its specification is
[examples/manuscript.json](examples/manuscript.json).

To build that specification again into a fresh directory:

```sh
python3 -m claimledger --ledger /tmp/manuscript-example/example.json manuscript \
  examples/manuscript.json /tmp/manuscript-second-build
```

For backup and reconstruction through the installed CLI:

```sh
python3 scripts/install.py --prefix /tmp/manuscript-cli
/tmp/manuscript-cli/bin/claimledger --ledger /tmp/manuscript-example/example.json export /tmp/manuscript-example.zip
/tmp/manuscript-cli/bin/claimledger verify /tmp/manuscript-example.zip
/tmp/manuscript-cli/bin/claimledger restore /tmp/manuscript-example.zip /tmp/manuscript-restored
/tmp/manuscript-cli/bin/claimledger --ledger /tmp/manuscript-restored/ledger.json manuscript \
  examples/manuscript.json /tmp/manuscript-from-restored
```

The two rebuilt bundles have identical file bytes. Each command refuses existing
output paths. A manuscript is a selected view, **not a complete ledger backup**;
keep the ledger or its archive and the specification to reproduce it.

## Specification semantics

The specification is strict UTF-8 JSON with exactly these fields:

```json
{
  "version": 1,
  "title": "An authored title",
  "sections": [
    {
      "heading": "An authored heading",
      "claims": [
        {"id": "opening", "citations": ["opening-original", "opening-relocated"]},
        {"id": "unverified", "citations": []}
      ]
    }
  ]
}
```

Every field is required. Unknown fields, duplicate JSON keys, non-finite numbers,
invalid Unicode surrogates, and unsupported versions (including boolean `true`)
are rejected. Titles and headings are nonempty plain text. All identifiers obey
the ledger identifier grammar. A section may have no claims, but the document
must have at least one claim occurrence. There is one heading level; nesting,
free paragraphs, formatting directives, and inferred citations are not supported.

Sections, claims within a section, and citations within each occurrence appear
in exactly the specified array order. Repeating a claim or citation is allowed;
each claim occurrence has its own HTML anchor. Citation appendix entries are
unique and sort by citation ID. Repeating a citation preserves the repeated
inline link; return links list each referencing claim occurrence once. Source
appendix entries sort by source revision ID. No implicit latest revision,
relocation substitution, or automatic evidence selection occurs.

A selected citation must belong to its selected claim. An empty citation array
is visibly labeled **Uncited claim**, even when the ledger contains citations
that the author did not select. All ledger records are validated before any
output, including unselected records and relocation history. Missing claims,
citations or sources, altered snapshot hashes, quote/context mismatches, invalid
ancestry, and unsupported ledger versions fail the entire build.

## Output and provenance

`manifest.json` uses the ledger's canonical JSON convention: sorted object keys,
two-space indentation, literal Unicode, and a final LF. It contains:

- `format: "claim-source-ledger-manuscript"`, `version: 1`, and the integrity notice.
- `specification` and its canonical SHA-256, plus SHA-256 of the complete canonical
  input ledger. Insignificant JSON whitespace and key ordering do not affect
  these hashes; ledger array ordering does. No paths, clocks, or random IDs occur.
- `sections`: ordered headings and resolved claim occurrences, with exact claim
  text, ordered citation IDs, and an `uncited` boolean.
- `citations`: selected original citation records, including exact quotation,
  context, source revision ID, offsets, and `supersedes`. An ancestor may be
  unselected and therefore absent; use the ledger/archive for complete history.
- `sources`: selected revision metadata and snapshot hashes, excluding inline
  source text. `snapshots/<sha256>.txt` contains the corresponding original bytes.
  Identical snapshots share one file while retaining separate revision metadata.
- `files`: byte count and SHA-256 for every other bundle file. The manifest does
  not hash itself; the CLI result supplies its hash. These are corruption checks,
  not signatures or independently trusted attestations.

Offsets are zero-based **Unicode code points**, start inclusive and end exclusive,
with no text normalization. CRLF occupies two positions, an emoji generally one,
and combining marks have their own positions. BOMs are retained. The exact
excerpt is `source_text[start:end]`; snapshots and JSON are authoritative.
Browsers can normalize line endings or display control characters differently.

The HTML is self-contained and script-free. Tab/Enter activate the skip link,
section links, citation links, return links, and native expandable context/full
snapshot controls. Source URLs are displayed as text and are never fetched or
made active. Imported titles, claims, quotations, and metadata are HTML-escaped.
The content security policy also disables scripts and external resources.

The Markdown uses ordinary headings/links and fixed HTML appendix anchors.
Authored punctuation and controls use numeric character references so they
cannot become Markdown links, raw HTML, images, or formatting. Render with a
CommonMark-compatible reader that permits fixed HTML anchors for navigation;
readers that strip anchors may lose links. Literal line endings and controls
may display differently in Markdown renderers. Exact authored text remains in
the manifest; this is not a rich Markdown authoring interface or a CSL
bibliography formatter. HTML is the tested interactive reading surface.

## Bounds and transaction contract

| Resource | Maximum |
| --- | --- |
| Specification file and canonical specification | 256 KiB each |
| Title or heading | 1,024 Unicode code points each |
| Sections | 100 |
| Claim occurrences, counting repetitions | 500 |
| Citation selections, counting repetitions | 2,000 |
| Selected source revision IDs | 100 |
| Sum of selected source UTF-8 bytes, counting each revision | 4 MiB |
| Complete bundle, including manifest and snapshots | 16 MiB |

Existing limits also apply: an 8 MiB ledger, 512 KiB per source, at most 1,000
records per collection, and 16,384 code points per claim. Rendered text is
bounded during accumulation and the aggregate is checked before staging.
All output is built in memory; these bounds are not process-memory guarantees.
Individual artifacts are additionally bounded by the aggregate cap.

The specification is read once. The builder takes the same persistent,
nonblocking advisory lock used by ledger mutations, reads and validates the
ledger, builds the bundle, and rechecks the original ledger bytes. It holds the
lock through publication. A busy lock fails without waiting. Ledger and
specification bytes are unchanged; a persistent `.lock` file may be created.
Use the same ledger pathname for cooperating processes. Aliases, uncooperative
writers, parent-directory replacement, and distributed filesystems are outside
the coordination contract.

After complete validation and serialization, files are written and fsynced in a
private sibling directory `.DEST.manuscript-XXXXXXXX`. Staged directories are
fsynced. **The sole commit boundary is Linux
`renameat2(RENAME_NOREPLACE)`**, which makes the complete directory visible in one
operation and refuses a competing creator, including an empty directory or
symlink. There is no unsafe check-then-rename fallback. No existing artifact is
overwritten. Normal write failures, exceptions, and Python cancellation clean up
the stage. Serialization failure occurs before staging.

SIGKILL, default SIGTERM, power loss, or cleanup permission changes can leave a
private stage. Once all related exporters have stopped, inspect and remove that
specific orphan manually; retry the original command into an absent destination.
Never treat or rename an orphan as a committed bundle. A kill after commit leaves
a complete bundle. The parent directory is not fsynced after commit, so power-loss
durability is not guaranteed. A broken stdout pipe or kill after commit may prevent
receipt of the CLI success message; inspect the destination before retrying.

## Verification and limitations

After the [documented developer setup](README.md#verification), run:

```sh
python3 scripts/verify.py
```

This includes 240 seeded manuscript cases (seed 681203) checked against a linear
reference resolver and tuple-based excerpt checks; repeated builds must have
identical bytes. Cases include repeated selections, multiple revisions, Unicode,
CR/LF/CRLF, reordered sections/claims, missing references, and hostile markup.
Regressions cover locking, unchanged inputs, bounds, corrupt snapshots,
serialization and write failures, cancellation, collision races, and SIGKILL
before/after commit. An isolated installed CLI blocks socket operations and
rebuilds an identical manuscript after archive restoration. Network-blocked
Chromium exercises keyboard navigation, excerpt expansion, literal hostile text,
all fragment targets, small-screen layout, and script-disabled reading.

[results/manuscript-benchmark.json](results/manuscript-benchmark.json) records
actual wall time, Linux peak process RSS, artifact sizes/hashes, and environment
for 300 synthetic claims across 12 sources with 600 citation selections. It
includes two builds and confirms identical output. Measurements are machine
observations, not capacity promises or performance comparisons.
[results/manuscript-browser.json](results/manuscript-browser.json) records browser
checks. Historical evidence remains in `results/baseline/` and
`results/archive-baseline/`.

No screen-reader audit, WCAG conformance claim, cross-Python-version byte
reproducibility test, bibliography style engine, PDF generation, or factual
support assessment is included. No private or paid data was needed. Snapshot
exports include the full selected source text, not only quoted excerpts.

## Related work and design scope

The [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/)
describes position and quotation/context selectors. The manuscript retains the
ledger's unnormalized code-point convention rather than claiming conformance to
W3C text processing or JSON-LD serialization.
[Pandoc's citation documentation](https://pandoc.org/MANUAL.html#citations) and
[its Citeproc implementation](https://github.com/jgm/pandoc/blob/main/src/Text/Pandoc/Citeproc.hs)
show ordered citation processing, bibliography selection, and formatted
references. This builder concentrates on an offline, exact-excerpt audit trail
for an explicitly selected subset of a versioned ledger. It does not implement
Pandoc/CSL compatibility or a new citation algorithm. These primary sources and
the existing ledger/archive implementation were reviewed on 2026-09-28.
