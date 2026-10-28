# Real fillable PDFs: accuracy test

Python: `.venv\Scripts\python.exe`, CPU only. The two source PDFs are not in git (`samples/real/README.md` says what they are).

- **Round 2** (below): after the five generic fixes you asked for, re-read both forms and filled them.
- **Round 1** (sections 1–8): the first read-only test, kept as the record.

---

## Round 3 (2026-10-28): `afan.pdf`, a real flat form, and nine generic fixes

### R3.1 The form and the first run

`afan.pdf`, the AFAN "Membership Registration Form":
- one A4 page, made in CorelDRAW, with no AcroForm (`scripts/list_widgets.py`: 0 widgets);
- a text layer, plus two embedded pictures: the logo and a pale watermark across the middle of the page;
- **25 real fields**, which I counted on my own render:
  - items 1–18, where item 7 holds two (Date of Birth, Telephone), item 11 holds three (a, b, c), and item 12 is one question wrapped over two lines;
  - the applicant's signature;
  - the coordinator's Signature and Date;
  - the Chairman's approval.

The first run found 27 fields: all 25 real ones, plus two that are not fields. Problems:

| Problem | Flagged? | Cause |
|---|---|---|
| Letterhead "ALL FARMERS ASSOCIATION OF NIGERIA (AFAN) Head Office" was a field; its "answer" was part of the address | yes | the model tagged printed text as an answer |
| Item 12 split into two fields; "Other (Specify)" got only half the question | first half yes, second no | the wrapped-line rule wanted a lowercase second line |
| E-mail box covered a third of its line | yes | OCR read the watermark ("RSAS"), and that word cut the line |
| Coordinator's Signature and Date: boxes to the right, not on the lines above | yes | no rule for a label printed under its line |
| Item 16: only the first of its two ruled lines | no | old one-line limit |
| Items 10–18 kept their number in the label; items 12 and 17 typed `unknown` | — | the number broke the yes/no rule |
| "RECOMMENDATION BY …" heading missed, so the fields under it went to the wrong section | — | the model tagged it `other` |
| Office fields (coordinator, Chairman) and signatures asked like normal fields | — | no office-use or signature marker |

### R3.2 Fixes

Each fix is a separate commit with a test on a generated PDF. Each test was first shown to fail on the code before its fix, or the test checks a key the old code didn't have.

| # | Commit | Fix |
|---|---|---|
| 1 | `634e571` | OCR words from embedded pictures whose ink is pale (median grey > 180) are dropped as watermark. Measured on this page: watermark 227; black, red and green print 38–106. |
| 2 | `e58123c` | `clean_label` drops a leading item number (`17.`, `(a)`, `iv)`, followed by a space); `e.g.`, `No. of` and `1.5` are untouched. |
| 3 | `fc57d71` | A label line that stops mid-sentence (`,`, `(`, open bracket, joining word) takes the next line; a label also takes an unfinished line right above it. The answer is searched beside the last line. |
| 4 | `9c2c4f5` | New answer step `line_above`: a line just above a label (at most 0.6 text heights) that spans it, with no other text under it. |
| 5 | `a1cfe93` | Blank ruled lines directly under an answer line (no text on their row) extend it: `answer_lines`; `fill_form` writes long answers line by line. |
| 6 | `c3f6565` | A capitals line (2+ words, alone on its row, no `:`) is a heading candidate: a section (`caps_line`, flagged), or a flagged field if it has a drawn answer area. |
| 7 | `243a908` | PDF input only: a label whose only answer is printed text, with nothing drawn there, is not a field; it is listed in `form.notes`. A placeholder on a line, or an option word next to its checkbox, still counts. |
| 8 | `8fb387b` | Office-use wording in the label or section heading (official use, approval/recommendation/endorsed/verified/certified by, to be completed by the officer…) → `ask_user: false` + reason + `needs_review`. `fill_form` now skips `ask_user: false` on flat pages too. |
| 9 | `c002133` | Signature / thumbprint / initials fields (and AcroForm `/Sig` fields) → `ask_user: false`; a date of signature is still asked. |
| — | `58f658e` | Regression from fix 2: "Are you … Other (Specify)" became `yes_no`, so a real answer would be refused. A label asking to "specify" is now `text`. |

**Tests:** 51 tests, all OK with `RUN_SLOW=1` (192 s). The photo-path tests are unchanged and pass.

**Other forms:** `sample_form_1.pdf` and `sample_form_2.pdf`, re-run from their saved words, give exactly the same fields, labels, types, boxes, flags and sections as before.

### R3.3 AFAN after the fixes

Same `layout.py` command. 83 s, almost all of it PaddleOCR (loading it and reading the 2 pictures).

**Result: 25 fields, the real 25; no false field; 3 sections, all real.**
- Note: "'ALL FARMERS ASSOCIATION OF NIGERIA (AFAN) Head Office' is not a field: its answer is printed text ('No. 1, Uke Street, Area 11, Garki,')."
- Sections:
  - "MEMBERSHIP REGISTRATION FORM";
  - "Details of Membership", now flagged: the model's own header confidence fell from 0.79 to 0.59. Probably because the watermark word is gone and the model reads the whole page at once; I can't prove that;
  - "RECOMMENDATION BY LOCAL GOVERNMENT AFAN COORDINATOR" (`caps_line`, flagged).

| Field | Before | After |
|---|---|---|
| Letterhead "… Head Office" | field (flagged) | **not a field**, in `notes` |
| 1–5, 7–9, 13–15, 18, 11(a)(b)(c) | right | right; numbers gone from labels and ids ("Other Commodity Association", "How Long") |
| 6. E-mail | 1/3 of the line (flagged) | **whole line** (`underline`, not flagged) |
| 12 + "Other (Specify)" | 2 fields, one with half the question | **1 field**: "Are you a service provider (Agric input, Dealer, Processor, Marketer, Other (Specify)", answer on the "Other (Specify)" line, type `text` |
| 16. Input Uses | first line only | **both lines** (`answer_lines`: 2) |
| 17. Insurance | `unknown`, margin box (flagged) | `yes_no`, margin box (flagged). The page has no line for it, so a guess is all there is |
| Applicant's Signature / Thumb Print | asked | kept, `ask_user: false` (signature) |
| Coordinator's Signature, Date | boxes to the right (flagged) | **on their lines** (`line_above`); `ask_user: false` (office use, plus signature for Signature) |
| Approval by State AFAN Chairman | asked (flagged) | `ask_user: false` (office use), flagged |

**On the boxes image:**
- no box on any letterhead text;
- every blue box sits on its line;
- item 12's red box covers both lines of the question;
- Signature and Date have their boxes on the lines above them;
- the RECOMMENDATION heading is green.

**Left as is:**
- Item 16's combined box also covers part of its own label on the first row. Filling uses `answer_lines`, so this is only how it looks.
- 9 fields are still typed `unknown` (e.g. "Local Government Area", "Bank Details"): no type rule fits them.
- "No." at the top and the passport-photo box are not fields (office number and photo).

**Fill:** not run on AFAN in this round.

---

## Round 2 (2026-10-28, after the fixes)

### R2.1 What changed in the code

Each fix is a separate commit with its own test on a generated PDF (`make_test_pdfs.make_widget_pdf`), never on these forms. Each test was first run against the code before the fix, to confirm it reproduces the problem.

| Fix | Commit | Rule now | Before the fix, on the test PDF |
|---|---|---|---|
| a. Short line above the input taken as the label | `7537677` | Other lines above the input within 2 text heights of the chosen label's distance are **rivals**. A rival ending with `:` or `?` wins over a label that doesn't. Any field with rivals gets `needs_review: true` and lists them in `label_alternatives`. | "First option" and "Example: Lagos" chosen, `needs_review: false` |
| b. Prompt above-left of the input | `9aede38` | New side `above_left`, tried only after left and above: the prompt sits within 2.5 text heights above the input and ends at most 3 text heights left of where the input starts. Always `needs_review`. | `label: null` |
| c. Read-only / calculated / hidden | `28590ee` | Every field has `ask_user`, `skip_reason`, `hidden`. Read-only, calculated (`/AA /C` or in `/CO`) or all-widgets-hidden → `ask_user: false` + reason; hidden also `needs_review: true`. `fill_form` skips every `ask_user: false` field, even with an answer. | calculated and hidden fields were overwritten |
| d. Same label on several fields | `ae3e24f` | `analyse_form` flags every field whose label (normalised) appears more than once, on any path. | both "Phone number" fields unflagged |
| e. Editable combo boxes | `258ac60` | `editable: true` (type stays `choice`). `fill_form` writes a matching option's export value, otherwise the typed text. Non-editable choices still refuse. | typed value refused |
| — | `0c67462` | `scripts/list_widgets.py` (the pypdf ground-truth script) and `samples/real/*.pdf` in `.gitignore`. | — |

**Tests:** 41 tests (35 old + 6 new), all OK with `RUN_SLOW=1` (161 s); without it, `Ran 41 ... OK (skipped=5)`. The photo-path tests are unchanged and pass.

**New keys** (extra, not in your spec):
- on every field: `ask_user`, `skip_reason`, `hidden`, `editable`;
- on fillable fields only: `label_alternatives`;
- inside the `pdf` block: `calculated`.

### R2.2 Re-read: same command as round 1

- **Command:** the same `layout.py` command as round 1, on both forms. Both exited 0, and stderr is only the weight-loading bar.
- **Time:** 25.3 s and 22.8 s (12.2 s and 10.7 s in round 1). The fixes only add geometry checks over a few dozen words, so I suspect other load on the machine, but **I did not measure what caused it**.
- **Unchanged:** the word files are byte-identical, every `answer_box` is unchanged, and the field count (5 and 12), `pdf_kind` (`fillable`) and sections are the same.

**Form 1, before → after**

| Field | Label before (source) | Flagged before | Label after (source) | Flagged after | Correct now? |
|---|---|---|---|---|---|
| `Name` | `null` (none) | yes | "Please enter your name" (`nearby_text_above_left`) | yes | **yes** (was missing) |
| `Dropdown2` | "First Choice" (`layoutlm_above`, 0.998) | **no** | "Please select an item from the combo/dropdown list" (`nearby_text_above`, 0.4), `label_alternatives: ['First Choice']`, `editable: true` | yes | **yes** (was wrong, unflagged) |
| `Option 1+2+3` | "Check all that apply" (`layoutlm_above`) | yes | same | yes | yes |
| `Name of Dependent` | "Name of Dependent" (`layoutlm_left`) | no | same | no | yes |
| `Age\t of Dependent` | "Age of Dependent" (`layoutlm_left`) | no | same | no | yes |

Both prompts start with "Please", so the LayoutLM-label code treats them as instructions (`layout._is_instruction`), not label candidates. They were found as plain text, which is why the source is `nearby_text_*` with confidence 0.4. On the new boxes image I checked that the red boxes now sit on both prompts, there is no box on "First Choice", and the blue boxes are where they were.

**Form 2, before → after** (only rows that changed; the other 7 are identical, all correct and unflagged)

| Field | Label (source), same before and after | Flagged before → after | New markers | Why |
|---|---|---|---|---|
| `calc1` | "Auto-calculation" (`layoutlm_above`) | no → **yes** | — | shares its label with `calc2` (d) |
| `calc2` | "Auto-calculation" (`layoutlm_above`) | no → **yes** | — | same (d) |
| `hidden` | "Hidden field" (`layoutlm_above`) | no → **yes** | `hidden: true`, `ask_user: false`, `skip_reason: 'hidden in the PDF'` | (c) |
| `calcsum` | "=" (`nearby_text_left`) | yes → yes | `ask_user: false`, `skip_reason: 'read-only in the PDF; calculated by the PDF from other fields'` | (c); the label is still "=" |

**Totals after the fixes**

| | Form 1 | Form 2 |
|---|---|---|
| Fields found / expected | 5 / 5 | 12 / 12 |
| Labels correct | **5** (was 3) | 10 + 1 partly (`field-specific`) + 1 wrong (`calcsum` "=", now not asked) |
| Types correct | 5 | 11 (`calcsum` `text`, not asked) |
| Answer boxes correct | 5 | 12 |
| Flagged | 3 (`Name`, `Dropdown2`, checkbox group) | 5 (checkbox group, `calc1`, `calc2`, `hidden`, `calcsum`) |
| `ask_user: false` | 0 | 2 (`hidden`, `calcsum`) |
| Null labels | **0** (was 1) | 0 |
| Wrong label and **not** flagged | **0** (was 1) | 0 (`field-specific` "Field-specific buttons" is the only printed text; still unflagged, specific to this form, not changed) |

### R2.3 Fill test

**Answers.** Fictional, by **key**, in `samples/real/sample_form_N_answers.json`:
- the read-only/calculated `calcsum` and the hidden field were left out (neither form has a signature field);
- the checkbox groups get lists.

**Commands:**
```
.venv\Scripts\python.exe fill_form.py samples\real\sample_form_1.pdf --form samples\real\sample_form_1_fields.json --answers samples\real\sample_form_1_answers.json --report samples\real\sample_form_1_fill_report.json
5 filled, 0 refused, 0 skipped. Saved samples\real\sample_form_1_filled.pdf
Filled fields marked needs_review (check these on the PDF): 3   ('Name', 'Dropdown2', the checkbox group)
Verified on the written file: 5/5 ok

.venv\Scripts\python.exe fill_form.py samples\real\sample_form_2.pdf --form samples\real\sample_form_2_fields.json --answers samples\real\sample_form_2_answers.json --report samples\real\sample_form_2_fill_report.json
skipped  'hidden'    not asked: hidden in the PDF
skipped  'calcsum'   not asked: read-only in the PDF; calculated by the PDF from other fields
10 filled, 0 refused, 2 skipped. Saved samples\real\sample_form_2_filled.pdf
Filled fields marked needs_review (check these on the PDF): 3   (the checkbox group, calc1, calc2)
Verified on the written file: 10/10 ok
```
Extra run on form 1, the editable dropdown with a typed value `"My own choice"`: filled, verified 1/1.

**My own checks** (separate from `fill_form`'s verification):
- **Originals untouched:** sha256 of both source PDFs is identical before and after.
- **Values read back with pypdf:**
  - Form 1: `Name='Chiamaka Okafor'`, `Dropdown2='Choice 3'`, `Option 1='/On'`, `Option 2='/Off'`, `Option 3='/On'`, `Name of Dependent='Emeka Okafor'`, `Age\t of Dependent='7'`.
  - Form 1 typed run: `Dropdown2='My own choice'`.
  - Form 2: every value as written: `radio='/Maybe'`; `checkbox1='/Red'`, `checkbox2='/Off'`, `checkbox3='/Blue'`; `listbox='March'`; `dropdown='Bus'`; the multiline text in full.
  - Form 2 untouched fields: `hidden` still `'This is the hidden field'`, `calcsum` still `'0'`.
- **Appearance states (`/AS`):** only the chosen radio kid (`/Maybe`) and the chosen checkboxes (`/Red`, `/Blue`, form 1 `/On` ×2) are on; all others are `/Off`.
- **Renders:** pypdfium2 with its own form renderer, 200 DPI, saved as `samples/real/sample_form_N_filled*_page1.png`. What I see:
  - **Form 1:** "Chiamaka Okafor" in the name box; "Choice 3" in the dropdown; Option 1 and Option 3 ticked, Option 2 empty; "Emeka Okafor" and "7" in the right table cells.
  - **Form 2:**
    - "Tunde Bakare", the email address, 12.50 and 7.25, "Changed by the fill test" and "Bus" each in their own box;
    - the multiline text wraps over 2 lines inside its box;
    - "Maybe" is selected, and "Red" and "Blue" are ticked;
    - the hidden field is still invisible.

**What a user would see go wrong after filling:**
1. **The sum shows "0", not 19.75.** `calcsum` is calculated by the PDF's JavaScript, and nothing in our pipeline runs it. A viewer that recalculates (e.g. Acrobat, when a field changes) may fix it; **I did not test any viewer**.
2. **The list box doesn't show the choice.** "March" is selected (read back), but the box still shows September–December, so the selection is scrolled out of view. Only the value was set, not the list's scroll position (`/TI`).
3. **The typed dropdown value is cut off on screen:** "My own ch". The box is 72 pt wide, and the PDF's auto-size font (`/DA ... 0 Tf`) was not shrunk by this renderer. The full value is in the file.
4. **`answers.json` saved with a UTF-8 BOM crashes `fill_form`** (`JSONDecodeError: Unexpected UTF-8 BOM`). I hit this by writing a file with PowerShell 5.1; Notepad can also save files with a BOM. Not fixed.

### R2.4 Verdict after the fixes

- **Reading:** both forms are read correctly enough for a demo:
  - every field is found and on its widget, and every label on form 1 is right;
  - no wrong label is left unflagged, except form 2's "Field-specific buttons", the only text printed near that box;
  - the hidden field and the calculated sum are kept but not asked.
- **Filling:** every answer is written and verified. The visible flaws are the four items in R2.3, all display or calculation side effects, not wrong values.
- **Still two demo forms only.** The above-left and rival rules are tested on generated layouts and these 2 forms; a long government form may hit cases they don't cover.

### R2.5 Open questions

1. Pages whose only widgets are buttons (form 2 pages 2–3) are still `kind: 'fillable'` (round 1, question 4, not answered yet).
2. Should `fill_form` also set the list box scroll position (`/TI`), recalculate simple sums (`AFSimple_Calculate`), or shrink text in narrow boxes? I would rather not run PDF JavaScript; a SUM/PRODUCT-only evaluator is possible but limited.
3. Should `fill_form` accept a UTF-8 BOM in `answers.json` (a one-line change: read it as `utf-8-sig`)?
4. Hidden fields: I made `fill_form` skip **every** `ask_user: false` field, hidden ones included, even when `answers.json` has a value. Your answer said this only for read-only/calculated fields. Tell me if hidden fields with an answer should be filled.
5. The shared-label rule (d) applies to flat PDFs too, so flagged counts on `Business-Name-Form.pdf` may change. I did not re-run that form.

---

# Round 1 (first test, before the fixes)

Code at commit `ceec012`, not changed. Nothing was filled and `answers.json` was not used. The round-1 output files are in commit `0438cf2`; the files now in `samples/real/` are from round 2.

**Short answer (round 1):** on these two real forms the pipeline found every fillable widget and put every answer box on the right widget (17/17). The kind (`fillable`) and all section headings are right. Labels are the weak point: **13 of 17 are right, 1 is only partly useful, 3 are wrong or missing**. Two of the bad labels are flagged; one wrong label is not flagged (confidence 0.998). Two more problems are not label problems: a hidden field and a read-only calculated field are reported as normal fields to answer.

## 1. The PDFs (step 1)

| File | Pages | Page size | Producer | Widgets |
|---|---|---|---|---|
| `samples/real/sample_form_1.pdf` | 1 | 612 × 792 pt (US Letter), no rotation, crop box = media box | Acrobat PDFMaker 15 for Word | 7 |
| `samples/real/sample_form_2.pdf` | 3 | 612 × 792 pt (US Letter) each, no rotation, crop box = media box | Microsoft Word 2013 (Apryse sample, watermarked) | 25 |

## 2. Ground truth with pypdf only (step 2)

I wrote a separate script that reads `/Annots` → `/Widget` with pypdf and follows `/Parent` for inherited keys. It uses no project code and lives in my scratchpad, not in the repo. It finds the same widget counts as the pipeline's page records (7; 21 + 3 + 1).

**Form-level facts**

| | Form 1 | Form 2 |
|---|---|---|
| Encrypted | no | no |
| XFA | no | no |
| `/NeedAppearances` | not set | not set |
| Total widgets | 7 | 25 |
| Distinct field names | 7 | 22 |
| Hierarchical names (with `.`) | none | none |
| Names with more than one widget | none | `radio` (3 kids), `reset` (2 kids) |
| Read-only fields | 0 | 1 (`calcsum`) |
| Hidden widgets (annotation flag Hidden) | 0 | 1 (`hidden`, `/F 6` = Print + Hidden) |
| Push buttons | 0 | 9 widgets / 8 fields |
| Scripts | none | `email`: validate (`/AA /V`) regex script; `calc1`, `calc2`: `AFNumber_Format/Keystroke`; `calcsum`: `AFSimple_Calculate("SUM", calc1, calc2)`, in `/CO`; `hide`/`show`: Hide actions; `reset`: ResetForm; `submit`: SubmitForm to a URL; page-2/3 buttons: GoTo/URI |

**Form 1 widgets** (rect in PDF points, origin bottom-left)

| # | Name | Type | Page | Rect | Tooltip | Flags | Options / on-state |
|---|---|---|---|---|---|---|---|
| 1 | `Name` | text | 1 | 202.5, 587.9, 412.3, 609.9 | — | — | — |
| 2 | `Dropdown2` | combo, **editable** (Ff 393216) | 1 | 71.7, 524.8, 143.7, 544.8 | — | — | Choice 1–4; value `Choice 1` |
| 3 | `Option 1` | checkbox | 1 | 73.2, 479.3, 86.2, 492.2 | `Option 1` | — | `/On` |
| 4 | `Option 2` | checkbox | 1 | 73.2, 464.6, 86.2, 477.6 | `Option 2` | — | `/On` |
| 5 | `Option 3` | checkbox | 1 | 73.2, 450.0, 86.2, 463.0 | `Option 3` | — | `/On` |
| 6 | `Name of Dependent` | text | 1 | 183.6, 401.3, 416.0, 415.3 | `Name of Dependent` | — | — |
| 7 | `Age\t of Dependent` (a tab in the name) | text | 1 | 183.6, 386.2, 416.0, 400.2 | same | — | — |

**Form 2 widgets**

| # | Name | Type | Page | Rect | Tooltip | Flags | Options / on-state / value |
|---|---|---|---|---|---|---|---|
| 1 | `required` | text | 1 | 89.5, 634.8, 292.6, 656.8 | — | Required | — |
| 2 | `email` | text | 1 | 318.3, 634.8, 521.3, 656.8 | — | — | validate script |
| 3–5 | `radio` (3 kids) | radio | 1 | x 90.7–108.7; y 568.7 / 548.1 / 527.6 | — | NoToggleToOff, Radio | `/Yes`, `/No`, `/Maybe`; value `/Off` |
| 6 | `checkbox1` | checkbox | 1 | 318.3, 568.1, 336.3, 586.1 | — | — | `/Red` |
| 7 | `checkbox2` | checkbox | 1 | 318.3, 547.6, 336.3, 565.6 | — | — | `/Yellow` |
| 8 | `checkbox3` | checkbox | 1 | 318.3, 527.0, 336.3, 545.0 | — | — | `/Blue` |
| 9 | `calc1` | text | 1 | 89.5, 456.9, 137.5, 478.9 | — | — | AFNumber format |
| 10 | `calc2` | text | 1 | 153.4, 456.9, 207.0, 478.9 | — | — | AFNumber format |
| 11 | `calcsum` | text | 1 | 224.2, 456.9, 289.7, 478.9 | — | **ReadOnly** | calculated sum; value `0` |
| 12 | `hidden` | text | 1 | 318.8, 457.4, 468.8, 479.4 | — | **widget Hidden** | value `This is the hidden field` |
| 13 | `listbox` | list (single select) | 1 | 91.3, 340.1, 292.2, 407.0 | — | — | January … December; value `December` |
| 14 | `field-specific` | text | 1 | 318.8, 383.9, 520.2, 405.9 | — | — | value `Change this text` |
| 15–17 | `hide`, `show`, `reset` | push button | 1 | y 351.6–371.6 | — | Pushbutton | — |
| 18 | `reset` (2nd kid) | push button | 1 | 230.4, 86.4, 302.4, 106.4 | — | Pushbutton | — |
| 19 | `dropdown` | combo | 1 | 90.1, 270.6, 289.9, 290.6 | — | — | Airplane, Bicycle, Boat, Bus, Car, Truck, Motorcycle; value `Airplane` |
| 20 | `multiline` | text | 1 | 90.7, 149.4, 520.2, 217.6 | — | Multiline | — |
| 21 | `submit` | push button | 1 | 314.8, 87.0, 386.8, 107.0 | — | Pushbutton | — |
| 22–24 | `prevpage2`, `nextpage2`, `google` | push button | 2 | y ≈ 628–649 | — | Pushbutton | — |
| 25 | `firstpage` | push button | 3 | 240.0, 625.0, 390.1, 645.0 | — | Pushbutton | — |

No tooltips on form 2, so every label there had to come from the printed page.

## 3. Pipeline runs (step 3)

Command from REPORT.md section 9, timed with `date` in Git Bash, stdout and stderr captured separately:
```
.venv/Scripts/python.exe layout.py samples/real/sample_form_1.pdf --fields samples/real/sample_form_1_fields.json --boxes samples/real/sample_form_1_boxes.png --ocr-out samples/real/sample_form_1_words.json
exit=0   wall seconds: 12.15
pdf_kind=fillable method=acroform+layoutlm pages: p1=fillable/pdf_text
p1 SECTION 'Sample Fillable PDF' [layoutlm_header]
p1 field                        None                                          text     acroform/none (review)
p1 first_choice                 'First Choice'                                choice   acroform/layoutlm_above
p1 check_all_that_apply         'Check all that apply'                        choice   acroform/layoutlm_above (review)
p1 name_of_dependent            'Name of Dependent'                           text     acroform/layoutlm_left
p1 age_of_dependent             'Age of Dependent'                            number   acroform/layoutlm_left
5 fields, 1 sections.

.venv/Scripts/python.exe layout.py samples/real/sample_form_2.pdf --fields samples/real/sample_form_2_fields.json --boxes samples/real/sample_form_2_boxes.png --ocr-out samples/real/sample_form_2_words.json
exit=0   wall seconds: 10.74
pdf_kind=fillable method=acroform+layoutlm pages: p1=fillable/pdf_text, p2=fillable/pdf_text, p3=fillable/pdf_text
p1 SECTION 'Sample PDF Form' [layoutlm_header]
p2 SECTION 'Sample Links' [layoutlm_header]
p3 SECTION 'Sample Links' [layoutlm_header]
p1 text_field_required          'Text field (required)'                       text     acroform/layoutlm_above
p1 email_format_validation      'Email (format validation)'                   email    acroform/layoutlm_above
p1 radio_buttons                'Radio buttons'                               choice   acroform/layoutlm_above
p1 checkboxes                   'Checkboxes'                                  choice   acroform/layoutlm_above (review)
p1 auto_calculation             'Auto-calculation'                            number   acroform/layoutlm_above
p1 auto_calculation_2           'Auto-calculation'                            number   acroform/layoutlm_above
p1 hidden_field                 'Hidden field'                                text     acroform/layoutlm_above
p1 field                        '='                                           text     acroform/nearby_text_left (review)
p1 list_box                     'List Box'                                    choice   acroform/layoutlm_above
p1 field_specific_buttons       'Field-specific buttons'                      text     acroform/layoutlm_above
p1 dropdown                     'Dropdown'                                    choice   acroform/layoutlm_above
p1 multiline_text_field         'Multiline text field'                        text     acroform/layoutlm_above
12 fields, 3 sections.
```
- **stderr:** one line per run, the model's "Loading weights … 205/205" progress bar. No warnings, no errors.
- **Speed:** both pages have a real text layer and no embedded images, so no OCR ran. The times include Python start-up and the LayoutLM load.
- **Outputs** (next to each PDF): `sample_form_N_fields.json`, `sample_form_N_boxes.png`, `sample_form_N_words.json`.

## 4. Comparison (step 4)

How I judged: I rendered every page myself with pypdfium2 at 200 DPI (separately from the pipeline) and read the printed text around each widget. Then I opened `*_boxes.png` (page 1 of form 2 cropped at full resolution) and checked each red label box and blue answer box. For the two label failures I also read the word boxes in `*_words.json` and checked them against the label search rule in `pdf_fields._nearest`.

### 4.1 `pdf_kind`
Both are `fillable`, and that is **correct**: AcroForm, no XFA, a text layer on every page.
Form 2's pages 2 and 3 are also typed `fillable`, but their only widgets are navigation buttons, so they have 0 fields. This is harmless here, but such a page is not really "fillable" (see question 4).

### 4.2 Widget count vs fields found
- **Form 1:** 7 widgets → 5 fields. The 3 lone checkboxes `Option 1–3` were merged into one independent-checkbox group (−2). This is correct: the page says "Check all that apply".
- **Form 2:** 25 widgets → 12 fields:
  - −9 push-button widgets skipped (`hide`, `show`, 2× `reset`, `submit`, `prevpage2`, `nextpage2`, `google`, `firstpage`). Correct.
  - −2: the 3 radio kids are one field `radio`. Correct.
  - −2: `checkbox1–3` merged into one independent-checkbox group. Correct: "Checkboxes" with Red/Yellow/Blue.
  - Total: 25 − 9 − 2 − 2 = 12. **No widget was lost and nothing was invented.**

### 4.3 Form 1, field by field

What the page prints (from my render): the title "Sample Fillable PDF", then an intro paragraph, then:
- "Please enter your name:" with the name box below it and to the right;
- "Please select an item from the combo/dropdown list:", then the static text "First Choice", then the dropdown;
- "Check all that apply:" over Option 1–3;
- "You can add fields within tables as well:" over a 2-row table: Name of Dependent | box, Age of Dependent | box.

| Field name | Label found (`label_source`) | Label correct? | Type | Type correct? | Answer box correct? | needs_review | Notes |
|---|---|---|---|---|---|---|---|
| `Name` | `null` (`none`), key `field` | **No.** It should be "Please enter your name" | text | yes | yes | true (sensible) | The prompt is above-left of the box and does not overlap it horizontally (label x 201–554 px, widget x 562–1145 px; left edges 361 px apart, the rule allows 68). So no rule matches it. No tooltip. |
| `Dropdown2` | "First Choice" (`layoutlm_above`, conf 0.998) | **No (probably)**. The question is "Please select an item from the combo/dropdown list" | choice, options Choice 1–4 | yes | yes | **false: a silent error** | "First Choice" is static text 1 px above the widget, so it beats the real prompt one line higher. The combo is **editable** (free text allowed); the output marks this only inside `pdf.flags`, and `choice` validation would refuse a typed value. |
| `Option 1+Option 2+Option 3` | "Check all that apply" (`layoutlm_above`) | yes | choice, `multiple: true`, options Option 1–3 | yes | yes (3 boxes on the 3 squares) | true (always set for these groups) | `pdf_field_name` is the list of 3 names, as designed. |
| `Name of Dependent` | "Name of Dependent" (`layoutlm_left`) | yes | text | yes | yes (right cell) | false | — |
| `Age\t of Dependent` | "Age of Dependent" (`layoutlm_left`) | yes | number (`label_words`) | yes (from the word "Age"; the PDF has no number format) | yes | false | The id keeps the tab from the PDF name; the label and key are clean. |

**Sections:** "Sample Fillable PDF" is correct, and there are no false sections. The blue prompts ("Please enter your name:", …) are not sections, and that is right: they are question text. "You can add fields within tables as well:" is not reported as anything. That is acceptable: it is an explanatory line, not a field.

**Boxes image:**
- Green box: on the title.
- Blue boxes: exactly on all 5 widget areas (name box, dropdown, 3 checkbox squares, 2 table cells).
- Red boxes: on "First Choice" (the wrong word), "Check all that apply:", "Name of Dependent" and "Age of Dependent".
- No red box on "Please enter your name:" or on "Please select an item…", the two missed prompts.

### 4.4 Form 2, field by field

What the page prints: "Sample PDF Form", then panels each titled with a bold label: "Text field (required)", "Email (format validation):", "Radio buttons:" (Yes/No/Maybe), "Checkboxes:" (Red/Yellow/Blue), "Auto-calculation:" (box + box = box), "Hidden field:", "List Box:", "Field-specific buttons:" (a text box and Hide/Show/Reset buttons), "Dropdown:", "Multiline text field:", then the RESET/SUBMIT buttons. Pages 2 and 3: the banner "Sample Links" and link buttons only.

| Field name | Label found (`label_source`) | Label correct? | Type | Type correct? | Answer box correct? | needs_review | Notes |
|---|---|---|---|---|---|---|---|
| `required` | "Text field (required)" (`layoutlm_above`) | yes | text | yes | yes | false | `required: true` taken from the PDF. Correct. |
| `email` | "Email (format validation)" (`layoutlm_above`) | yes | email (`label_words`) | yes | yes | false | The PDF's own email validation script (`/AA /V`) is not read; the type comes from the word "Email". Here the result is right either way. |
| `radio` | "Radio buttons" (`layoutlm_above`) | yes | choice, Yes/No/Maybe | yes | yes (3 boxes on the 3 circles) | false | — |
| `checkbox1+checkbox2+checkbox3` | "Checkboxes" (`layoutlm_above`) | yes | choice, `multiple: true`, Red/Yellow/Blue | yes | yes | true (by design) | Options come from the on-state names, which match the printed words. |
| `calc1` | "Auto-calculation" (`layoutlm_above`) | yes | number (`format_action`) | yes | yes | false | — |
| `calc2` | "Auto-calculation" (`layoutlm_above`) | yes, but the same label as `calc1` | number (`format_action`) | yes | yes | false | Correct but ambiguous: a user would be asked "Auto-calculation" twice. The key `auto_calculation_2` tells them apart only by number. |
| `calcsum` | "=" (`nearby_text_left`, conf 0.4) | **No.** It is the computed sum, not something the user should answer | text | **no**: it holds a number sum (the PDF gives it no number format, so `text` follows the stated rule) | yes | true (because of the weak label) | **Read-only and calculated** (`/C AFSimple_Calculate`). It is listed as a normal field; `read_only: true` exists only inside the `pdf` block. Per REPORT.md section 12, the fill step skips read-only fields, but the analysis does not say "don't ask". |
| `hidden` | "Hidden field" (`layoutlm_above`) | yes (that is the printed text) | text | yes | yes (on the widget's rectangle) | **false** | **The widget is hidden** (`/F 6`). In a viewer it is invisible until "Show field" is pressed. The pipeline reads the Hidden bit (`pdf_fields.py:198`) but uses it only to choose which widget to search a label for (`pdf_fields.py:381`); it is not in the output. |
| `listbox` | "List Box" (`layoutlm_above`) | yes | choice, January…December | yes | yes | false | Single-select (Ff 0). |
| `field-specific` | "Field-specific buttons" (`layoutlm_above`) | **partly**: it is the only printed text, but it names the buttons, not a question | text | yes | yes | false | Prefilled "Change this text". A user would be asked "Field-specific buttons?". |
| `dropdown` | "Dropdown" (`layoutlm_above`) | yes | choice, 7 vehicles | yes | yes | false | Not editable. Correct. |
| `multiline` | "Multiline text field" (`layoutlm_above`) | yes | text | yes | yes (the full tall box) | false | The Multiline flag is only inside `pdf.flags`. |

**Sections:**
- p1 "Sample PDF Form", p2 "Sample Links", p3 "Sample Links": all three are the real page titles. **No false sections.**
- "Page 1/2/3" in the corner is correctly not a section.
- The bold panel titles are used as labels, not sections, which is right.

**Boxes image:**
- Green boxes: on the three titles.
- Red boxes: on every panel title, plus a small red box on the "=" sign (the wrong label of `calcsum`).
- Blue boxes:
  - on every text box, the 3 radio circles and the 3 checkbox squares;
  - on the list box, the dropdown and the multiline box;
  - on the three auto-calculation boxes (including the read-only sum showing "0");
  - on the hidden field's rectangle under "Hidden field:".
- The yellow/blue buttons (Hide, Show, Reset field, RESET, SUBMIT, the page-2/3 link buttons) have no boxes, which is correct.
- Nothing is missing.

## 5. Totals

| | Form 1 | Form 2 | Both |
|---|---|---|---|
| Widgets (all) | 7 | 25 | 32 |
| Widgets that can hold an answer (no push buttons) | 7 | 16 | 23 |
| Fields found | 5 | 12 | 17 |
| Expected fields (after radio and checkbox grouping) | 5 | 12 | 17 |
| Labels correct | 3 | 10 (+1 partly: `field-specific`) | 13 (+1 partly) |
| Labels wrong / missing | 2 (`Name` null, `Dropdown2` "First Choice") | 1 (`calcsum` "=") | 3 |
| Types correct | 5 | 11 (`calcsum` text vs number) | 16 |
| Answer boxes correct | 5 | 12 | 17 |
| Flagged `needs_review` | 2 (`Name`, checkbox group) | 2 (checkbox group, `calcsum`) | 4 |
| Null labels | 1 | 0 | 1 |
| Wrong but **not** flagged | 1 (`Dropdown2`) | 1 hidden field + 1 partly useful label, all unflagged | — |
| Sections: real found / false | 1 / 0 | 3 / 0 | 4 / 0 |

## 6. Every failure, classified

| # | Failure | Class | Best explanation | Not sure about |
|---|---|---|---|---|
| F1 | Form 1 `Name`: no label (prompt "Please enter your name:" missed) | **Generic** | The label rule accepts "left" only on the same row, and "above" only with horizontal overlap or left edges within 2 text heights. Word forms often put the input box below a prompt but indented to the right. That layout matches neither rule. Seen in the word boxes: label ends at x 554, widget starts at x 562, left edges 361 px apart. | How common this layout is on your target forms. |
| F2 | Form 1 `Dropdown2`: label "First Choice" instead of the prompt one line up; **not flagged** | **Generic** (the cause), the trigger is form-specific | The nearest text above wins. Any static text between a prompt and its input (an example, a hint, a printed default) will be taken as the label. LayoutLM tagged "First Choice" as a question with 0.998 confidence, so nothing flags it. | What "First Choice" is meant to be. It may be a printed caption the author intended as a sub-label. I judged it wrong because the question the user must answer is the prompt above it. |
| F3 | Form 2 `calcsum` (read-only, calculated) listed as a field to answer, label "=" | **Generic** | The analysis keeps read-only fields as normal fields. Read-only (and calculated `/C` / `/CO`) status is only inside `pdf`; the fill step skips them later. A voice assistant using `fields` would ask the user for it. | Whether you want read-only fields kept in `fields` (marked) or left out. |
| F4 | Form 2 `hidden` (widget Hidden flag) listed as a normal, unflagged field | **Generic** | The Hidden bit is read but not exported or used for flagging. Forms that show fields only after a tick (common in government forms) will have these. | Whether the user should be asked hidden fields at all. It depends on the logic that would show them, which we do not run. |
| F5 | Form 2 `field-specific`: label "Field-specific buttons" names buttons, not a question | Specific to this demo form | It is the only printed text near the box, so the output is the best available. A real form would rarely do this. | — |
| F6 | Form 2 `calcsum` typed `text` | Generic but minor | The type comes from the field's format action or label words; a calculate script (`AFSimple_Calculate`) is not used as a hint. Becomes irrelevant if F3 is handled. | — |
| F7 | Form 1 `Dropdown2` is an **editable** combo, but typed plain `choice` | Generic, minor | `choice` validation will refuse a typed value the PDF itself accepts. Only visible in `pdf.flags.edit`. | Whether you want free text allowed for editable combos. |
| F8 | Form 2 `calc1` and `calc2` share one label | Generic, minor | One printed label for several inputs on a row (also common for date parts, phone parts). Not wrong, but the user can't tell the boxes apart. | — |
| F9 | Form 2 `email` validation script not read | Generic, no effect here | Only `/F` and `/K` (format, keystroke) scripts are read, not `/V` (validate). The type was right anyway from the label. | — |

Not failures, but worth knowing:
- Form 2's pages 2–3 count as `fillable` pages with 0 fields (buttons only).
- The id `Age\t of Dependent` contains a tab character (it is the real PDF name, so it is right as an id).

## 7. Verdict

**For a demo on forms like these: yes, with care.**
- Every real input was found, and no widget was lost or invented.
- Every answer box is on the right widget.
- Types and options are right, apart from the read-only sum.
- Section titles are right.

What a user would see go wrong:
1. **A question with no text** (form 1 name box): the assistant has nothing to ask, only the key `field`. This one is flagged.
2. **A wrong question with full confidence** (form 1 dropdown asked as "First Choice"). It is not flagged, so nothing warns the user. This is the most worrying result, because the same thing will happen whenever a hint or example line sits between a prompt and its box.
3. **Being asked for something they can't or shouldn't fill:** the calculated total ("="), and a field that is invisible in the PDF viewer ("Hidden field").
4. A slightly odd question ("Field-specific buttons") and a repeated question ("Auto-calculation" twice).

Two small demo forms are not a measure of accuracy in general. 3 bad labels out of 17 is about 18%; on long government forms the rate could be higher or lower. Neither form has hierarchical names, XFA, `/D`-only states, rotated pages or scanned pages, so those risks (REPORT.md section 13) are still untested.

## 8. Questions for you

1. **Read-only and calculated fields** (F3): keep them in `fields` with a top-level `read_only: true` / "don't ask" marker, or leave them out of `fields`?
2. **Hidden widgets** (F4): flag them (`needs_review`, `hidden: true`), leave them out, or keep them as they are?
3. **Label search** (F1, F2): should a prompt that is above-left of a box (no horizontal overlap) count as "above"? And should a short text directly above a box lose to a LayoutLM question one line higher, or at least make the field `needs_review`? I have not changed anything; these are only proposals.
4. Pages whose only widgets are buttons: keep `kind: 'fillable'`, or give them another kind?
5. Editable combo boxes (F7): accept free text, or only the listed options?
6. The two PDFs in `samples/real/` are **not committed** (you asked for JSON and PNG only). Should they be committed, given the second one carries the Apryse watermark?
7. Do you want the pypdf ground-truth script added to the repo (for example `tools/pdf_widgets.py`) so this check can be repeated on the next real forms?
