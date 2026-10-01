# Offline manuscript comparison, version 1

Compare two saved manuscript bundle directories without a ledger, network,
model, private data, or bibliography service. The output is deterministic
`comparison.json` and a self-contained `comparison.html`. These reports describe
selected authored material and its recorded evidence. They do not assess factual
support, authenticity, truth, or whether an absent claim exists elsewhere.

## Complete example and command

Python 3.10+ and Linux with `renameat2(RENAME_NOREPLACE)` are required for
publication. From a checkout, choose a directory that does not exist:

```sh
python3 scripts/comparison_example.py /tmp/claim-comparison-example
```

Open `/tmp/claim-comparison-example/comparison/comparison.html`. The synthetic
example changes an opening time, revises authored text, changes the selected
source revision and excerpt, reorders sections, repeats a claim, omits a
hypothesis, and adds an uncited suggestion. Its two saved ledgers and manuscript
specifications remain alongside the bundles. A separate authored ledger revision
retains the author's asserted claim IDs; the comparison does not infer identity
from similar wording. The script also archives and restores the later ledger,
rebuilds its manuscript, and checks that comparing the rebuilt bundle produces
identical report bytes.

To compare those bundles again, without opening either ledger:

```sh
python3 -m claimledger manuscript-compare \
  /tmp/claim-comparison-example/before \
  /tmp/claim-comparison-example/after \
  /tmp/claim-comparison-example/another-comparison
```

An [installed CLI](README.md#quick-start) accepts the same subcommand. The
existing `compare SOURCE TARGET` command continues to compare source revisions
inside a ledger; `manuscript-compare BEFORE AFTER DESTINATION` is separate.
An optional `--seconds 10 --work 8388608` lowers the comparison limits. The
command ignores `--ledger`. Exit 0 means a complete report was published, whether
or not there were differences. Invalid/unsupported inputs and exhausted limits
exit 2 with a diagnostic and no report. Cancellation can terminate with the
usual Python/process exit status. No partial report is labeled equivalent.

## Identity and findings

Version 1 makes explicit, mechanical comparisons. It does not implement a
minimal edit script or fuzzy matching. Strings are exact, unnormalized Unicode:
CR, LF, CRLF, BOM, emoji, and combining characters retain their distinctions.
Citation offsets count Unicode code points, start inclusive and end exclusive.

- **Claim ID** is the only stable cross-bundle claim identity. Different IDs are
  added/absent even if their text is identical. A reused ID is the author's
  assertion of identity; hashes cannot prove its origin. All occurrences of a
  claim ID within one bundle must have the same text.
- **Repeated claims** are ordered groups. Their recorded placements and ordered
  citation arrays are compared in document order. There is no guessed pairing
  of occurrences. If a group repeats on either side and its placements or
  selections differ, `ambiguous_occurrences` explicitly records that limitation.
  An identical repeated group has no observable change, but this does not prove
  that indistinguishable occurrences were not exchanged.
- **Sections** have no IDs in manuscript v1. Ordered headings are compared as
  authored text, and claim placements use one-based section/position coordinates
  plus heading text. A heading rename is not inferred to be a section move.
  Duplicate headings set `ambiguous_section_headings`. Insertions can shift many
  placements; the report calls these position changes, not independently proven
  moves. Empty sections remain represented by the ordered headings comparison.

Findings are sorted by `(id, kind)`, with document findings using the empty ID.
The available kinds are:

| Kind | Meaning |
| --- | --- |
| `title` | Authored title changed. |
| `sections` | Ordered section headings changed. |
| `claim_order` | Flattened ordered claim IDs changed, including additions, omissions, and repeated occurrences. |
| `added`, `absent` | ID occurs in only the after/before bundle; includes its text and occurrences. |
| `claim_text` | Exact authored text for a shared ID changed. |
| `placement` | The group's ordered section/heading/position coordinates changed. |
| `citation_selection` | The group's ordered per-occurrence citation ID arrays changed, preserving duplicates. |
| `ambiguous_occurrences` | Repeated occurrences cannot be individually paired across the changed group. |
| `source_revision` | Selected source metadata sets, or source metadata assigned to shared citation IDs, changed. Includes revision ID, content hash, title, author, date, and recorded URL. |
| `excerpt` | Selected quotation/offset/context sets, or those values assigned to shared citation IDs, changed. |
| `source_evidence` | Selected `(source metadata, excerpt)` pairs changed, including their assignment to shared citation IDs. This also detects reassociation when the separate sets agree. |
| `citation_lineage` | `supersedes` changed for a shared selected citation ID. |
| `provenance` | Recorded ledger or specification hash changed. The ledger hash is not independently verifiable without the ledger. |

Source/excerpt sets deliberately ignore repeated selections. Such repetitions
are already represented in `citation_selection`. Selecting a different citation
can produce both selection and evidence findings; these dimensions are not
exclusive. Renaming a citation while preserving identical evidence changes
selection alone, apart from any provenance change. Source and excerpt findings
contain the before/after selected citation IDs; full citation records and source
metadata appear once per side in JSON and in the linked HTML evidence appendix.
Added/absent groups include their selected records there without separate
per-field findings for a group that has no counterpart.

`outcome: "no_semantic_changes"` means all the fields above agree. It does **not**
mean the input bytes are identical: presentation bytes, JSON whitespace, and
record array order may differ. `outcome: "differences"` includes provenance-only
changes. Both outcomes have `complete: true`; there is no successful partial or
unsupported result. Limits may reject two otherwise valid large manuscripts.

## Input verification and deterministic output

Only manuscript format `claim-source-ledger-manuscript`, version 1, is supported.
The loader checks the strict manifest schema, specification hash, resolved
sections, selected claim texts, exact citation ownership and selection, unique
record IDs, source metadata, and the exact expected file set. It rejects
symlinks, nonregular files, unknown entries, duplicate JSON keys, non-finite
numbers, unsupported conventions/versions, invalid Unicode and malformed paths.
Only fixed file names and validated snapshot hashes become filesystem paths.
Files are opened with `O_NOFOLLOW` relative to directory descriptors.

Every bundle file's size/hash is checked, including Markdown and HTML.
Snapshots must be strict UTF-8 and agree with the recorded source SHA-256;
exact quoted text, code-point offsets, and context must agree with the snapshots.
As in manuscript v1, an unselected `supersedes` ancestor may be absent. Present
ancestry must be consistent and acyclic; complete lineage validation requires
the original ledger/archive. An ancestor cannot name a selected non-citation
record. Unselected claims/sources are not inferred or reconstructed.

Imported manuscript HTML and Markdown are treated as opaque bytes for hashing;
they are never executed, parsed into the report, or used to override manifest
content. A hash-consistent presentation file is not certified as the exact
output of the original renderer. All comparison content comes from the
validated manifest and source snapshots. This permits presentation differences
without inventing authored differences. Self-declared hashes detect corruption,
not a coordinated rewrite or forgery.

`inputs.before` and `inputs.after` include every exact input file's bytes and
SHA-256 (including the manifest). Their `sha256` values hash the canonical JSON
file inventory: sorted keys, two-space indentation, literal Unicode, final LF.
Input paths, current time, elapsed time, and random staging names do not enter
the report. JSON uses the same canonical convention. Repeated comparisons of
unchanged inputs produce identical JSON and HTML bytes. CLI stdout separately
reports output file hashes/sizes and the destination pathname.

The report embeds neither original rendered HTML nor remote resources. All
imported content is HTML-escaped. A content security policy allows only the
hash-pinned, fixed filter script and inline styles; it blocks external resources,
base URL changes, and form submission. Recorded URLs are inert text. The core
application imports no networking library and makes no network requests.

## Bounds and publication

| Resource | Version 1 maximum |
| --- | --- |
| Total input bytes per bundle, including manifest and rendered files | 16 MiB |
| Individual snapshot | 512 KiB |
| Selected source bytes per bundle, counting each revision ID | 4 MiB |
| Selected source revision IDs per bundle | 100 |
| Claim occurrences per bundle | 500 |
| Citation selections per bundle, counting repeats | 2,000 |
| Unique selected citation records per bundle | 1,000 |
| Sections per bundle | 100 |
| Canonical specification | 256 KiB |
| Claim text | 16,384 code points |
| Comparison work | 64 MiB of canonical projection bytes and evidence bytes visited |
| Runtime | 30 seconds, checked cooperatively from command start through pre-commit |
| Combined JSON and HTML output | 16 MiB |

Existing manuscript title/heading/metadata limits also apply. Work accounting
charges canonical projection encodings and the evidence-set/pair bytes visited;
it is a deterministic unit of comparison work, not CPU instructions. Input
validation is bounded separately by bytes and collection counts. Serialization
and rendering check size incrementally and the two output sizes are checked
in aggregate. All data is processed in memory; these bounds are not an RSS cap.
A deadline is checked between bounded reads, validation phases, comparisons,
serialization chunks, writes and immediately before commit. It is **not** a hard
interrupt for a blocked filesystem operation, a single JSON parsing operation,
or cleanup. The CLI can lower but cannot raise either work or runtime caps.

No output path may be inside either input bundle. Inputs are read once for
analysis and their file inventories/hashes are rechecked before staging. No
ledger lock or input writes are needed. Use saved, quiescent local directories:
uncooperative edits after the final check, parent-directory replacement,
network filesystem behavior, and hostile concurrent filesystem mutation are
outside this snapshot contract.

After successful validation, analysis, serialization and rechecking, both files
are written and fsynced in a private sibling `.DEST.comparison-XXXXXXXX`
directory. The sole commit point is Linux `renameat2(RENAME_NOREPLACE)`; an
existing or concurrently created destination is never overwritten. There is
no unsafe rename fallback. Ordinary failures, cancellation and serialization
exceptions leave no destination and clean up staging. A failure after the first
write cannot publish a one-file report.

SIGKILL, default SIGTERM, power loss or cleanup permission failure can leave a
private stage. After confirming the exporter has stopped, inspect and remove
that specific orphan; do not rename it into a report. Killing after commit
leaves the complete report. The parent directory is not fsynced after commit,
so power-loss durability is not guaranteed. Failure to receive stdout after
commit does not imply the output was rolled back.

## Verification, measurements, and limits

After the [developer setup](README.md#verification), the single full check is:

```sh
python3 scripts/verify.py
```

This retains existing ledger/archive/manuscript regressions and adds 240
seeded bundle pairs (seed 908172) compared against a separate linear/tuple
reference implementation. The pairs cover simultaneous text, ordering,
selection, revision, excerpt and membership changes; repeated claims; duplicate
headings; multiple revisions; Unicode; line endings; and hostile markup.
Regressions cover malformed references, tampering, exact output limits,
input/source/claim/work/runtime limits, altered inputs, serialization/write
failure, cancellation, destination races, SIGKILL before/after commit, omitted
ancestors and swapped citation evidence. Every seeded pair checks unchanged
inputs and byte-identical repeated output.

An isolated installed CLI blocks socket operations, creates a ledger and two
manuscripts, rebuilds the later manuscript from an archive, deletes both ledgers,
and compares the bundles. The restored comparison must be byte-identical.
Network-blocked Chromium tests every finding filter, before/after controls,
keyboard navigation, context expansion, return to hidden findings, all fragment
targets, hostile markup, a 390px viewport and JavaScript-disabled reading.

[results/comparison-benchmark.json](results/comparison-benchmark.json) contains
actual runtime, Linux peak process RSS, input/output sizes and hashes, environment,
and repeatability checks for a seeded 300-claim, 12-source, 600-selection workload.
RSS covers the entire benchmark process, including fixture setup, manuscript
builds, saved input copies, and two comparisons. This is a bounded workload
observation, not a performance claim or maximum-capacity guarantee.
[results/comparison-browser.json](results/comparison-browser.json) records actual
browser checks. Historical measurements are preserved in
`results/manuscript-baseline/`, `results/archive-baseline/`, and `results/baseline/`.

The HTML uses native select controls, fragment links, details/summary and visible
focus outlines. Filtering/view controls require JavaScript; all findings and
both sides remain readable without it. Returning to a hidden finding clears the
type filter. Browser rendering can normalize newlines and display controls
unfaithfully; JSON and snapshot bytes remain authoritative. There is no
screen-reader audit, WCAG conformance claim, cross-browser or cross-Python-version
byte reproducibility test. No rich-text diff, PDF comparison, bibliography style
engine, factual-support assessment, or inferred cross-ledger identity is included.

## Existing work and design scope

Reviewed on 2026-10-01: [Git's diff documentation](https://git-scm.com/docs/git-diff.html)
describes line/word comparisons and configurable diff algorithms.
[CPython's difflib implementation](https://github.com/python/cpython/blob/main/Lib/difflib.py)
implements sequence matching with matching-block and popular-element heuristics.
Those implementations inform the decision to avoid similarity-based identity for
repeated authored claims. This feature uses straightforward exact, structural
comparisons over existing manuscript IDs and evidence records. It makes no claim
to a novel diff algorithm and does not invoke Git or difflib at runtime.
