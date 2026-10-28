# N-ATLAS Form Assistant: prototype report (PDF forms → fields → filled PDF)

Date: 2026-10-27, updated 2026-10-28 with the missing part of the brief (section 0) and your answers to my questions (section 00). Python 3.11.9 in `.venv`, CPU only.
Scope (supervisor, 27 Oct 2026): input is a **digital PDF**, either (A) fillable (AcroForm fields) or (B) flat, with a text layer or image-only (scanned). Voice and N-ATLaS are later stages. Photos are no longer a main input; the photo path (OpenCV cleaning, perspective, deskew) is kept as a working fallback and its tests still pass. Answers come from `answers.json` (field id **or key** → English text).

## 0000. Update 2026-10-28 (fourth round): a real flat form (`afan.pdf`) and nine generic fixes

Details and before/after per field: `docs/real_form_test.md`, round 3.

**First run:** found all 25 real fields of the AFAN membership form, but also:
- a false field from the letterhead;
- item 12 split in two;
- a watermark cutting the E-mail line;
- signature lines missed;
- a two-line answer cut to one line;
- item numbers inside labels;
- a missed capitals heading;
- no office-use or signature marker.

**Fixes** (one commit each, each with a test on a generated PDF):

| Commit | Fix |
|---|---|
| `634e571` | pale watermark OCR words dropped |
| `e58123c` | item numbers stripped from labels |
| `fc57d71` | wrapped questions after an unfinished line |
| `9c2c4f5` | label printed under its line (`line_above`) |
| `a1cfe93` | multi-line answer areas (`answer_lines`, filled line by line); fixes old bug #1 (section 4) |
| `c3f6565` | capitals headings as sections |
| `243a908` | on blank PDFs, printed text tagged as an answer is not a field (listed in `notes`) |
| `8fb387b` | office-use fields: `ask_user: false`; `fill_form` skips these on flat pages too |
| `c002133` | signature/thumbprint fields: `ask_user: false` |
| `58f658e` | "specify" questions are `text` (a regression from stripping item numbers) |

**Tests:** 51, all OK with `RUN_SLOW=1`.

**After the fixes:**
- **AFAN:** 25 fields, exactly the real ones; 3 real sections; every answer box on its line.
- **Not asked:** the office and signature fields are kept with `ask_user: false`.
- **Flagged:** only item 17 (no line on the page) and the official fields.
- **`sample_form_1/2`:** re-run, unchanged.

**New extra keys:**
- every flat field: `answer_lines`;
- `skip_reason` can now be "for official use (…)" or "signature or thumbprint: …".

**Behaviour changes to know:**
- `Business-Name-Form.pdf` was not re-run. Its "Signature" field will now be `ask_user: false`, so `fill_form` no longer types text into it.
- Other changes there (watermark, numbers, headings) are possible.

## 000. Update 2026-10-28 (third round): two real fillable PDFs, and the fixes they led to

Full details, per field: `docs/real_form_test.md`. The real PDFs are in `samples/real/` but not in git (`.gitignore`; `samples/real/README.md` says what they are).

**First test (read-only):**
- All 17 fields were found, all answer boxes are right, and `pdf_kind` and sections are right.
- 3 labels were wrong or missing; one of them was wrong with confidence 0.998 and not flagged.
- A hidden field and a read-only calculated field were listed as normal fields.

**Fixes** (generic only; one commit each, each with a test on a generated PDF that reproduces the problem):

| | Commit | Change |
|---|---|---|
| a | `7537677` | Fillable labels: other lines above the input about as close as the chosen label are rivals. A line ending with `:`/`?` beats one that doesn't. Rivals → `needs_review`, listed in `label_alternatives`. |
| b | `9aede38` | A prompt above-left of the input (it ends before the input starts) is the label when nothing is on the left or above. Flagged. |
| c | `28590ee` | `ask_user`, `skip_reason`, `hidden` on every field. Read-only, calculated (`/AA /C`, `/CO`) and hidden fields are kept with `ask_user: false` (hidden: also `needs_review`). `fill_form` skips every `ask_user: false` field. |
| d | `ae3e24f` | Fields that share a label are all flagged (any path, including flat). |
| e | `258ac60` | Editable combo boxes: `editable: true`; `fill_form` writes a typed value that is not in the list. |
| — | `0c67462` | `scripts/list_widgets.py` (pypdf-only widget list, usage in its docstring); `samples/real/*.pdf` ignored. |

**Tests:** 41 (35 old + 6 new), all OK with `RUN_SLOW=1`; photo-path tests unchanged and passing.

**After the fixes, on the two real forms:**
- **Form 1:** 5/5 labels right (was 3/5); no null labels.
- **Form 2:** unchanged labels. The shared "Auto-calculation" pair and the hidden field are now flagged; the hidden field and the sum have `ask_user: false`.
- **Both forms:** no wrong label left unflagged, except form 2's "Field-specific buttons", which is the only text printed near that box.
- **Fill by key:** 5/5 and 10/10 filled and verified (values read back, ink in box), plus a typed value in the editable dropdown. Both not-asked fields were skipped, and the originals are unchanged (sha256).

**Smaller items, noted and not fixed** (you asked me to skip them):
- A read-only calculated field is typed `text` (its calculate script is not used as a type hint).
- The PDF's email validation script (`/AA /V`) is not read; the type comes from the label.
- Pages whose only widgets are buttons are still `kind: 'fillable'`.
- The "Field-specific buttons" label (specific to that form).
- `calcsum`'s label is still "=" (the field is no longer asked).

**Found during the fill test, not fixed:**
- the calculated sum stays "0", because no PDF JavaScript runs;
- the list box keeps its old scroll position, so the chosen "March" is out of view;
- a long typed value is cut off on screen in a narrow combo box (the value in the file is complete);
- `fill_form` crashes on an `answers.json` with a UTF-8 BOM.

**Not re-run:** `Business-Name-Form.pdf` (rule d may flag more of its fields).

## 00. Update 2026-10-28 (second round): your answers to my questions

| # | Your answer | What I changed | Commit |
|---|---|---|---|
| 1 | An instructions-only page must not make a fillable PDF `mixed` or produce false fields. `mixed` only when a page without widgets holds real fields. | In a PDF with widgets, pages without widgets still go through the flat path, but **every flagged field there is dropped** (`needs_review`: confidence < 0.6, a guessed answer area, or heading-like text) and listed in `form.notes`. A page left with no fields gets `kind: 'instructions'` and does not count for `pdf_kind`. A PDF without widgets is unchanged. | `a255a8c`, `44eb584` |
| 2 | Validate flat answers too. | Flat answers are checked with the same rules: the type patterns (number/date/email/phone); options for `choice`/`yes_no`; a yes/no word for `yes_no` without printed options. Invalid → `refused`, nothing drawn, listed in the summary. | `8f71a68` |
| 3a | A group of several options is `choice`; a lone checkbox is `yes_no`. | Radio groups and same-name checkbox groups are now `choice` **even when the options are Yes/No** (they were `yes_no`). On flat PDFs, a field whose answer area is 2+ checkboxes is `choice`, a single checkbox `yes_no`. This applies to **PDF input only**; the photo fallback keeps its old typing, so its tests are untouched. | `8f9685c` |
| 3b | Independent checkboxes in a group are `choice`, take a list of values, and are flagged. | Lone checkboxes (separate PDF fields, one widget each, not radio) that sit next to each other in a row (gap ≤ 12 text heights) or a column (left edges within 1 text height, gap ≤ 1.5 text heights) become **one field**: `type: 'choice'`, `multiple: true`, `needs_review: true`, `answer_method: 'acroform_checkbox_group'`, `pdf_field_name`: **a list** of the member names (one per option), `id`: the names joined with `+`. Label = question left/above the group (same chain: LayoutLM question → nearest text). Fill: a list (or one string) of options. Chosen boxes get their real on-state from the PDF, the others Off. Any unknown option refuses the whole answer. A list for any other field is refused. | `dc5e195` |
| 4 | Keep the extra keys; mark spec vs extra in the report. | Section 5 now has the table. | (this report) |
| 5 | `my_form.png`: leave it untracked. | Untouched. | — |

Tests added (in `tests/test_pdf.py`, all on generated PDFs):
- (1) `test_instructions_page_is_not_mixed`; slow: `test_instructions_page_with_layoutlm`. Without the new rule, the instructions page produced 2 false fields ("Notes for applicants", "Note") and `mixed`; now `fillable`, page 2 `instructions`, 0 fields there. `test_mixed_pdf_uses_both_paths` (fillable page + real flat page) still gives `mixed`.
- (2) `test_flat_invalid_values_are_refused`.
- (3) `test_independent_checkbox_groups`; slow: `test_checkbox_groups_with_layoutlm`; `test_pdf_kind`, `test_on_states_come_from_the_pdf` (lone checkbox = `yes_no`); the radio expectations in the older tests now expect `choice`.

New generator functions (test data only): `make_test_pdfs.make_instructions_pdf` and `make_checkbox_group_pdf`. The latter has field names like `Check Box1` and on-states that alternate between `/Yes` and `/On`.

**One slow test needed an explicit exception, and you should know why.** On the generated **scanned** page, OCR drops the option "Yes" next to its box (known bug, section 4 item 4). The pipeline then sees only one checkbox for "Do you smoke?", so it is not a group and stays `yes_no`. Before, this was hidden, because "Do you…" gave `yes_no` from the label words. The test now skips the type check only when a scanned page's field found a strict subset of the real options, and it still requires those options to be real. I did not change the shared checkbox detection (it also serves the photo path).

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

**`pdf_kind` rule** (updated with your answer, section 00):
- Each page is `fillable` (has widgets), `flat_text` (words from the text layer, with or without OCR of embedded images) or `flat_scanned` (OCR only).
- In a PDF with widgets, a page without widgets that keeps no confident field is `instructions`, and it is ignored.
- If the remaining pages agree, that is the kind; otherwise `mixed`.
- Widget pages go through the AcroForm path, other pages through the flat path. `fill_form` picks the method per field: `pdf_field_name` set → pypdf values; null → overlay.
- Tested on generated 2-page PDFs: fillable + real flat page → `mixed`; fillable + instructions page → `fillable`.
- **Not changed:** a PDF without widgets whose pages are partly text-layer and partly scanned is still `mixed`. Your answer was about fillable PDFs, so tell me if this case should be different.

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
23345e6 Samples: checkbox groups (valid and invalid answers), fillable form with an instructions page; run and test logs
44eb584 analyse_form: instructions pages add no 'none' to the method
44b7d2d Slow test: on scanned pages, a group with a missed OCR option is the known limitation, not a type error
dc5e195 Independent checkboxes side by side or stacked: one flagged 'choice' field that takes a list of values
8f9685c PDF checkbox types: a group of options is 'choice' (Yes/No too), a lone checkbox is 'yes_no'
8f71a68 fill_form: validate flat answers against type and options too; refuse and list invalid values
a255a8c Fillable PDFs: pages without widgets keep only confident fields; empty ones are 'instructions', not 'mixed'
--- second round above (section 00) ---
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
- `samples/run_log_answers.txt`: every pipeline and fill run after the section 00 changes (latest);
- `samples/run_log_brief.txt`: pipeline and fill runs on 2026-10-28, after the section 0 changes;
- `samples/run_log_pdf.txt`: the runs of 2026-10-27 (old output format);
- `samples/test_log_pdf.txt`: full test run (2026-10-28, 35 tests).

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

**Tests** (generated forms only; 4 seeds, 3 page sizes, labels left of or above inputs). 12 new tests for section 0, 5 for section 00; the photo-path tests (`tests/test_pipeline.py`) are unchanged and pass:
```
> set RUN_SLOW=1 && .venv\Scripts\python.exe -m unittest discover -s tests -v
section 00: test_instructions_page_is_not_mixed, test_instructions_page_with_layoutlm,
     test_flat_invalid_values_are_refused, test_independent_checkbox_groups,
     test_checkbox_groups_with_layoutlm ... ok
section 0: test_field_name_is_never_a_label, test_pdf_kind, test_mixed_pdf_uses_both_paths,
     test_keys_from_labels, test_answers_by_key_or_id, test_on_states_come_from_the_pdf,
     test_check_value, test_invalid_values_are_refused, test_fields_list_or_form_object,
     test_never_overwrites_the_original, test_verification_catches_missing_ink,
     test_filled_flagged_fields_are_listed ... ok
older PDF tests (now also assert verified == all True on every fill) ... ok
photo-path tests (7): test_generated_forms, test_ocr_and_layoutlm_on_synthetic, ... ok
Ran 35 tests in 205.637s
OK
```
Fast tests only (no `RUN_SLOW`): `Ran 35 tests ... OK (skipped=5)`.

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

- **Output format: your spec, plus extra keys (kept, your answer 4).** **Spec** = required by your brief; **extra** = added by me.

  | Where | Spec (required) | Extra (kept) |
  |---|---|---|
  | top level | `form`, `sections`, `fields` | — |
  | `form` | `source_file`, `pdf_kind`, `pages` | `method`, `notes` (e.g. dropped instruction-page fields) |
  | each page | `page`, `width_px`, `height_px`, `dpi` | `width_pt`, `height_pt`, `rotation`, `widgets`, `word_source`, `kind` (`fillable` / `flat_text` / `flat_scanned` / `instructions`) |
  | each field | `id`, `label`, `label_box`, `answer_box`, `type`, `page`, `pdf_field_name`, `required`, `options`, `source`, `confidence`, `needs_review`, `answer_method` | all fields: `key`, `section`; fillable: `label_source`, `type_source`, `pdf` (name, field_type, flags, required, read_only, tooltip, max_length, default_value, value, option_values, format_script, widgets; groups add `members`); flat: `option_boxes`; independent-checkbox groups: `multiple: true` |
  | each section | (your spec shows `[...]`) | `id`, `title`, `box`, `page`, `source`, `reason`, `confidence`, `needs_review` |

  **One spec deviation:** for an independent-checkbox group, `pdf_field_name` is a **list** of PDF field names (one per option), not a single string, because the group really is several PDF fields. Every other fillable field has a string; flat fields have `null`.
- **Where LayoutLM is used: now as in your brief** (labels for fillable widgets; the flat path). It is also still used to decide what is a section, which the brief does not mention.
- **Checkbox typing: your rule now** (section 00). A group of options → `choice` (Yes/No too); a lone checkbox → `yes_no`; independent checkboxes in a group → one flagged `choice` that takes a list; combo and list boxes → `choice`. **What counts as "a group" of independent checkboxes is my geometry rule** (same row within 12 text heights, or a column with aligned left edges and gaps ≤ 1.5 text heights). Two unrelated yes/no checkboxes stacked closely (e.g. "☐ I agree" over "☐ Send me news") would be merged into one group; that group is flagged, but it is still wrong. On **flat** PDFs, a checkbox group takes one value: nothing on the page says whether several may be ticked.
- **Text fields on fillable PDFs default to `text`.** Number, date or phone only when the PDF's format action (AFNumber_/AFDate_/AFSpecial_) or the label or tooltip words say so. So "Next of kin" is `text` on the fillable form but `unknown` on the flat one.
- **Field id = full AcroForm name** on fillable PDFs (your "my call"); the readable `key` sits next to it (your decision).
- **Type validation on fillable and flat PDFs** (your answer 2). Flat types are guesses from label words, so a wrongly typed flat field (e.g. a "Number" label that takes letters) will refuse a correct answer; the reason says which type was assumed. Date validation accepts both day-first and month-first, plus ISO and written months; it does not check against the field's own AFDate format string.
- **`pdf_kind` of a photo** (fallback path): `flat_scanned`, since a photo is a scanned flat page.
- **"Real text" rule** (your "my call"): a page uses its text layer if it has at least 3 real words and at most 20% garbage (`(cid:NN)`, U+FFFD). On those pages, embedded images are OCR'd too and their text is added with `source: 'ocr'`. This goes against my own plan ("no mixing within a page"), because on your real form 4 labels exist only as images. The page records `word_source: 'pdf_text+ocr_images'`.
- **Only two real fillable PDFs tested** (third round, section 000): two small demo forms from Word. Real forms made in Acrobat, Word or LibreOffice use features my generator doesn't (calculated fields, hierarchical names, XFA, appearance streams without `/NeedAppearances`).

## 6. Information I need from you

All earlier questions are answered (sections 0 and 00). New, smaller ones:

1. **A PDF without widgets, with text-layer and scanned pages:** still `mixed`. Should it be?
2. **Independent-checkbox `pdf_field_name` as a list** (section 5): acceptable, or do you want another shape?
3. **Grouping rule for independent checkboxes** (section 5): is "close together in a row or column" good enough, or should a group also need a shared question label?
4. **Flat checkbox groups:** keep one value, or also accept a list like the fillable groups?
5. **Real fillable PDFs** for `samples/real/` (section 13, item 1).

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
| **Mixed** (`mixed`) | per page | widget pages as (A), other pages as (B) keeping only confident fields; a page left empty is `instructions` and the PDF stays `fillable` | per page | per page | per page | per field: pypdf for widgets, overlay for the rest (tested on generated 2-page PDFs) |
| **Independent checkboxes** (inside A) | — | lone checkboxes close together in a row/column → one field | question left/above the group | `choice`, `multiple: true`, flagged | — | a list of options; chosen boxes get their PDF on-state, others Off; each member read back + render check |
| **(B1) Flat with text layer** (`flat_text`) | text layer (+ image OCR) | LayoutLM questions + drawn answer areas (cells, underlines, boxes, checkboxes, lines below the label) | LayoutLM, rules fallback | label words + options; a checkbox area of 2+ boxes → `choice`, of 1 box → `yes_no` | LayoutLM headers; labels with no area or alone in a full-width row; larger text with only a guessed area | after type/option validation: text drawn in the answer box; X in the chosen checkbox |
| **(B2) Flat, image-only** (`flat_scanned`) | PaddleOCR on the 200 DPI render | same as B1 | same as B1 | same as B1 | same as B1; the larger-text rule is unreliable on OCR boxes | same as B1 |

## 12. Fill results

Re-run after the section 00 changes (`samples/run_log_answers.txt`); the results of the earlier rows did not change. "Verified" is `fill_form`'s own check of the written file (section 0, item 8).

| PDF | Answers | Filled | Refused | Skipped | Verified | Also checked by eye |
|---|---|---|---|---|---|---|
| `test_checkbox_groups.pdf` | 4 by key: `["English", "Yoruba"]`, `"Lab test"`, `"yes"`, `"Ada Obi"` | 4 | 0 | 0 | 4/4 | render: English and Yoruba ticked, Hausa empty; only Lab test ticked; "I agree" ticked; name in its box |
| `test_checkbox_groups.pdf` | 4, deliberately invalid: `["English", "French"]`, `"maybe"`, a list for the name | 1 | 3 (`['French'] match no option`, `'maybe' is not yes/no`, `a list of values is only accepted for independent checkboxes`) | 0 | 1/1 | — |
| `test_fillable_with_notes.pdf` (analysis only) | — | — | — | — | — | `pdf_kind=fillable`, p2 `instructions`, note: "2 low-confidence field(s) dropped on pages without widgets: p2 'Notes for applicants', p2 'Note'" |
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
- **Refused, with a reason** (fillable and flat): answers longer than `max_length`; answers matching no option; wrong type (number/date/email/phone); a non-yes/no answer for `yes_no`; a list for anything but an independent-checkbox group.
- **Skipped, with a reason:** unknown ids or keys; different answers for id and key; an option whose on-state is not in the PDF.
- Read-only and signature fields are skipped too.

Observed limits:
- On underlines, answer text is smaller than the form's own text: the answer area is one text line tall and the font is 75% of it.
- Single-line answers sit low in tall cells (deliberate, so they land on underlines).
- Typed text is written into signature cells if `answers.json` has an entry for them.

## 13. Remaining risks

1. **Few real fillable PDFs tested — still the main risk.** Two real demo forms (Word-made, section 000 and `docs/real_form_test.md`) now pass after the third-round fixes; they include a calculated field, a hidden field, an editable combo and push buttons. They do not include hierarchical names, XFA, `/D`-only states or long multi-page government forms. More real forms in `samples/real/` would help.
2. **Still my own rules** (section 6): the geometry that decides which independent checkboxes form a group; `mixed` for flat PDFs with text and scanned pages; a list as `pdf_field_name` for groups.
3. **Scanned PDFs** inherit OCR mistakes (missed options, headings tagged as questions). These are flagged, not fixed. New consequence: a missed option can stop a checkbox group from being seen as a group, so it is typed from its label words instead of `choice` (seen on the generated scanned page; section 00).
4. **Dropping flagged fields on pages without widgets** could also drop a real but uncertain field there (e.g. a blank whose answer area had to be guessed). Each dropped field is listed in `form.notes`.
5. **Flagged fields are filled** if they have an answer (your decision). They are now listed in the fill summary.
6. **Verification is coarse.** `ink_in_box` proves that new ink landed inside the box, not that it is the right text. For flat fills, the tests also re-read the drawn text with pdfplumber.
7. **The LayoutLM checkpoint licence is unknown** (research-only until confirmed). Only relevant if the project becomes a product.
8. **Speed:** reading the words of the 2-page `Business-Name-Form.pdf` took 64.2 s on this CPU, most of it loading PaddleOCR for the embedded images. Pages without images need no OCR. I didn't time those separately; the whole slow test suite (8 forms through the full pipeline, plus the fast tests) took 157 s.
