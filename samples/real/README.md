# Real fillable PDFs (not in git)

The PDFs in this folder are not committed (`samples/real/*.pdf` is in `.gitignore`). Only the outputs are.

| File | What it is | Pages | Widgets |
|---|---|---|---|
| `sample_form_1.pdf` | "Sample Fillable PDF": a short demo form made in Word with Acrobat PDFMaker 15. It has a name box, an editable dropdown, 3 checkboxes and a 2-row table. | 1 | 7 |
| `sample_form_2.pdf` | "Sample PDF Form": a demo form by Apryse (watermarked), made with Word 2013. It has a required text field, an email field, radio buttons, checkboxes, an auto-calculated sum, a hidden field, a list box, a dropdown, a multiline field, and push buttons on all 3 pages. | 3 | 25 |
| `afan.pdf` | AFAN (All Farmers Association of Nigeria) Membership Registration Form: a flat form made in CorelDRAW, with a text layer, a logo and a pale watermark picture. 25 fields, including office-use and signature lines. | 1 | 0 (flat) |

Outputs, per form (`afan_*` for afan.pdf):
- `sample_form_N_fields.json`, `sample_form_N_boxes.png`, `sample_form_N_words.json`: from `layout.py`.
- `sample_form_N_answers.json`: fictional answers, by key.
- `sample_form_N_fill_report.json`, `sample_form_N_filled_page*.png`: from `fill_form.py`. The filled PDFs are not committed either.
- `widgets_ground_truth.txt`: the independent widget list from `scripts/list_widgets.py`.

Results: `docs/real_form_test.md`.
