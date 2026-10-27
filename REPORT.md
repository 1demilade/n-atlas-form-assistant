# N-ATLAS Form Assistant: prototype report (PDF forms → fields → filled PDF)

Date: 2026-10-27. Python 3.11.9 in `.venv`, CPU only.
Scope (supervisor, 27 Oct 2026): input is a **digital PDF**, either (A) fillable (AcroForm fields) or (B) flat, with a text layer or image-only (scanned). Photos, voice and N-ATLaS are out of scope for now. Answers come from `answers.json` (field id → English text).

Pipeline for each PDF page (`layout.analyse_form`):

1. Render the page at 200 DPI (pypdfium2). Every box in the output uses this pixel space.
2. Get words with boxes (`pdf_input.py`):
   - from the **text layer** (pdfplumber) when the page has real text, plus OCR of the page's embedded images only;
   - otherwise **PaddleOCR** on the whole page.
3. Run LayoutLM once over all pages.
4. Build fields:
   - **Fillable PDFs:** AcroForm widgets (pypdf), each linked to its label by LayoutLM (`pdf_fields.py`).
   - **Flat PDFs:** LayoutLM labels plus drawn answer areas (`layout.py`, `answer_areas.py`).
5. Separate section headings into a `sections` list.
6. Write one JSON object and `form_boxes.png`. `fill_form.py` then writes the answers into a copy of the PDF.

Git history (one commit per step; undo any of them with `git revert <hash>`):
```
4bb309c PDF tests on generated forms; fixes they found                      (step 6)
c3ed007 fill_form: fill fillable and flat PDFs from answers.json            (step 5)
ad39008 Flat/fillable pipeline in one JSON object; section headings as a list (step 4)
3de6666 Fillable PDFs: read AcroForm fields and link them to printed labels (step 3)
640d2e1 layout_lm: force Hugging Face offline mode when loading the model   (bug fix)
9b87528 PDF word extraction: text layer per page, OCR only where needed     (step 2)
2ceedf1 ocr.render_pdf: render PDF pages with pypdfium2 instead of PyMuPDF  (step 2)
05f76b2 Add REPORT.md                                                       (previous report)
```

> **The brief I received was cut off** in section 2, item 2 ("checkbox -> yes_no or single…"). I never saw the rest of item 2 or items 3–5, which cover where LayoutLM must be used and the exact output format. Wherever those items matter below, I followed my own plan and marked it **[assumption]**.

---

## 1. What works (command → real output)

Every result below came from running the command shown. Logs:
- `samples/run_log_pdf.txt`: pipeline and fill runs;
- `samples/test_log_pdf.txt`: full test run.

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

| PDF | Kind / word source | Fields found | Real fields | Real found | Extras | Sections |
|---|---|---|---|---|---|---|
| `Business-Name-Form.pdf` (real, 2 pages) | flat / `pdf_text+ocr_images` | 34 | 34 | 33 (missed "Recent Passport Photograph") | 1 ("Attestation", flagged) | 7 (all real headings) |
| `samples/test_fillable.pdf` (generated, seed 1) | fillable / `pdf_text` | 9 | 9 | 9, all labels from LayoutLM | 0 | 4/4 |
| `samples/test_flat.pdf` (same layout, no widgets) | flat / `pdf_text` | 9 | 9 | 9 | 0 | 4/4 |
| `samples/test_image.pdf` (image-only copy) | flat / `ocr` | 9 | 9 | 9 | 0 | 4/4 |

The previous report, on the same real PDF, had 40 fields (33 real; 6 headings and "Attestation" as extras) and missed the bottom "Date". The headings are now in `sections`, and "Date" is found.

```
> .venv\Scripts\python.exe layout.py samples/test_fillable.pdf ...
kind=fillable method=acroform+layoutlm words: p1=pdf_text
p1 SECTION 'Other information' [layoutlm_header]
p1 'Date of visit'        date     acroform/layoutlm_left
p1 'Home address'         text     acroform/layoutlm_above
p1 'Marital status'       choice   acroform/layoutlm_left
...
9 fields, 4 sections.
```

**Filling:** see section 12.

**Tests** (generated forms only; 4 seeds, 3 page sizes, labels left of or above inputs):
```
> set RUN_SLOW=1 && .venv\Scripts\python.exe -m unittest discover -s tests -v
test_fields_match_ground_truth ... ok            test_boxes_follow_rotation_and_crop ... ok
test_labels_and_types_without_layoutlm ... ok    test_kind_detection ... ok
test_fillable_round_trip ... ok                  test_real_text_rule ... ok
test_fillable_skips_with_reasons ... ok          test_words_land_on_ink ... ok
test_flat_text_and_crosses_land_in_place ... ok  (+ the 7 older tests) ... ok
test_generated_pdfs ... ok                       test_image_only_pdf ... ok
Ran 18 tests in 156.547s
OK
```

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

- **[assumption] Output format.** Item 5 of your brief (the output format) was cut off. I used one JSON object:
  `{file, kind: fillable|flat|image, dpi, pages: [{page, dpi, width_px, height_px, width_pt, height_pt, rotation, widgets, word_source}], method, fields: [...], sections: [...], notes: [...]}`.
  - Every field has the old keys (`id, label, label_box, answer_box, type, source, confidence, needs_review, page, answer_method, options`) plus `section`.
  - Flat fields add `option_boxes`.
  - Fillable fields add `label_source`, `type_source` and a `pdf` block with: name, field_type, flags, required, read_only, tooltip, max_length, default_value, value, option_values, format_script, widgets.
  - `pdf.required` is read from the PDF's own flag, never guessed.
- **[assumption] Where LayoutLM is used** (items 3 and 4 were cut off). It's used for label linking on fillable PDFs, for labels on flat PDFs, and to decide what is a section.
- **[assumption] How checkboxes are typed** (item 2 was cut off mid-sentence). A single checkbox → `yes_no`. Radio groups and same-name checkbox groups → `choice`, or `yes_no` when the options are Yes/No. Combo and list boxes → `choice`.
- **Text fields on fillable PDFs default to `text`.** Number, date or phone only when the PDF's format action (AFNumber_/AFDate_/AFSpecial_) or the label or tooltip words say so. So "Next of kin" is `text` on the fillable form but `unknown` on the flat one.
- **Field id = full AcroForm name** on fillable PDFs (your "my call"). It's stable and needed for filling, but not human-friendly (e.g. `f5_txt48`). Flat PDFs keep the ids made from the label (`date_of_visit`, `address_2`).
- **"Real text" rule** (your "my call"): a page uses its text layer if it has at least 3 real words and at most 20% garbage (`(cid:NN)`, U+FFFD). On those pages, embedded images are OCR'd too and their text is added with `source: 'ocr'`. This goes against my own plan ("no mixing within a page"), because on your real form 4 labels exist only as images. The page records `word_source: 'pdf_text+ocr_images'`.
- **No real fillable PDF was tested.** All fillable results come from PDFs I generated, which you agreed to. Real forms made in Acrobat, Word or LibreOffice use features my generator doesn't (calculated fields, hierarchical names, XFA, appearance streams without `/NeedAppearances`).

## 6. Information I need from you

1. **The rest of the brief** (section 2, items 2–5 and anything after). Several choices above are assumptions until then.
2. **`form.png` is deleted in your working copy, but the deletion isn't committed.** I didn't touch it. Should I restore it (`git restore form.png`) or commit the deletion? It's photo-era material, so it's no longer needed for the PDF scope.
3. Should fillable-PDF field ids stay as the raw AcroForm names, or should I add a readable `key` (from the label) alongside? `answers.json` would still use `id`.
4. When a flagged false field such as "Attestation" is in `answers.json`, filling writes text there. Should `fill_form` skip fields with `needs_review: true` unless told otherwise?

## 7. Generalisation risks (PDFs that will probably struggle)

- **Real fillable PDFs with unusual structure:** XFA-only forms (no AcroForm widgets, so they'd be treated as flat); fields hidden until a checkbox is ticked; calculated or read-only fields; one field shown on several pages (handled: widgets are grouped by name, and the label is searched on the first visible widget's page).
- **Fillable PDFs with no printed label near a widget:** these fall back to tooltip, then nearby text, then the field name, all flagged `needs_review`.
- **Scanned PDFs:** image-only pages depend fully on PaddleOCR, with the risks in section 2. Skewed scans are not straightened, because the photo-cleaning code is not applied to PDFs.
- **Text layers that exist but lie:** e.g. a scanned page with a bad invisible OCR layer underneath. The page passes the "real text" rule, and its wrong text is used as-is.
- **Very dense or multi-column flat forms without ruling lines:** the answer area falls back to empty space (`empty_right` / `empty_below`), which is often wrong (always flagged).
- **Non-Latin answers on flat PDFs:** the built-in Helvetica can't draw characters outside Windows-1252. Those answers are skipped with a reason. English answers are fine.

## 8. Hardcoded / sample-specific items

**Nothing sample-specific in the pipeline.** No field names, labels, coordinates or results are in the logic.
- Filenames are CLI arguments.
- The defaults are generic output names only: `form_fields.json`, `form_boxes.png`, `answers.json`, `form_filled.pdf`.

**Generic values left on purpose (config blocks at the top of each file):**
- `pdf_input.py`: `MIN_TEXT_WORDS=3`, `MAX_BAD_WORD_SHARE=0.2`, `PHRASE_GAP=0.8`, image-OCR limits.
- `pdf_fields.py`: `LEFT_MAX=15`, `ABOVE_MAX=2.5`, `RIGHT_MAX=3` (in text heights), and the PDF-standard flag bits.
- `layout.py`: `SECTION_ROW_SHARE=0.6`, `SECTION_TEXT_SCALE=1.15`.
- `fill_form.py`: font limits 6–11 pt, and the yes/no words used to tick checkboxes.

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

REM 2. Fill it from answers.json (field id -> English text); prints a status per field
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
form = analyse_form(path)
report = fill_form(path, form, answers, out_path)
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
| **(A) Fillable** | text layer (+ image OCR) | every AcroForm widget (text, checkbox, radio group, combo/list, signature); push buttons skipped | LayoutLM question next to the widget (left/above; right for single checkboxes), then a LayoutLM header (flagged), then tooltip, nearby text, field name (all flagged) | from the PDF's own field type, format action and options; label/tooltip words only for number/date/email/phone | LayoutLM headers that aren't labels | pypdf sets values; tested on generated forms only |
| **(B1) Flat with text layer** | text layer (+ image OCR) | LayoutLM questions + drawn answer areas (cells, underlines, boxes, checkboxes, lines below the label) | LayoutLM, rules fallback | label words + options + checkbox count | LayoutLM headers; labels with no area or alone in a full-width row; larger text with only a guessed area | text drawn in the answer box; X in the chosen checkbox |
| **(B2) Flat, image-only** | PaddleOCR on the 200 DPI render | same as B1 | same as B1 | same as B1 | same as B1; the larger-text rule is unreliable on OCR boxes | same as B1 |

## 12. Fill results

| PDF | Answers | Filled | Skipped | Checked by |
|---|---|---|---|---|
| `test_fillable.pdf` | 9 | 9 | 0 | values read back from the file (`get_fields`); only the chosen radio kid is on (`/opt1` = Married, `/SMS`); render shows every value in its own field |
| `test_flat.pdf` | 9 | 9 | 0 | render: text on its underline or in its box, X in "Married" and "SMS" only |
| `test_image.pdf` | 9 | 9 | 0 | render: same as flat |
| `Business-Name-Form.pdf` | 34 | 34 | 0 | render: every answer inside its own cell, right column stops at the photo area; "Attestation" got text too (it's a flagged false field) |

The tests also check skips: answers longer than `max_length`, answers matching no option, and unknown ids are skipped with a reason; read-only and signature fields are skipped too.

Observed limits:
- On underlines, answer text is smaller than the form's own text: the answer area is one text line tall and the font is 75% of it.
- Single-line answers sit low in tall cells (deliberate, so they land on underlines).
- Typed text is written into signature cells if `answers.json` has an entry for them.

## 13. Remaining risks

1. **No real fillable PDF tested** (section 5). This is the biggest gap for kind (A).
2. **The brief is incomplete** (section 6, item 1). The output format and checkbox typing are assumptions.
3. **Scanned PDFs** inherit OCR mistakes (missed options, headings tagged as questions). These are flagged, not fixed.
4. **Flagged fields are still filled** if they have an answer (section 6, item 4).
5. **The LayoutLM checkpoint licence is unknown** (research-only until confirmed). Only relevant if the project becomes a product.
6. **Speed:** reading the words of the 2-page `Business-Name-Form.pdf` took 64.2 s on this CPU, most of it loading PaddleOCR for the embedded images. Pages without images need no OCR. I didn't time those separately; the whole slow test suite (8 forms through the full pipeline, plus the fast tests) took 157 s.
