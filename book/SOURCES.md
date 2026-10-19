# Sources, provenance, and limits

This book uses historical sources accessible without credentials. They were
retrieved on 2026-10-19. Exact URLs, byte counts, hashes, author/date metadata,
source roles, and extraction choices are in [sources/catalog.json](sources/catalog.json).
The reading edition contains a bibliography and complete selected excerpts. Its
companion evidence edition embeds the full retained textual snapshots.

## Four retained texts

- **William Howard Russell, The Atlantic Telegraph (1865)**, Project Gutenberg
  [no. 40948](https://www.gutenberg.org/ebooks/40948). The retained HTML is the
  digital transcription of a Naval Institute Press reprint. Russell accompanied
  the 1865 expedition; his earlier history is retrospective. He also prints
  technical descriptions and company documents. These documents preserve what
  participants claimed and specified, not independent confirmation of every
  performance assertion. The extraction starts at printed p.1, preserves explicit
  printed-page markers, and collapses whitespace. Raw HTML, including reprint
  front matter and Gutenberg notices, is retained. No source illustrations are
  reproduced in the reading edition.
- **Chamber of Commerce of New-York, The Atlantic Telegraph: Report of the
  Proceedings at a Banquet Given to Mr. Cyrus W. Field**, November 15, 1866;
  [Internet Archive item](https://archive.org/details/atlantictelegrap00newyrich).
  The complete scan and original OCR are retained. The cited speech is a
  contemporary participant's account, delivered at an event honoring him.
  Its measurements, explanation of delays, and claims about success are
  attributed accordingly. Whitespace is collapsed; OCR spelling and split words
  are preserved. Printed p.30, for example, is PDF page36 (one-based).
- **Henry M. Field, History of the Atlantic Telegraph (1866), p.361**, from
  [this scanned volume](https://archive.org/details/historyatlantic04fielgoog).
  The selected page reproduces Cyrus Field's July27 arrival telegram. Henry was
  Cyrus's brother. This is not an original telegram slip and not an independent
  eyewitness confirmation. Only the relevant page and a selected transcription
  are retained. Joining line-end hyphens and normalizing typographic quotation
  marks/dash spacing is documented in the text. The transcription stops at the
  page boundary rather than inventing the remainder of a sentence.
- **The Times and General Commercial Gazette**, St. John's, Newfoundland,
  August1, 1866, [Memorial University scan](https://dai.mun.ca/pdfs/timesgeneral/TimesAndGeneralCommercialGazette18660801.pdf).
  The retained scan page3, second full column, has a July29 Heart's Content report
  and a July31 telegram in the Postscript. Both selected items were transcribed
  from the page image, not accepted from its poor OCR. The intervening London
  news item is omitted; the selection is explicitly marked. A separately
  published newspaper is not necessarily independent authorship: the second
  telegram is attributed to Cyrus Field.

The historical works are public domain in the United States. Provider notices
remain in retained raw files where supplied. No newly commissioned illustration,
licensed dataset, or private personal information was used.

## Reproducible source preparation

The complete Russell HTML and banquet OCR/PDF are saved unchanged. Running
`python3 scripts/book_sources.py` recreates the two normalized text snapshots.
The ordinary build also re-extracts them in memory and requires exact agreement.
Every citation stores exact Unicode code-point offsets, the matching quotation,
and surrounding context in the native ledger. The book notes add printed page
or newspaper column locations and snapshot line numbers.

The two single-page facsimiles were split from public downloads with PyMuPDF
1.26.5. To re-create them separately, download the source PDFs from the catalog
URLs to a temporary directory; do not replace pinned research inputs automatically.
The catalog records the complete original downloads' hashes and sizes. With
PyMuPDF 1.26.5 installed in your own environment, the extraction operation is:

```python
import pymupdf
source = pymupdf.open("downloaded-original.pdf")
shard = pymupdf.open()
shard.insert_pdf(source, from_page=page_index, to_page=page_index)
shard.save("selected-page.pdf", garbage=4, deflate=True)
```

Use zero-based `page_index = 363` for Henry Field's printed p.361, or `2` for the
newspaper scan page3. Extraction may vary in PDF metadata; the checked-in shard
hashes identify this edition's exact files. These optional downloads and PyMuPDF
are **not required** to build or verify the book from this checkout. The full
newspaper download exceeds the per-file repository limit, so only the cited page
is retained. The text selections can be re-created by reading those page images;
manual transcription is not represented as an automated OCR transformation.

## Open questions and access gaps

The book does not adjudicate the full cause of the 1858 failure. It reports
Russell's attributed account and marks its limits; the original inquiry and
traffic registers were not examined. His message totals are not independently
recounted from original operator logs. Full cable specifications, legal privileges,
financing, weather, and tariffs have not been audited against underlying records.
Interpretations and participant assertions are visibly distinguished.

The banquet facsimile really says “Saturday, the 7th of September” on p.30.
September7, 1866, was Friday. The source conflict is retained; the narrative uses
“early September” for completion of the recovered cable, and does not silently
correct it. Henry Field's arrival report, the newspaper's Field telegram, and
Field's speech must not be counted as three independent witnesses to every claim.

The specialist Atlantic Cable site's pages for the 1866 Deane diary, the 1866
Bright technical account, and the 1857 Cyrus Field broadside returned HTTP403
when fetched during this research. Search snippets were not treated as retained
source evidence and no chapter depends on them. Alternative public scans and
transcriptions supplied the bounded narrative. The August8 issue of the
Newfoundland newspaper was also inspected during source selection but is not
cited or included; the August1 items were sufficient for the claims made here.

No long-term causal estimate of economic benefit, peace, price accessibility,
or reliability is offered. Ordinary workers' experiences, Newfoundland communities,
and material-supply histories are underrepresented in this source set. These are
limits of the chosen short book, not evidence that those histories did not matter.
No original-history or novel-discovery claim is made: Russell and both Fields
already narrated the undertaking. This edition contributes a bounded synthesis
with an inspectable, reproducible connection from prose to retained evidence.
