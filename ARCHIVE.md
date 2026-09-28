# Archive format and recovery, version 1

An archive is a bounded, canonical ZIP file containing a complete ledger and its
immutable UTF-8 snapshots. It is an offline backup/interchange format, not a
signature, encrypted container, general ZIP extractor, or evidence of factual
truth. No command fetches a URL or executes archive contents. A party able to
rewrite an archive can recompute its manifest; compare the returned SHA-256 with
a value obtained through a separately trusted channel when authenticity matters.

## CLI and backup workflow

```sh
python3 -m claimledger --ledger /tmp/canal-research/evidence.json export /tmp/evidence.zip
python3 -m claimledger verify /tmp/evidence.zip
python3 -m claimledger restore /tmp/evidence.zip /tmp/recovered-evidence
python3 -m claimledger --ledger /tmp/recovered-evidence/ledger.json audit
python3 -m claimledger --ledger /tmp/recovered-evidence/ledger.json compare notice revision
python3 -m claimledger --ledger /tmp/recovered-evidence/ledger.json report /tmp/recovered-report.html
```

`export` refuses an existing output. `verify` only reads the archive; `restore`
requires an absent destination whose parent already exists. Even an empty
existing directory, file, or dangling symlink is refused. All three commands
return JSON on success and exit 0; invalid input, collisions, exhausted limits,
and unavailable platform features return a diagnostic on stderr and exit 2.
`verify` includes the full archive SHA-256, byte sizes and record/file counts.
Warnings for claims with no evidence do not invalidate an archive. `--ledger`
selects the export input; it has no effect on verify or restore.

Export/verification need Python 3.10+ on POSIX. **Transactional restore currently
requires Linux with libc/kernel/filesystem support for
`renameat2(RENAME_NOREPLACE)`.** Other platforms fail without publishing a
restoration; there is deliberately no check-then-rename fallback. The archive
itself is platform-independent. Cross-version byte reproducibility has only been
tested on the Python version recorded in the results; the profile below fixes
all serialized metadata and uses no compression library.

Keep archives separately from the working ledger and periodically verify and
restore a backup into a new directory. An archive includes all source text and
metadata and needs the same access controls as the ledger. The tools do not
provide encryption or off-device storage. Original imported files need not exist.

## Payload allowlist and manifest

Exactly these files are permitted, with no directory entries:

- `ledger.json`: the complete version-1 ledger, serialized as in [FORMAT.md](FORMAT.md).
- `snapshots/<sha256>.txt`: one file for each distinct snapshot content hash in
  `ledger.json`; exact UTF-8 bytes, including BOMs, line endings, and empty text.
- `manifest.json`: the canonical JSON object below, listing every other file.

There are no lock files, generated reports, executable code, local paths, or
unreferenced files. Sources with identical text share a snapshot file but retain
all individual source IDs and metadata inside the ledger. Records and array order
are preserved, including original citations, accepted relocations, and their
`supersedes` relationships. Source history is not inferred from filenames.

Manifest shape (descriptive placeholders, not a valid fixture):

```json
{
  "files": {
    "ledger.json": {"bytes": 1234, "sha256": "<64 lowercase hex digits>"},
    "snapshots/<content hash>.txt": {"bytes": 42, "sha256": "<content hash>"}
  },
  "format": "claim-source-ledger",
  "version": 1
}
```

The manifest does not hash itself; the CLI reports a SHA-256 over the entire
archive. Unknown fields, duplicate JSON keys, non-finite numbers, non-integer
sizes/versions (including booleans), and unsupported versions are rejected.
The manifest and ledger use canonical UTF-8 JSON: sorted object keys, two-space
indentation, literal Unicode, and a final newline. Ledger array order is semantic;
changing it changes archive bytes. Original JSON whitespace is not preserved.

## ZIP profile and bounds

Files appear in lexicographic path order in both local headers and the central
directory. Each uses ZIP_STORED (method 0), flags 0, versions made/extract 20,
Unix creator system 3, regular-file mode 0600, timestamp 1980-01-01 00:00:00,
zero internal attributes and zero disk number. Sizes and CRC-32 are in the
headers. No encryption, descriptors, ZIP64, extras, comments, padding, preambles,
trailing data, or additional local headers are allowed. Paths are ASCII and
case-sensitive. The central directory immediately follows the payloads and is
followed by a 22-byte end record. Empty source content is allowed.

This deliberately narrow profile means that generic ZIP tools can *read* an
archive, but repacking it will usually make it invalid. Deflate and other
compression methods are unsupported even when their expanded data would fit.
Stored entries trade space for deterministic bytes and avoid decompression bombs.
The verifier reconstructs and byte-compares the canonical archive after semantic
validation, rejecting alternate local/central headers or hidden content.

| Resource | Maximum |
| --- | ---: |
| Entire input container (compressed-byte budget, including headers) | 20 MiB |
| Sum of expanded member bytes, including manifest | 18 MiB |
| Entries including ledger and manifest | 1,002 |
| Central directory bytes | 160 KiB |
| Manifest bytes | 256 KiB |
| Ledger bytes | 8 MiB |
| Each snapshot | 512 KiB |
| Generated report | 8 MiB |

Existing record, string, and quotation limits also apply. The report is generated
and size-checked in memory during export and verification but is not included in
the archive. Thus a ledger that cannot produce a bounded report cannot be
archived in version 1. No output is published on a limit failure. The container
and directory/count limits are checked before ZIP member objects are allocated;
member and total expanded sizes are checked before reading content. Memory is
bounded but holds several copies of the archive/ledger/report; the byte limits
are not peak-RSS limits.

Verification checks CRCs, exact member sets, file hashes and sizes, ledger schema,
global IDs, source hashes, all claim/source/revision references, relocation
cycles, quotation offsets and text, and stored context. Snapshot files must agree
byte-for-byte with embedded source text and content-addressed names. Paths such
as `../x`, absolute paths, backslashes, alternate separators, duplicates, links,
and unexpected files cannot be restored. The implementation never calls ZIP
`extract` or `extractall`.

## Transaction boundary and failure recovery

Export holds the ledger's existing nonblocking mutation lock through validation
and publication. It reads and checks the ledger bytes again before publishing,
which detects a noncooperating writer if the resulting bytes differ. All
cooperating commands must use the same absolute ledger path, without symlink or
hard-link aliases. External editors, deletion/replacement of the stable lock
inode, ABA edits, and hostile concurrent filesystem manipulation are outside the
coordination guarantee. Use trusted local directories, not network filesystems.
Export publishes a completed, fsynced temporary archive with an atomic no-clobber
hard link. It does not overwrite an older backup.

Restore reads and validates the entire archive **before creating staging files**.
It creates a private mode-0700 `.DEST.restore-XXXXXXXX` directory beside the
intended destination, writes mode-0600 files, fsyncs every file and the staged
directories, then performs one atomic no-replace directory rename. That rename is
the sole commit boundary. A competing creator wins without its destination
being changed, including when it creates an empty directory.

Before the boundary, an ordinary error or Python cancellation removes the private
stage on a best-effort basis and leaves no destination. After the boundary, the
destination contains the whole restoration; cleanup cannot roll it back. A
SIGKILL, SIGTERM, host crash, or loss of permissions can leave a private stage.
It is never advertised as a completed ledger. Once the process is known to have
ended, inspect and remove **that specific** orphan stage manually; do not delete
stages belonging to active restores. Retry from the verified archive into an
absent destination. Do not promote an orphan stage as a recovery shortcut.
A kill immediately after commit can leave a complete destination without a CLI
success message: audit it and compare a re-export with the original archive.

The published directory contains `ledger.json` plus `snapshots/`. The embedded
snapshots in `ledger.json` remain authoritative for future authoring; the extra
snapshot files are a restoration artifact. Future exports derive their snapshots
from the ledger and do not treat those files as a second mutable database.
The archive manifest is not copied into the working directory because later
ledger mutations would make it stale. Reports and `.lock` files are regenerated.

**Power-loss durability is not promised.** The destination's parent directory
is not fsynced after rename, so a power loss may lose the publication even though
the CLI returned success. Local process crashes and filesystem power failures
are different guarantees. There is no rollback after commit, automatic orphan
cleanup, backup retention manager, or cross-filesystem move.

## Compatibility and implementation references

Version 1 accepts only this profile and ledger schema version 1. Future
incompatible formats require a new explicit archive version and migration tool;
there is no silent downgrade, best-effort extraction, or skipped unknown member.
Preserve the original archive when migrating. Verification proves internal
agreement, not source authenticity or the factual truth of any claim.

The design uses existing techniques, with no novelty claim. Reviewed primary
references and implementations on 2026-09-28:

- Python's [zipfile documentation](https://docs.python.org/3/library/zipfile.html)
  and the installed CPython `ZipFile._RealGetContents`/`writestr` implementations:
  explicit `ZipInfo` metadata, per-entry reads, duplicate-name hazards, and
  pre-allocation directory checks.
- The repository's `scripts/install.py` uses Python `zipapp` for offline executable
  packaging. Archive data intentionally uses a separate non-executable allowlist.
- Linux's [rename(2) documentation](https://man7.org/linux/man-pages/man2/renameat2.2.html)
  specifies the atomic rename and `RENAME_NOREPLACE` collision semantics used here.

Run `python3 scripts/verify.py` for all verification. The suite includes 240 seeded
round trips (seed 390274) with independent JSON record/snapshot comparisons,
repeated quotes, Unicode, line endings, deduplication, multiple revisions and
relocation chains; 256 seeded bit corruptions (seed 83719); structural and semantic
corruptions; limit failures; collisions; interrupted writes; cancellation; and
SIGKILL on both sides of the restore boundary. The isolated installed CLI rejects
socket operations and completes export/verify/restore/audit/compare/report;
network-blocked Chromium exercises the restored report and relocation links.
[results/archive-benchmark.json](results/archive-benchmark.json) records actual
runtime, peak process RSS, hashes, sizes, seeds, and environment for a synthetic
40-source, 120-claim, 240-citation workload. These are observations, not capacity
guarantees. The previous milestone's evidence is retained in `results/baseline/`.
