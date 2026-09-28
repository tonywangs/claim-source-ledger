# Ledger format, version 1

The file is one UTF-8 JSON object. Duplicate JSON object keys, non-finite numbers,
unknown fields, unsupported versions, and invalid Unicode surrogate code points
are rejected. Array order is preserved. Authoring and export use sorted JSON
object keys, two-space indentation, literal Unicode, and a final newline.

```json
{
  "version": 1,
  "sources": [
    {
      "id": "s1",
      "title": "Synthetic example",
      "author": "",
      "date": "",
      "url": "",
      "text": "Before 😀 after.\r\n",
      "sha256": "<64 lowercase hexadecimal digits>"
    }
  ],
  "claims": [{"id": "c1", "text": "An authored observation."}],
  "citations": [
    {
      "id": "q1",
      "claim": "c1",
      "source": "s1",
      "start": 7,
      "end": 8,
      "quote": "😀",
      "prefix": "Before ",
      "suffix": " after.\r\n",
      "supersedes": null
    }
  ]
}
```

The hash above is a descriptive placeholder, not a valid fixture. Generate hashes
with `SHA256(text.encode('utf-8'))`; strict UTF-8 decode/encode round-trips the
original bytes, including BOM and line endings. No encoding detection,
normalization, or newline conversion is performed during import. The text and
bibliographic fields are a snapshot, not a link to a mutable filesystem path.
There is no implicit “latest” snapshot; revision comparison names both IDs.

All listed fields are required, including empty metadata and context fields.
IDs are globally unique. Offsets are integers (not booleans), `0 <= start < end <= len(source text)`,
using half-open Unicode code-point indexing, independent of bytes or UTF-16.
The quotation must equal `text[start:end]`. Prefix must equal the immediately
preceding substring of its recorded length; suffix must equal the following
substring. Empty context is valid. The CLI records up to 80 code points on each
side; shorter manually authored contexts are accepted if they agree exactly.

`supersedes` is null for an original citation, or the ID of an existing citation
to the same claim and exact quotation. Cycles are invalid. Explicit acceptance
creates the new citation on a different snapshot; old citations remain immutable
through the CLI. Audit validates structural ancestry, not a signed record of who
accepted it or whether it was created through the CLI.

Audit envelope:

```json
{
  "version": 1,
  "ok": true,
  "issues": [
    {"code": "claim_without_evidence", "id": "c2", "severity": "warning"}
  ]
}
```

Issues sort by ID and code. All severities except missing evidence are errors.
Malformed schema returns a single `schema` error with a diagnostic `message`;
unreadable/invalid JSON returns `unreadable_ledger`. Error messages are diagnostic
and may contain local paths, while issue codes are stable within version 1.
The boolean `ok` means no integrity errors, not that all claims are evidenced.

Comparison envelope has `version`, `source`, `target`, and `citations`, sorted
by citation ID. Each result has `citation`, `status`, `positions` (up to the
first 64 matching offsets), and `positions_truncated`. Original citations are
included even if a later citation supersedes them. No timestamps or random IDs
are generated, so audit, comparison, ledger serialization, and report output are
deterministic for identical inputs and operation order.

The JSON file is the transaction boundary: mutations load and audit it under a
POSIX advisory lock, modify an in-memory copy, validate size/integrity, write and
fsync a same-directory private temporary file, then atomically replace the old
file. Read-only commands see either the old or new complete file. The lock file
is separate and persistent so cooperating processes agree on one lock inode.
Output reports and new ledgers use a hard link from a complete temporary file to
publish without clobbering a competing creator. There is no multi-file commit.

A future incompatible schema requires a new version and an explicit migration;
version 1 readers refuse it. JSON is intentionally inspectable but manual editing
bypasses immutability conventions. Hashes provide error detection, not provenance
attestation or security against deliberate tampering.

Portable backups use the separate bounded [archive format version 1](ARCHIVE.md).
The archive carries this complete JSON ledger and exact content-addressed snapshot
bytes, without changing the ledger schema or revision semantics.
