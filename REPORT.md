# N-ATLAS Form Assistant: prototype report (PDF forms → fields → filled PDF)

Date: 2026-10-27, updated 2026-10-28 with the missing part of the brief (section 0). Python 3.11.9 in `.venv`, CPU only.
Scope (supervisor, 27 Oct 2026): input is a **digital PDF**, either (A) fillable (AcroForm fields) or (B) flat, with a text layer or image-only (scanned). Voice and N-ATLaS are later stages. Photos are no longer a main input; the photo path (OpenCV cleaning, perspective, deskew) is kept as a working fallback and its tests still pass. Answers come from `answers.json` (field id **or key** → English text).

## 0. Update 2026-10-28: the missing part of the brief

You sent the cut-off part of the brief (items a–d) and your decisions. I compared it with every **[assumption]** below and changed only what differed. Each difference is one commit:

| # | Brief says | What I had | Change | Commit |
|---|---|---|---|---|
| 1 | Fillable labels: LayoutLM QUESTION left/above (same row first), **then tooltip, then nearest text** | question → *LayoutLM header* → tooltip → nearby text → **field name** | Order is now question → tooltip → nearest text (a LayoutLM header near the widget counts as nearest text, flagged). **The field name is never a label**: with nothing found, `label` is `null`, `label_source: 'none'`, `needs_review: true`. | `d142ab8` |
| 2 | Output `{'form': {source_file, pdf_kind, pages:[{page,width_px,height_px,dpi}]}, 'sections', 'fields'}` | `{file, kind: fillable\|flat\|image, dpi, pages, method, fields, sections, notes}` | New shape. `pdf_kind` is `fillable`, `flat_text`, `flat_scanned` or `mixed` (rule below). | `c28e89c` |
| 3 | Every field has `pdf_field_name` (null for flat) and `required` (null for flat) | name and required only inside the `pdf` block | Both added at field level. `required` is the PDF's own Required flag. | `c28e89c` |
| 4 | `fill_form(pdf_path, fields, answers, out_path)` | `fill_form(pdf_path, form, answers, out_path)`; needed the whole object | **Parameter renamed `form` → `fields`** (positional calls unchanged). It takes the fields list, the whole object, or a JSON path. With a bare list, page sizes come from a 200 DPI render. | `71b128a` |
| 5 | Read the **real** checkbox/radio on-state names **from the PDF** | on-states from the JSON; single checkbox fell back to `'Yes'` | Read from the PDF being filled (`pdf_fields.read_on_states`, /AP /N and /D). An option whose on-state is not in the PDF is skipped with a reason. No `'Yes'` guess. | `4af5c7e` |
| 6 | Validate each value against **type** and options first; refuse invalid values and list them | options, max_length, yes/no only; no type check | Fillable text fields typed number/date/email/phone are checked (`field_types.check_value`). Invalid values get status **`refused`** (nothing written) and are listed at the end of the CLI output. | `350d892` |
| 7 | Never overwrite the original; write `<name>_filled.pdf` | no guard; CLI default `form_filled.pdf` | Default output `<name>_filled.pdf` next to the input; `out_path` equal to the input (any spelling) raises `ValueError` before writing. | `855386c` |
| 8 | Verify by re-reading values (fillable) and by rendering | only in tests and by hand | `fill_form` now checks its own output. Each filled entry gets `verified: {value_read_back, ink_in_box}`. `value_read_back` is for fillable fields only. `ink_in_box` renders the original and the filled PDF and needs new ink inside the answer box (or the chosen option's box). Failures add a warning. | `831d133` |
| — | Flat PDFs: existing LayoutLM + answer-area path, fed with exact text-layer words | already so (`pdf_text` words with exact word boxes) | **No change.** The Business form still gives the same 34 fields and 7 sections. | — |
| — | Flat fill: overlay with pypdf, 200 DPI px → points, shrink font, mark in the chosen box | already so | **No change** (only the verification and output path above). | — |
| — | Types: text, number, date, yes_no, choice, email, phone, unknown | same list | **No change.** | — |

Your decisions:
- **`form.png`**: restored with `git checkout -- form.png`.
- **Flagged fields**: filled only if `answers.json` has an entry (that was already the case). Every filled `needs_review` field is now marked in the report (`needs_review: true`, `label`) and listed in the CLI summary. Commit `f852792`.
- **Readable key**: every field has `key`. Flat fields: `key = id` (flat ids were already made from the label). Fillable fields: key from the label (`marital_status`), with `_2`, `_3` added on a collision with another key or another field's id; a field with no label gets `field`, `field_2`, …. `answers.json` may use either; if both are given with different values, the field is skipped with a reason. Commit `f209628`.
- **Tag**: `photo-pipeline-v1` did not exist. Created (annotated) on `05f76b2` "Add REPORT.md", the commit before the first digital-PDF change (`2ceedf1`, pypdfium2 rendering).
- **Real fillable PDFs**: `samples/real/` does not exist, so **no real fillable PDF was tested**. This stays the main untested risk (section 13).

**`pdf_kind` rule** (my reading; see question 1 in section 6): each page is `fillable` (has widgets), `flat_text` (words from the text layer, with or without OCR of embedded images) or `flat_scanned` (OCR only). If all pages agree, that is the kind; otherwise `mixed`. Widget pages go through the AcroForm path, other pages through the flat path, and `fill_form` picks the method per field (`pdf_field_name` set → pypdf values; null → overlay). Tested on a generated 2-page PDF (fillable page + flat page).

Pipeline for each PDF page (`layout.analyse_form`):

1. Render the page at 200 DPI (pypdfium2). Every box in the output uses this pixel space.
2. Get words with boxes (`pdf_input.py`):
   - from the **text layer** (pdfplumber) when the page has real text, plus OCR of the page's embedded images only;
   - otherwise **PaddleOCR** on the whole page.
3. Run LayoutLM once over all pages.
4. Build fields, per page:
   - **Pages with widgets:** AcroForm widgets (pypdf), each linked to its label by LayoutLM (`pdf_fields.py`).
   - **Other pages:** LayoutLM labels plus drawn answer areas (`layout.py`, `answer_areas.py`).
5. Separate section headings into a `sections` list; add a readable `key` to every field.
6. Write one JSON object and `form_boxes.png`. `fill_form.py` then writes the answers into `<name>_filled.pdf` and verifies it.

Git history (one commit per step; undo any of them with `git revert <hash>`):
```
bd45d33 Samples for the new fill: reports, a fill by key with one invalid value, run and test logs
f852792 fill_form: mark and list every filled needs_review field in the fill summary
831d133 fill_form: verify the written PDF (read values back; new ink inside each answer box on a render)
855386c fill_form: write <name>_filled.pdf by default; refuse to overwrite the original
71b128a fill_form(pdf_path, fields, answers, out_path): accept the fields list as well as the form object
350d892 fill_form: validate fillable answers against type and options; refuse and list invalid values
4af5c7e fill_form: read checkbox/radio on-state names from the PDF being filled
f209628 Readable key from the label next to each id; answers.json may use id or key
c28e89c Output format from the brief: form{source_file, pdf_kind, pages}, pdf_field_name, required; per-page kind with a mixed path
d142ab8 Fillable labels: LayoutLM question, then tooltip, then nearest text; never the field name
--- 2026-10-28 above (section 0); 2026-10-27 below ---
4bb309c PDF tests on generated forms; fixes they found                      (step 6)
c3ed007 fill_form: fill fillable and flat PDFs from answers.json            (step 5)
ad39008 Flat/fillable pipeline in one JSON object; section headings as a list (step 4)
3de6666 Fillable PDFs: read AcroForm fields and link them to printed labels (step 3)
640d2e1 layout_lm: force Hugging Face offline mode when loading the model   (bug fix)
9b87528 PDF word extraction: text layer per page, OCR only where needed     (step 2)
2ceedf1 ocr.render_pdf: render PDF pages with pypdfium2 instead of PyMuPDF  (step 2)
05f76b2 Add REPORT.md                                                       (previous report; tag photo-pipeline-v1)
```

> **The brief I received was cut off** in section 2, item 2. You have since sent the missing part (items a–d); section 0 lists what changed. Items still marked **[assumption]** below are the ones the missing part does not cover.

---

## 1. What works (command → real output)

Every result below came from running the command shown. Logs:
- `samples/run_log_brief.txt`: pipeline and fill runs on 2026-10-28, after the section 0 changes;
- `samples/run_log_pdf.txt`: the runs of 2026-10-27 (old output format);
- `samples/test_log_pdf.txt`: full test run (2026-10-28, 30 tests).

**Text layer instead of OCR, in the same pixel space.** On `Business-Name-Form.pdf`:
- 54 lines have the same text in both sources. Their text-layer boxes agree with the earlier PaddleOCR boxes within a median of 5 px and a maximum of 9 px (about 1 mm at 200 DPI). That difference is OCR padding, not an offset.
- OCR of embedded images recovered 8 lines that are pictures, not text. Four are real labels ("Proposed Business Name", "General Nature of business", "Signature", "Address of Principal Place of Business"); three are headings; one is the "CAC" logo.
```
68 items in 64.2s
kind flat [(1, 'pdf_text+ocr_images', 1655, 2339, 595.56, 842.04), (2, 'pdf_text+ocr_images', 1655, 2339, 595.56, 842.04)]
identical-text lines matched: 54/67; max corner diff px: median 5, 90%: 7, max 9
```

**Rotation and crop box:** rotated (90/180/270) and unevenly cropped copies give every word at the expected box:
```
rotate  90 crop False: render 2339x1655, matched 99/99 words, max box error 0.0 px
rotate 180 crop False: render 1655x2339, matched 99/99 words, max box error 0.0 px
rotate 270 crop False: render 2339x1655, matched 99/99 words, max box error 0.0 px
rotate   0 crop True : render 1460x2089, matched 99/99 words, max box error 0.7 px
rotate  90 crop True : render 2089x1460, matched 99/99 words, max box error 0.7 px
rotate 270 crop True : render 2089x1460, matched 99/99 words, max box error 0.9 px
```

**Full pipeline** (`layout.py <pdf>`):

| PDF | `pdf_kind` / word source | Fields found | Real fields | Real found | Extras | Sections |
|---|---|---|---|---|---|---|
| `Business-Name-Form.pdf` (real, 2 pages) | `flat_text` / `pdf_text+ocr_images` | 34 | 34 | 33 (missed "Recent Passport Photograph") | 1 ("Attestation", flagged) | 7 (all real headings) |
| `samples/test_fillable.pdf` (generated, seed 1) | `fillable` / `pdf_text` | 9 | 9 | 9, all labels from LayoutLM | 0 | 4/4 |
| `samples/test_flat.pdf` (same layout, no widgets) | `flat_text` / `pdf_text` | 9 | 9 | 9 | 0 | 4/4 |
| `samples/test_image.pdf` (image-only copy) | `flat_scanned` / `ocr` | 9 | 9 | 9 | 0 | 4/4 |

These counts are the same as on 2026-10-27; the section 0 changes did not change which fields are found on these PDFs. The previous report, on the same real PDF, had 40 fields (33 real; 6 headings and "Attestation" as extras) and missed the bottom "Date". The headings are now in `sections`, and "Date" is found.

```
> .venv\Scripts\python.exe layout.py samples\test_fillable.pdf --ocr-json samples\test_fillable_words.json --fields samples\test_fillable_fields.json --boxes samples\test_fillable_boxes.png
pdf_kind=fillable method=acroform+layoutlm pages: p1=fillable/pdf_text
p1 SECTION 'Other information' [layoutlm_header]
p1 date_of_visit                'Date of visit'                               date     acroform/layoutlm_left
p1 home_address                 'Home address'                                text     acroform/layoutlm_above
p1 marital_status               'Marital status'                              choice   acroform/layoutlm_left
...
9 fields, 4 sections.
```
One field of `samples/test_fillable_fields.json` (every key of your spec is present on every field; checked with a script):
```
top: ['form', 'sections', 'fields']
form: {'source_file': 'samples\\test_fillable.pdf', 'pdf_kind': 'fillable', 'method': 'acroform+layoutlm', 'notes': []}
page1: {'page': 1, 'dpi': 200, 'width_px': 1700, 'height_px': 2200, 'width_pt': 612.0, 'height_pt': 792.0, 'rotation': 0, 'widgets': 13, 'word_source': 'pdf_text', 'kind': 'fillable'}
{'id': 'f5_txt48', 'label': 'Marital status', 'label_box': [156, 941, 347, 971], 'answer_box': [425, 939, 870, 970], 'type': 'choice', 'page': 1, 'pdf_field_name': 'f5_txt48', 'required': False, 'options': ['Single', 'Married', 'Other'], 'source': 'acroform', 'confidence': 0.998, 'needs_review': False, 'answer_method': 'acroform_widget'}
missing: []
extra: ['key', 'label_source', 'pdf', 'section', 'type_source']
```

**Filling:** see section 12.

**Tests** (generated forms only; 4 seeds, 3 page sizes, labels left of or above inputs). 12 new tests for section 0; the photo-path tests (`tests/test_pipeline.py`) are unchanged and pass:
```
> set RUN_SLOW=1 && .venv\Scripts\python.exe -m unittest discover -s tests -v
new: test_field_name_is_never_a_label, test_pdf_kind, test_mixed_pdf_uses_both_paths,
     test_keys_from_labels, test_answers_by_key_or_id, test_on_states_come_from_the_pdf,
     test_check_value, test_invalid_values_are_refused, test_fields_list_or_form_object,
     test_never_overwrites_the_original, test_verification_catches_missing_ink,
     test_filled_flagged_fields_are_listed ... ok
older PDF tests (now also assert verified == all True on every fill) ... ok
photo-path tests: test_generated_forms, test_ocr_and_layoutlm_on_synthetic, ... ok
Ran 30 tests in 184.084s
OK
```
Fast tests only (no `RUN_SLOW`): `Ran 30 tests in 11.195s, OK (skipped=3)`.

**What I saw when I opened the images myself:**
- **`samples/test_fillable_boxes.png`:**
  - every blue box sits exactly on its widget, over the drawn box or line;
  - each radio option has its own blue box on its checkbox square;
  - "Home address" gets the box below it;
  - red label boxes fit the text tightly, and the 4 headings are green.
- **`samples/pdf_boxes.png` (real form):**
  - all 7 green boxes are real headings;
  - every table label's blue box is its empty answer cell, and the right column stops at the photo area;
  - "City/Town/Village" avoids the "You must ensure…" note;
  - the bottom "Date" gets its cell; "Signature" gets its signature cell (flagged);
  - "General Nature of Business" gets only the first of its 4 ruled lines;
  - "Attestation" is a flagged false field with a thin box after it.
- **`samples/test_image_boxes.png` (scanned copy):** the same as the text-layer version: 9 correct labels and areas, 4 headings.

## 2. What does not work

Nothing crashes. These are wrong results:

| Problem | Where | Detail |
|---|---|---|
| "Recent Passport Photograph" not found | `layout.py` / LayoutLM | It was a flagged field before. With exact text-layer word boxes, the model no longer tags it as a question. It's a photo area, so it couldn't be filled with text anyway. |
| "Attestation" reported as a field | `layout.py` | Flagged `needs_review`. Its answer area is a guess (`empty_right`). |
| Multi-line answer areas get only the first line | `answer_areas.py` | Unchanged: "General Nature of Business" gets 1 of its 4 lines, so long answers are squeezed into one line. |
| On image-only pages, headings can become fields | `layout.py` | Seen in 1 of 4 generated scanned pages: "Personal details" and "Other information" were tagged as questions. Both are flagged `needs_review`. The rule "larger text → heading" doesn't work on OCR text, because OCR box heights vary by about ±15%. |
| PaddleOCR misses short words next to checkboxes | `ocr.py` (model) | On a scanned page it read "□No" and dropped "Yes". The □ is now stripped. The missing option means that field's options are incomplete. |
| Sideways or upside-down text | `pdf_input.py` | Words come out with the right boxes but run vertically or with reversed letters ('emanruS'). Pages whose content is only rotated with `/Rotate` and reads upright on screen are fine (tested). |

## 3. Bugs found and fixed

| File | What | Why |
|---|---|---|
| `layout_lm.py` | Added `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` | **The previous report said model loading was strictly local; that was wrong.** A debug log showed `GET https://huggingface.co/api/models/philschmid/layoutlm-funsd` at load time even with `local_files_only=True`. With offline mode the log shows no Hub requests and no TCP connects. |
| `pdf_input.py` | Crop-box offset taken from pypdf's raw boxes | pdfplumber reports words relative to the media box, but pdfium renders only the crop box. A cropped copy was off by 120 px; it's now under 1 px. |
| `pdf_fields.py` | A same-row label beats text above the input | A heading just above a box was picked as the label ("Date of visit" → "Personal details"). Found by a test. |
| `pdf_fields.py` | A model-tagged header next to a widget is used as its label (flagged) | The model tagged "Do you smoke?" as a header, so the field fell back to its tooltip. Found by a slow test. |
| `layout.py` | A question piece inside a heading's line is dropped; heading titles use the whole line | "Other information" became a section "information" plus a field "Other". |
| `answer_areas.py` | New step: underline or box just **below** a label (not inside table cells) | "Home address" (label above its line) got a guessed `empty_right` area. |
| `layout_rules.clean_items` | Keeps `source` and `words`; strips checkbox glyphs (□☐■…) | It used to drop every key except text/box/score/page. OCR glued "□" onto options. |
| `layout_rules.draw_boxes` | Works with `label_box: None`; draws every widget; draws sections in green | Fillable fields labelled from a tooltip have no label box. |
| `ocr.render_pdf` | pypdfium2 instead of PyMuPDF | Your decision 3. Same name and signature, same output size (1655×2339); mean pixel difference under 3/255. |
| `ocr.read_form` | Same signature; PDFs go through `pdf_input`; new `ocr_image()` | So the text layer can be used instead of OCR. |
| `layout_lm.split_into_words` | Uses exact word boxes when an item has them | Old bug #3 (boxes estimated from character counts) is fixed for text-layer pages. |
| `ocr_test.py`, `tests/test_pipeline.py` | Expect `source` in Shape 1 (and optional `words`) | Required by the new Shape 1. |

## 4. Bugs found and NOT fixed

1. Multi-line answer areas (old #4) are still one line.
2. A single checkbox with its label to the **right** ("☐ I agree") on a **flat** PDF is still treated as an option, not a field (old #5). On fillable PDFs this works: single checkboxes look for their label on the right too.
3. On image-only pages, word boxes are still estimated from character counts (old #3). PaddleOCR's `return_word_box=True` would fix this; not tried.
4. On the generated image-only page, OCR missed the option "Yes" next to its checkbox (see section 2).
5. In the flat path, option boxes are matched by option text, so two identical option texts in one row ("Yes … Yes") would share one box. Not seen on any test form.

## 5. Things I am not sure about

- **Output format: now your spec** (section 0). Settled. **Extra keys I kept** (not in your spec; tell me if you want them removed):
  - in `form`: `method`, `notes`;
  - in each page: `width_pt`, `height_pt`, `rotation`, `widgets`, `word_source`, `kind`;
  - in each field: `key`, `section`, `label_source`; flat fields also have `option_boxes`; fillable fields also have `type_source` and the `pdf` block (name, field_type, flags, read_only, tooltip, max_length, default_value, value, option_values, format_script, widgets).
- **Where LayoutLM is used: now as in your brief** (labels for fillable widgets; the flat path). It is also still used to decide what is a section, which the brief does not mention.
- **[assumption, still open] How checkboxes are typed.** The missing part only lists the allowed types. A single checkbox → `yes_no`. Radio groups and same-name checkbox groups → `choice`, or `yes_no` when the options are Yes/No. Combo and list boxes → `choice`.
- **Text fields on fillable PDFs default to `text`.** Number, date or phone only when the PDF's format action (AFNumber_/AFDate_/AFSpecial_) or the label or tooltip words say so. So "Next of kin" is `text` on the fillable form but `unknown` on the flat one.
- **Field id = full AcroForm name** on fillable PDFs (your "my call"); the readable `key` sits next to it (your decision).
- **Type validation only on fillable PDFs.** Item d asks for it under "Fillable". Flat-PDF types are guesses from label words, so refusing values there could block correct answers; flat answers are not type-checked. Date validation accepts both day-first and month-first, plus ISO and written months; it does not check against the field's own AFDate format string.
- **`pdf_kind` of a photo** (fallback path): `flat_scanned`, since a photo is a scanned flat page.
- **"Real text" rule** (your "my call"): a page uses its text layer if it has at least 3 real words and at most 20% garbage (`(cid:NN)`, U+FFFD). On those pages, embedded images are OCR'd too and their text is added with `source: 'ocr'`. This goes against my own plan ("no mixing within a page"), because on your real form 4 labels exist only as images. The page records `word_source: 'pdf_text+ocr_images'`.
- **No real fillable PDF was tested.** All fillable results come from PDFs I generated, which you agreed to. Real forms made in Acrobat, Word or LibreOffice use features my generator doesn't (calculated fields, hierarchical names, XFA, appearance streams without `/NeedAppearances`).

## 6. Information I need from you

Answered on 2026-10-28 (brief, `form.png`, readable key, flagged fields; see section 0). New questions:

1. **What does `mixed` mean to you?** My rule: pages differ in kind. So a fillable PDF with one page of printed instructions and no widgets becomes `mixed`, and that page goes through the flat path. That path may report a flagged false field there. If you meant only "fillable + flat pages", or wanted instruction pages ignored, tell me.
2. **Should flat-PDF answers be type-checked too** (section 5)? Right now only fillable answers are refused for a wrong type.
3. **Checkbox typing** (section 5) is still my assumption.
4. **Extra keys** in the output (section 5): keep or remove?
5. `samples/my_form.png` is untracked in your working copy. I didn't add or touch it.

## 7. Generalisation risks (PDFs that will probably struggle)

- **Real fillable PDFs with unusual structure:** XFA-only forms (no AcroForm widgets, so they'd be treated as flat); fields hidden until a checkbox is ticked; calculated or read-only fields; one field shown on several pages (handled: widgets are grouped by name, and the label is searched on the first visible widget's page).
- **Fillable PDFs with no printed label near a widget:** these fall back to tooltip, then nearby text, all flagged `needs_review`; with neither, `label` is `null` (never the field name).
- **A page with widgets that also has printed-only blanks:** only the widgets become fields on that page (the flat path runs only on pages without widgets).
- **Scanned PDFs:** image-only pages depend fully on PaddleOCR, with the risks in section 2. Skewed scans are not straightened, because the photo-cleaning code is not applied to PDFs.
- **Text layers that exist but lie:** e.g. a scanned page with a bad invisible OCR layer underneath. The page passes the "real text" rule, and its wrong text is used as-is.
- **Very dense or multi-column flat forms without ruling lines:** the answer area falls back to empty space (`empty_right` / `empty_below`), which is often wrong (always flagged).
- **Non-Latin answers on flat PDFs:** the built-in Helvetica can't draw characters outside Windows-1252. Those answers are skipped with a reason. English answers are fine.

## 8. Hardcoded / sample-specific items

**Nothing sample-specific in the pipeline.** No field names, labels, coordinates or results are in the logic.
- Filenames are CLI arguments.
- The defaults are generic output names only: `form_fields.json`, `form_boxes.png`, `answers.json`, and `<input name>_filled.pdf`.

**Generic values left on purpose (config blocks at the top of each file):**
- `pdf_input.py`: `MIN_TEXT_WORDS=3`, `MAX_BAD_WORD_SHARE=0.2`, `PHRASE_GAP=0.8`, image-OCR limits.
- `pdf_fields.py`: `LEFT_MAX=15`, `ABOVE_MAX=2.5`, `RIGHT_MAX=3` (in text heights), and the PDF-standard flag bits.
- `layout.py`: `SECTION_ROW_SHARE=0.6`, `SECTION_TEXT_SCALE=1.15`.
- `fill_form.py`: font limits 6–11 pt, the yes/no words used to tick checkboxes, `MIN_NEW_INK_PX=5` (verification).
- `field_types.py`: the number/email/phone patterns, 7–15 phone digits (E.164 maximum), and the accepted date formats.

**Test data on purpose:**
- `make_test_pdfs.py` reuses the label pool of `make_synthetic_form.py` (e.g. "Marital status") and fixed section names.
- The `samples/*_answers.json` files were made from each form's output, with one example value per field **type**. That's why the Business form shows "Surname = 12 Marina Road, Lagos": the answers are placeholders.

## 9. How to run everything (Windows, from the project folder)

```bat
REM 0. One-time setup (already done on this machine)
.venv\Scripts\pip.exe install pypdf pdfplumber
.venv\Scripts\python.exe -c "import layout_lm; layout_lm.download_models()"

REM 1. Understand a PDF form -> one JSON object + boxes image (red label, blue answer area, green section)
.venv\Scripts\python.exe layout.py Business-Name-Form.pdf --fields samples\pdf_fields.json --boxes samples\pdf_boxes.png --ocr-out samples\pdf_words.json
REM    reuse saved words (faster):  --ocr-json samples\pdf_words.json
REM    no LayoutLM:                 --method rules

REM 2. Fill it from answers.json (field id or key -> English text); prints a status per field,
REM    the refused values, the filled needs_review fields and the verification result.
REM    Without --out it writes Business-Name-Form_filled.pdf next to the input (never the input itself).
.venv\Scripts\python.exe fill_form.py Business-Name-Form.pdf --form samples\pdf_fields.json --answers samples\pdf_answers.json --out samples\pdf_filled.pdf --report samples\pdf_fill_report.json

REM 3. Make test PDFs with ground truth
.venv\Scripts\python.exe make_test_pdfs.py fillable --out samples\test_fillable.pdf --seed 1 --count 9
.venv\Scripts\python.exe make_test_pdfs.py flat --out samples\test_flat.pdf --seed 1 --count 9
.venv\Scripts\python.exe make_test_pdfs.py image --src samples\test_flat.pdf --out samples\test_image.pdf

REM 4. Tests (fast: about 10 s; slow adds PaddleOCR + LayoutLM: about 160 s)
.venv\Scripts\python.exe -m unittest discover -s tests -v
set RUN_SLOW=1
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
In Python:
```python
from layout import analyse_form
from fill_form import fill_form
form = analyse_form(path)                                # {'form': ..., 'sections': ..., 'fields': ...}
report = fill_form(path, form['fields'], answers, None)  # None -> <name>_filled.pdf
```
`layout.explain_fields_in_language` is still a stub for the later N-ATLaS stage.

## 10. Licence notes

You said licensing is not a concern for now. Kept for reference:

| Component | Licence | Source |
|---|---|---|
| pypdf 6.21.3 | BSD-3-Clause | package metadata (`License-Expression`) |
| pdfplumber 0.11.10 | MIT | package classifier |
| pdfminer.six 20260107 | MIT | package metadata |
| pypdfium2 5.14.0 | BSD-3-Clause / Apache-2.0 | `pip show` |
| PyMuPDF 2.0 | AGPL-3.0 | still installed, **no longer imported by the pipeline** |
| `philschmid/layoutlm-funsd` | **not stated**; fine-tuned on FUNSD (research use) | unchanged from the previous report |
| PaddleOCR 3.7.0, transformers 5.21.0, OpenCV 4.10 | Apache-2.0 | unchanged |

## 11. What works per PDF kind

| Kind | Words | Fields | Labels | Types | Sections | Fill |
|---|---|---|---|---|---|---|
| **(A) Fillable** (`fillable`) | text layer (+ image OCR) | every AcroForm widget (text, checkbox, radio group, combo/list, signature); push buttons skipped | LayoutLM question next to the widget (left/above, same row first; right for single checkboxes), then tooltip, then nearest text (LayoutLM header first) — fallbacks flagged; never the field name | from the PDF's own field type, format action and options; label/tooltip words only for number/date/email/phone | LayoutLM headers that aren't labels | pypdf sets values after type/option validation; on-states read from the PDF; NeedAppearances; values read back + render check; tested on generated forms only |
| **Mixed** (`mixed`) | per page | widget pages as (A), other pages as (B) | per page | per page | per page | per field: pypdf for widgets, overlay for the rest (tested on a generated 2-page PDF) |
| **(B1) Flat with text layer** (`flat_text`) | text layer (+ image OCR) | LayoutLM questions + drawn answer areas (cells, underlines, boxes, checkboxes, lines below the label) | LayoutLM, rules fallback | label words + options + checkbox count | LayoutLM headers; labels with no area or alone in a full-width row; larger text with only a guessed area | text drawn in the answer box; X in the chosen checkbox |
| **(B2) Flat, image-only** (`flat_scanned`) | PaddleOCR on the 200 DPI render | same as B1 | same as B1 | same as B1 | same as B1; the larger-text rule is unreliable on OCR boxes | same as B1 |

## 12. Fill results

Re-run on 2026-10-28 (`samples/run_log_brief.txt`). "Verified" is `fill_form`'s own check of the written file (section 0, item 8).

| PDF | Answers | Filled | Refused | Skipped | Verified | Also checked by eye |
|---|---|---|---|---|---|---|
| `test_fillable.pdf` | 9 (by id) | 9 | 0 | 0 | 9/9 | (2026-10-27) only the chosen radio kid is on (`/opt1` = Married, `/SMS`) |
| `test_fillable.pdf` | 9 (by **key**, email deliberately invalid: `ada.obi at example`) | 8 | 1 (`'ada.obi at example' is not an email address (email field)`) | 0 | 8/8 | render: every value in its field, email field empty, only "Married" and "SMS" ticked |
| `test_flat.pdf` | 9 | 9 | 0 | 0 | 9/9 | (2026-10-27) text on its underline or in its box, X in "Married" and "SMS" only |
| `test_image.pdf` | 9 | 9 | 0 | 0 | 9/9 | (2026-10-27) same as flat |
| `Business-Name-Form.pdf` | 34 | 34 | 0 | 0 | 34/34 | (2026-10-27) every answer inside its own cell |

On the Business form, the summary now lists the two flagged fields that got text:
```
Filled fields marked needs_review (check these on the PDF): 2
  'attestation' ('Attestation'): Example answer
  'signature' ('Signature'): Example answer
Verified on the written file: 34/34 ok
```

The tests also check:
- **Refused, with a reason:** answers longer than `max_length`; answers matching no option; wrong type (number/date/email/phone).
- **Skipped, with a reason:** unknown ids or keys; different answers for id and key; an option whose on-state is not in the PDF.
- Read-only and signature fields are skipped too.

Observed limits:
- On underlines, answer text is smaller than the form's own text: the answer area is one text line tall and the font is 75% of it.
- Single-line answers sit low in tall cells (deliberate, so they land on underlines).
- Typed text is written into signature cells if `answers.json` has an entry for them.

## 13. Remaining risks

1. **No real fillable PDF tested — the main untested risk.** `samples/real/` does not exist (checked 2026-10-28), and the only real PDF in the project (`Business-Name-Form.pdf`) is flat. Every fillable and mixed result comes from PDFs I generated. Real forms from Acrobat, Word or LibreOffice use features my generator doesn't: calculated fields, hierarchical names, XFA, kids with their own appearance states, `/D`-only states. Please put some real fillable PDFs in `samples/real/`.
2. **Still assumptions:** checkbox typing, my reading of `mixed`, and no type check on flat answers (section 6).
3. **Scanned PDFs** inherit OCR mistakes (missed options, headings tagged as questions). These are flagged, not fixed.
4. **Flagged fields are filled** if they have an answer (your decision). They are now listed in the fill summary.
5. **Verification is coarse.** `ink_in_box` proves that new ink landed inside the box, not that it is the right text. For flat fills, the tests also re-read the drawn text with pdfplumber.
6. **The LayoutLM checkpoint licence is unknown** (research-only until confirmed). Only relevant if the project becomes a product.
7. **Speed:** reading the words of the 2-page `Business-Name-Form.pdf` took 64.2 s on this CPU, most of it loading PaddleOCR for the embedded images. Pages without images need no OCR. I didn't time those separately; the whole slow test suite (8 forms through the full pipeline, plus the fast tests) took 157 s.
