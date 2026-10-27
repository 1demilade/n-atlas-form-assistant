# N-ATLAS Form Assistant: prototype report (OCR → LayoutLM → fields)

Date: 2026-10-27. Python 3.11.9 in `.venv`, CPU only (torch 2.14.1+cpu; the Quadro P520 GPU is not used).
Pipeline: image/PDF → `ocr.py` (OpenCV photo cleaning + PaddleOCR) → `layout.py` (`find_fields`: LayoutLM first, rules fallback) → `form_fields.json` + `form_boxes.png` (red = label, blue = answer area).

Git history (each step is one commit, so you can undo any step with `git revert` or `git checkout <hash> -- <file>`):
```
a8a4474 Checkbox groups beat single LayoutLM answers; line-level instruction filter; strictly local model loading; final outputs and run logs
6cb3c6b LayoutLM post-processing: drop instructions, block non-label text, limit answer distance, smooth unsure words; real test_layoutlm.py and ocr_test.py
5eb3b9a Stricter checkbox detection, write-in boxes, option filtering; add generic unittest suite
ae6064f Add layout_lm.py, layout.py find_fields, generic answer areas and field types; make layout_rules generic
6ee5d7c ocr.py: PyMuPDF 200 DPI PDF pages, OpenCV photo cleaning, load PaddleOCR once, prepare_pages()
c3e9ddc Snapshot of existing state before audit
```

---

## 1. What works (command → real output)

All outputs below were produced and checked by running the commands shown. Full logs: `samples/run_log.txt` and `samples/test_log.txt`.

**LayoutLM loads locally and its real label names were confirmed** (not assumed):
```
> .venv\Scripts\python.exe test_layoutlm.py form.png --ocr-json ocr_output.json
model=philschmid/layoutlm-funsd tokenizer=microsoft/layoutlm-base-uncased device=cpu
id2label = {0: 'O', 1: 'B-HEADER', 2: 'I-HEADER', 3: 'B-QUESTION', 4: 'I-QUESTION', 5: 'B-ANSWER', 6: 'I-ANSWER'}
counts: {'header': 1, 'answer': 1, 'question': 13, 'other': 2}
```

**OCR returns Shape 1 for images and multi-page PDFs**, and boxes fit the image that was OCR'd:
```
> .venv\Scripts\python.exe ocr_test.py Business-Name-Form.pdf
PASSED: 67 items from Business-Name-Form.pdf; first: {'text': 'APPLICATION TO REGISTER BUSINESS NAME', 'box': [345, 263, 1334, 303], 'score': 0.996630072593689, 'page': 1}
> .venv\Scripts\python.exe ocr_test.py
PASSED: 13 items from C:\Users\LC\AppData\Local\Temp\tmp9jtlrrxv\synthetic.png; first: {'text': 'CLINIC REGISTRATION', ...}
```

**Full pipeline on four forms.** In the table, "expected" is my own count of real fill-in fields on each form.

| Form | Size | Fields found | Expected | Real fields found | Extras (all `needs_review: true`) | Missed |
|---|---|---|---|---|---|---|
| (a) `form.png` (screenshot, top of page 1 only) | 1086×801 | 9 | 6 | 6 | 3 section headings | 0 |
| (b) `Business-Name-Form.pdf` (2 pages, 200 DPI) | 1655×2339 ×2 | 40 | 34 | 33 | 6 section headings + "Attestation" | 1 ("Date" at the bottom of page 2) |
| (c) `samples/synthetic_form.png` (different wording, underlines, boxes, checkboxes) | 1400×1000 | 10 | 10 | 10 (all 10 types correct) | 0 | 0 |
| (d) `samples/photo_sim.jpg` (form.png warped onto a desk, rotated, shadowed, noisy) | 3000×2250 → cleaned to 1738×1250 | 9 | 6 | 6 | 3 section headings | 0 |

Excerpt (PDF, page 2):
```
> .venv\Scripts\python.exe layout.py Business-Name-Form.pdf --ocr-out samples/pdf_ocr.json --fields samples/pdf_fields.json --boxes samples/pdf_boxes.png
p2 'Surname'                                     text     layoutlm/table_cell
p2 'Date of birth'                               date     layoutlm/table_cell
p2 'Recent Passport Photograph'                  unknown  layoutlm/empty_below (review)
p2 'Phone number'                                phone    layoutlm/table_cell
p2 'Email'                                       email    layoutlm/table_cell
p2 'Identity Number'                             number   layoutlm/table_cell
...
40 fields found. Saved samples/pdf_fields.json and samples/pdf_boxes.png (red = label, blue = answer area).
```
Synthetic form:
```
> .venv\Scripts\python.exe layout.py samples/synthetic_form.png --ocr-json samples/synthetic_form_ocr.json --fields samples/synthetic_form_fields.json --boxes samples/synthetic_form_boxes.png
p1 'Blood group'        unknown  layoutlm/box
p1 'Home address'       text     layoutlm/underline
p1 'Employer'           unknown  layoutlm/underline
p1 'Date of visit'      date     layoutlm/box
p1 'Do you smoke?'      yes_no   layoutlm/checkboxes
p1 'Telephone'          phone    layoutlm/underline
p1 'Town'               text     layoutlm/underline
p1 'Email address'      email    layoutlm/underline
p1 'Preferred contact'  choice   layoutlm/checkboxes
p1 'Patient name'       text     layoutlm/underline
10 fields found.
```

**What I saw when I opened each `*_boxes.png`:**
- **PDF:** every table label has a red box, and its blue box sits on the empty answer cell to its right, stopping at the cell borders.
  - "Phone number" … "Occupation" correctly stop at the photo column.
  - "City/Town/Village" correctly avoids the "You must ensure…" note.
  - Section headings get a red box plus a blue box over the rest of their heading row. That is wrong, but they are flagged for review.
  - "Recent Passport Photograph" gets a blue box below it, inside the photo area.
  - "Signature" gets the empty part of its cell.
  - The bottom "Date" has no box (missed).
- **Synthetic:** all 10 labels are red. The blue boxes follow the underline or the drawn box exactly (within 1 px of the ground truth). The two checkbox questions get a blue box spanning all of their checkboxes.
- **form.png and photo:**
  - Options 1–3 and "Date of commencement" are correct.
  - "General Nature of Business" gets only the first of its 4 answer lines.
  - "Address" at the bottom edge gets a box that crosses the column line, because the cell is cut off by the screenshot edge.
  - The cleaned photo is flat, straight and evenly lit (checked visually).

**Fallback works when LayoutLM fails** (simulated by pointing at a missing model):
```
LayoutLM failed (OSError("We couldn't connect to 'https://huggingface.co' ... couldn't find them in the cached files...")); using rule-based fallback.
11 fields; sources = ['rules']
```

**Automated tests** (no dependence on one sample; 4 generated forms with different seeds and sizes 1400×1000, 900×1300, 2000×1500, 1100×800):
```
> set RUN_SLOW=1 && .venv\Scripts\python.exe -m unittest discover -s tests -v
test_keywords ... ok
test_options_beat_keywords ... ok
test_ocr_and_layoutlm_on_synthetic ... ok
test_label_names_are_parsed_not_assumed ... ok
test_normalize_uses_real_size ... ok
test_words_get_own_boxes_inside_line ... ok
test_generated_forms ... ok
Ran 7 tests in 49.253s
OK
```

## 2. What does not work

No command currently crashes. These are wrong results, not errors:

| Problem | Where | Detail |
|---|---|---|
| Section headings reported as fields | `layout.py` `_layoutlm_candidates` | LayoutLM tags them as QUESTION, e.g. "Address of Branch (if any)", "Proprietor's Address". Their answer method is `own_cell` or `none`, so they are flagged `needs_review`, but they still appear in the list. |
| Last "Date" on PDF page 2 missed | `layout_lm.py` (model output) | The model tags it `header` (`p2 header 0.85 'Date'`), so it never becomes a candidate. |
| Label box can end mid-word | `layout_lm.py` `split_into_words` | Word boxes are estimated from character counts, so bold or proportional fonts drift: the "Proposed Business N\|ame" box ends inside "Name". The label *text* is correct. |
| Multi-line answer areas get only the first line | `answer_areas.py` `find_answer_box` | Seen on "General Nature of Business", which has 4 ruled lines. |
| Rules fallback is noisy | `layout_rules.py` `label_from_text` | On the PDF it found 43 candidates (34 real), including "CAC", "Note", "below". It is good enough as a fallback, not as the main path. |

## 3. Bugs found and fixed

| File | What | Why |
|---|---|---|
| `layout_lm.py`, `test_layoutlm.py` | Were empty (0 bytes); written from scratch | There was no LayoutLM step at all. |
| `layout.py` | Did not exist; `find_fields(ocr_items, image_path)` created | Required by the brief. |
| `layout_rules.py` | `FIELD_DEFINITIONS`, `FIELD_LABEL_HINTS`, `FORM_NOTES`, section strings, and the "Date of commencement / business" special case removed; replaced by generic label rules | The old code could only ever find the 34 CAC fields. |
| `layout_rules.py` | `required: True/False` removed | The brief says never to guess required/optional status. |
| `layout_rules.py` | Types `multiline_text`, `signature`, `file` removed | They are not in the allowed type list. |
| `layout_rules.py` `draw_boxes` | It used to *create* `answer_box` while drawing, from the label's right edge to the rightmost text, so boxes crossed column lines and covered notes. It now only draws. | Drawing must not change the data; answer areas now come from `answer_areas.py`. |
| `layout_rules.py` `draw_boxes` | Draws on the exact cleaned/rendered page images that were OCR'd (`ocr.prepare_pages`) | Before, PaddleOCR rendered the PDF internally and drawing rendered it again separately; they only matched by coincidence (both zoom 2). |
| `ocr.py` | PDFs rendered with PyMuPDF at 200 DPI, page by page | As requested; it also gives one known image per page. |
| `ocr.py` | PaddleOCR loaded once (lazy singleton) | It was re-created on every `read_form` call. |
| `ocr.py` | OpenCV photo cleaning added: find the paper and flatten perspective, deskew, remove shadows | You asked for it; mostly photos are expected. |
| `ocr.py` | Default input file name removed from the CLI (`input` is now required) | No sample file names inside scripts. |
| `ocr_test.py` | Was a pytest function with no runner and a hardcoded `form.png`; now runnable, takes any path (default: a generated synthetic form), and checks boxes fit the page | It did nothing when run. **Signature changed:** `test_read_form_returns_list()` → `test_read_form_returns_list(path)`. |
| `test_layout.py` | Imported `FORM_NOTES` (removed); now runs the rules fallback via `find_fields(..., method='rules')` and takes the form as an argument. Output defaults changed to `form_fields_rules.json` / `form_boxes_rules.png` so it doesn't overwrite the main output. | Would crash on import otherwise. |
| `field_types.py` | "Signature" was typed `text` because "nature" matched inside "sig**nature**"; fixed with word boundaries | Found while inspecting PDF output. |
| `answer_areas.py` | Letters (o, e, B, D, P) were detected as checkboxes | Now a box needs 4 straight inked sides, must be ≥ 0.6× text height, and must not be a small part of an OCR word. |
| `layout.py` | Checkbox option words ("Email", "Yes") were treated as labels | Text at or just right of a checkbox is now an option of the field on that row. |
| `answer_areas.py` | "Do you smoke?" took the "Telephone" underline from the next column; "Phone number" took "Passport" (a LayoutLM answer in another column) | Underlines and LayoutLM answers must now start within a few text heights of the label and before the next label. |
| `layout.py` | Instruction sentences ("Please give…") were tagged as questions | Dropped if the line starts with please/kindly/note, or has more than 12 words without a "?". |
| `ocr.py`, `layout_lm.py` | Runtime network calls: transformers checked huggingface.co and PaddleX checked its model hosts at start-up | `local_files_only=True` and `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`; models are downloaded once with `layout_lm.download_models()`. |

## 4. Bugs found and NOT fixed

1. **Section headings appear as fields** (see section 2). A generic fix would detect "label alone in a full-width table row" as a heading; I didn't want to drop real fields without your input.
2. **The model sometimes tags a real label as `header`** (the PDF's last "Date"). The candidates could also include short `header` entities that have an empty area next to them, but that would add more headings too.
3. **Word boxes are estimated from character counts.** PaddleOCR can return word-level boxes (`return_word_box=True`), which would be exact. I haven't tried it in this version.
4. **Multi-line answer areas** (several ruled lines under one label) only return the first line.
5. **A checkbox label to the *right* of its box** ("☐ I agree to the terms") is treated as an option, not a field, so single-checkbox consent lines are missed.
6. **Photo cleaning turns the image greyscale.** That's fine for OCR, but `form_boxes.png` is grey.

## 5. Things I am not sure about

- **Field types for some labels are `unknown` on purpose:** "Option 1", "Gender", "NIN", "Identity Type", "Local Government", "Signature", "Employer", "Blood group". The form gives no options or format, so I didn't guess. Please confirm that's what you want; a later stage (glossary/N-ATLaS) may handle these better.
- **The keyword lists in `field_types.py` are generic English words** (name, address, date, phone, number, …). Some of them also appear on your sample (e.g. "address", "name"). I treat them as general form vocabulary, not sample-specific names, but you should decide whether that is acceptable.
- **The photo test is simulated** (`form.png` warped onto a fake desk). I have **not** tested a real phone photo; real blur, glare, folds and hand-held angles may behave differently.
- **Only one real form was tested,** and it is a blank, typed, table-style form. LayoutLM quality on handwritten or filled forms is untested here.
- I added three extra keys to each field: `page` (you approved this), `answer_method` and `options`. They are useful for the explanation stage; tell me if you want them removed.

## 6. Information I need from you

1. Should section headings be **dropped**, **kept with `needs_review`** (current behaviour), or returned in a **separate `sections` list**? Sections could also help the Hausa/Yoruba/Igbo explanations.
2. Can you give me **2–3 real phone photos** of forms (any forms) to test with? The current photo test is simulated.
3. **PyMuPDF is AGPL-3.0** (see section 10). If the app will be distributed or offered as a service, should I switch PDF rendering to `pypdfium2`? It is already installed and permissively licensed.
4. Is `form_fields.json` as a **flat list** (current) correct? The old file was `{"fields": [...], "notes": [...]}`.
5. Do you want `form_boxes.png` drawn on the **original colour photo** rather than the cleaned greyscale one? Boxes would then need mapping back through the perspective transform.

## 7. Generalisation risks (forms that will probably struggle)

- **Handwritten or already-filled forms:** answer text in a cell makes the "empty cell" rule skip it. LayoutLM's ANSWER label should help here, but it is untested.
- **Labels below or above the line** (label printed under the underline), **vertical/rotated text**, and **multi-column forms with no ruling lines**: the empty-space fallback may pick the wrong area.
- **Non-English forms** (Hausa/Yoruba/Igbo printed forms): the FUNSD checkpoint and the type keywords are English only.
- **Dense forms with more than 512 tokens per page** are handled by overlapping windows, but this was only checked in code, not on a real dense form.
- **Very low-resolution or blurred photos:** the cleaning upscales to 1000 px minimum but can't recover detail. Rotations above 15° are not straightened.
- **Photos where the paper does not contrast with the background** (white paper on a white table): the perspective correction is skipped.
- **Dotted-line answer areas:** small gaps are closed, but widely spaced dots may not be detected as lines.

## 8. Hardcoded / sample-specific items

**Removed:**
- From `layout_rules.py`:
  - all 34 CAC field definitions, label hints and section aliases;
  - `FORM_NOTES`, including quickservice@cac.gov.ng;
  - the `dateofcommencementof` + `business` merge;
  - the `commencement_date` special case;
  - the required flags.
- Default file names inside logic: `ocr.py` used to default to `Business-Name-Form.pdf`, `ocr_test.py` used `form.png`, and `test_layout.py` defaulted `--form` to the PDF.

**Left on purpose (generic, not sample-specific):**
- Thresholds in config blocks at the top of files, all relative to page size or text height:
  - `PDF_DPI=200`, `MAX_SIDE=2400`, `MIN_SIDE=1000`, deskew limits;
  - `ROW_TOLERANCE`, `UNSURE_WORD=0.6`, `REVIEW_BELOW_CONFIDENCE=0.6`;
  - `MAX_QUESTION_WORDS=12`, `MAX_LABEL_WORDS=8`.
- Keyword lists in `field_types.py` and the instruction words (please/kindly/note) in `layout.py`.
- CLI default *output* names (`ocr_output.json`, `form_fields.json`, `form_boxes.png`), as allowed by the brief.
- `make_synthetic_form.py` contains test labels ("Patient name", …) by design: it is the generator for test forms, not part of the pipeline.

## 9. How to run everything (Windows, from the project folder)

```bat
REM 0. One-time setup (already done on this machine)
.venv\Scripts\pip.exe install pymupdf
.venv\Scripts\python.exe -c "import layout_lm; layout_lm.download_models()"

REM 1. Full pipeline (OCR + LayoutLM + answer areas + types) on a photo, scan or PDF
.venv\Scripts\python.exe layout.py form.png
.venv\Scripts\python.exe layout.py Business-Name-Form.pdf --ocr-out samples\pdf_ocr.json --fields samples\pdf_fields.json --boxes samples\pdf_boxes.png
REM    reuse saved OCR (faster):  --ocr-json ocr_output.json
REM    force a method:            --method layoutlm | rules
REM    skip photo cleaning:       --no-clean

REM 2. Individual steps
.venv\Scripts\python.exe ocr.py form.png --output ocr_output.json --save-pages samples\cleaned
.venv\Scripts\python.exe ocr_test.py Business-Name-Form.pdf
.venv\Scripts\python.exe test_layoutlm.py form.png --ocr-json ocr_output.json
.venv\Scripts\python.exe test_layout.py form.png --input ocr_output.json

REM 3. Make a new synthetic test form (change seed/size for a different layout)
.venv\Scripts\python.exe make_synthetic_form.py --out samples\synthetic_form.png --seed 3 --width 1400 --height 1000 --count 10

REM 4. Tests (fast: about 1 s; slow adds PaddleOCR + LayoutLM: about 50 s)
.venv\Scripts\python.exe -m unittest discover -s tests -v
set RUN_SLOW=1
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

In Python: `from ocr import read_form; from layout import find_fields; fields = find_fields(read_form(path), path)`.
The later N-ATLaS step is a stub, `layout.explain_fields_in_language`, which raises `NotImplementedError`.

## 10. Licence notes (as far as I could see)

| Component | Licence | Source |
|---|---|---|
| `microsoft/layoutlm-base-uncased` (tokenizer, base model) | MIT | `license: mit` in its README on the Hub |
| `philschmid/layoutlm-funsd` (checkpoint) | **Not stated** | The model card has no licence field. It is fine-tuned from the MIT base model on **FUNSD**, whose authors released it for non-commercial research and educational use (from memory; please check the FUNSD page). **Treat the checkpoint as research-only until confirmed.** |
| PaddleOCR 3.7.0, PP-OCRv6 det/rec models | Apache-2.0 | `pip show paddleocr` |
| transformers 5.21.0 | Apache-2.0 | `pip show transformers` |
| opencv-contrib-python 4.10 | Apache-2.0 | `pip show opencv-contrib-python` |
| **PyMuPDF** | **AGPL-3.0 or Artifex commercial** | `pip show pymupdf`. AGPL requires releasing your source if you distribute the app or offer it over a network. `pypdfium2` (already installed) is a permissive alternative. |
