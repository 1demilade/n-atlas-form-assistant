"""PDF tests on generated forms (several seeds, page sizes and layouts; no real sample needed).

Fast:  .venv\\Scripts\\python.exe -m unittest tests.test_pdf -v
Slow (PaddleOCR + LayoutLM): set RUN_SLOW=1 first.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from field_types import ALLOWED_TYPES  # noqa: E402
from fill_form import fill_form  # noqa: E402
from make_test_pdfs import (make_checkbox_group_pdf, make_fillable_pdf, make_flat_pdf,  # noqa: E402
                            make_image_pdf, make_instructions_pdf)
from ocr import prepare_pages  # noqa: E402
from pdf_fields import link_fields, read_acroform  # noqa: E402
from pdf_input import describe_pdf, has_real_text, read_pdf_words  # noqa: E402

SLOW = os.environ.get('RUN_SLOW') == '1'
SEEDS = [(1, 9), (2, 8), (3, 10), (4, 7)]


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text).lower()).strip()


def to_px(rect, truth, render):
    """Ground-truth rect (PDF points, bottom-left origin) -> pixels of the page render."""
    width_pt, height_pt = truth['page_size_pt']
    sx, sy = render.shape[1] / width_pt, render.shape[0] / height_pt
    return [rect[0] * sx, (height_pt - rect[3]) * sy, rect[2] * sx, (height_pt - rect[1]) * sy]


def expected_type(truth_field, fillable):
    # A fillable text field with no format hint or type words is plain text, never 'unknown'.
    if fillable and truth_field['type'] == 'unknown' and truth_field['style'] in ('line', 'box'):
        return 'text'
    # On a flat page a combo box is an empty rectangle: its options are not visible.
    if not fillable and truth_field['style'] == 'combo':
        return 'unknown'
    # A group of options (radio or checkboxes, even Yes/No) is 'choice' on PDFs.
    if len(truth_field.get('options') or []) >= 2 and truth_field['style'] != 'combo':
        return 'choice'
    return truth_field['type']


def example_answer(truth_field):
    if truth_field.get('options'):
        return truth_field['options'][-1]
    return {'date': '01/02/2026', 'number': '42', 'email': 'a.b@example.com',
            'phone': '08030000000'}.get(truth_field['type'], 'Lagos')


class Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()


class TextLayerTests(Tmp):
    def test_real_text_rule(self):
        word = lambda t: {'text': t, 'box': [0, 0, 1, 1]}  # noqa: E731
        self.assertTrue(has_real_text([word('Name'), word('Date'), word('Address')]))
        self.assertFalse(has_real_text([word('Name'), word('Date')]))
        self.assertFalse(has_real_text([word('(cid:12)')] * 5 + [word('Name')] * 3))
        self.assertFalse(has_real_text([word('-'), word('|'), word('.'), word('_')]))

    def test_words_land_on_ink(self):
        import numpy as np
        for seed, count in SEEDS:
            with self.subTest(seed=seed):
                path = self.tmp / f'flat{seed}.pdf'
                make_flat_pdf(path, seed, count)
                render = prepare_pages(path)[0]
                gray = render.mean(axis=2)
                items = read_pdf_words(path, ocr_images=False)
                self.assertTrue(items)
                for item in items:
                    self.assertEqual(item['source'], 'pdf_text')
                    for word in item['words']:
                        x0, y0, x1, y1 = word['box']
                        self.assertTrue(0 <= x0 < x1 <= render.shape[1] and 0 <= y0 < y1 <= render.shape[0])
                        self.assertGreater((gray[y0:y1, x0:x1] < 128).mean(), 0.02, word)

    def test_boxes_follow_rotation_and_crop(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import RectangleObject
        src = self.tmp / 'flat.pdf'
        make_flat_pdf(src, 5, 10)

        def words(path):
            ws = [w for i in read_pdf_words(path, ocr_images=False) for w in i['words']]
            counts = Counter(w['text'] for w in ws)
            return {w['text']: w['box'] for w in ws if counts[w['text']] == 1}

        base = words(src)
        H, W = prepare_pages(src)[0].shape[:2]
        scale = 200 / 72
        left, bottom, right, top = 25, 60, 35, 15

        def expected(b, rotation, crop):
            w, h = W, H
            if crop:
                b = [b[0] - left * scale, b[1] - top * scale, b[2] - left * scale, b[3] - top * scale]
                w, h = W - (left + right) * scale, H - (bottom + top) * scale
            x0, y0, x1, y1 = b
            return {0: b, 90: [h - y1, x0, h - y0, x1], 180: [w - x1, h - y1, w - x0, h - y0],
                    270: [y0, w - x1, y1, w - x0]}[rotation]

        for rotation in (0, 90, 180, 270):
            for crop in (False, True):
                if not rotation and not crop:
                    continue
                with self.subTest(rotation=rotation, crop=crop):
                    writer = PdfWriter(clone_from=PdfReader(str(src)))
                    page = writer.pages[0]
                    if crop:
                        m = page.mediabox
                        page.cropbox = RectangleObject([float(m.left) + left, float(m.bottom) + bottom,
                                                        float(m.right) - right, float(m.top) - top])
                    if rotation:
                        page.rotate(rotation)
                    path = self.tmp / f'r{rotation}_{crop}.pdf'
                    writer.write(str(path))
                    got = words(path)
                    matched = 0
                    for text, box in base.items():
                        other = got.get(text) or got.get(text[::-1])  # upside-down text reads reversed
                        if other:
                            matched += 1
                            for a, b in zip(expected(box, rotation, crop), other):
                                self.assertLessEqual(abs(a - b), 1.5, (text, rotation, crop))
                    self.assertGreaterEqual(matched, 0.9 * len(base))

    def test_pale_text_is_a_watermark(self):
        """Pale grey letters are a watermark even with a dark underline drawn across them."""
        import cv2
        import numpy as np
        from pdf_input import is_pale_text
        page = np.full((200, 800, 3), 255, np.uint8)
        cv2.putText(page, 'WATERMARK', (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (215, 215, 215), 6)
        cv2.line(page, (0, 60), (800, 60), (0, 0, 0), 2)  # an answer line over the watermark
        cv2.putText(page, 'Signature', (20, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (20, 20, 20), 3)
        cv2.putText(page, 'Red text', (500, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (36, 28, 237), 3)
        self.assertTrue(is_pale_text(page, [10, 10, 520, 100]))
        self.assertFalse(is_pale_text(page, [10, 125, 300, 185]))
        self.assertFalse(is_pale_text(page, [490, 125, 790, 185]))  # coloured print is not pale

    def test_kind_detection(self):
        fillable, flat, image = self.tmp / 'a.pdf', self.tmp / 'b.pdf', self.tmp / 'c.pdf'
        make_fillable_pdf(fillable, 1, 6)
        make_flat_pdf(flat, 1, 6)
        make_image_pdf(flat, image)
        self.assertEqual(describe_pdf(fillable)['kind'], 'fillable')
        self.assertEqual(describe_pdf(flat)['kind'], 'flat')
        info = describe_pdf(image)
        self.assertEqual(info['kind'], 'flat')
        self.assertEqual(info['pages'][0]['dpi'], 200)
        import pdfplumber
        with pdfplumber.open(str(image)) as pdf:
            words = [{'text': w['text'], 'box': [0, 0, 1, 1]} for w in pdf.pages[0].extract_words()]
        self.assertFalse(has_real_text(words), 'image-only page must go to OCR')


class AcroFormTests(Tmp):
    def test_fields_match_ground_truth(self):
        for seed, count in SEEDS:
            with self.subTest(seed=seed):
                path = self.tmp / f'f{seed}.pdf'
                truth = make_fillable_pdf(path, seed, count)
                render = prepare_pages(path)[0]
                raw = {f['name']: f for f in read_acroform(path)}
                self.assertEqual(set(raw), {t['name'] for t in truth['fields']})
                for t in truth['fields']:
                    field = raw[t['name']]
                    kind = {'line': 'Tx', 'box': 'Tx', 'combo': 'Ch'}.get(t['style'], 'Btn')
                    self.assertEqual(field['pdf_type'], kind, t)
                    self.assertEqual(field['flags']['required'], bool(t.get('required')), t)
                    self.assertEqual(field['tooltip'], t.get('tooltip'))
                    self.assertEqual(len(field['widgets']), len(t['rects']))
                    for widget, rect in zip(field['widgets'], t['rects']):
                        for a, b in zip(widget['box'], to_px(rect, truth, render)):
                            self.assertLessEqual(abs(a - b), 1, t)
                    if t['style'] == 'combo':
                        self.assertEqual(field['option_texts'], t['options'])

    def test_labels_and_types_without_layoutlm(self):
        """Fallback linking (tooltip, nearby text) must already find the right label."""
        for seed, count in SEEDS:
            with self.subTest(seed=seed):
                path = self.tmp / f'f{seed}.pdf'
                truth = make_fillable_pdf(path, seed, count)
                items = read_pdf_words(path, ocr_images=False)
                fields, _ = link_fields(read_acroform(path), items, prepare_pages(path), use_layoutlm=False)
                by_id = {f['id']: f for f in fields}
                for t in truth['fields']:
                    field = by_id[t['name']]
                    self.assertEqual(norm(field['label']), norm(t['label']), (field['label_source'], t))
                    self.assertEqual(field['pdf_field_name'], t['name'])
                    self.assertEqual(field['required'], bool(t.get('required')), t)
                    self.assertEqual(field['type'], expected_type(t, True), t)
                    self.assertIn(field['type'], ALLOWED_TYPES)
                    self.assertTrue(field['needs_review'], 'fallback labels must be flagged')
                    if t.get('options'):
                        self.assertEqual(field['options'], t['options'])

    def test_field_name_is_never_a_label(self):
        """A widget with no question, tooltip or nearby text gets no label, not 'Text1'."""
        import numpy as np
        from pdf_fields import FLAG_BITS
        raw = {'name': 'Text1', 'pdf_type': 'Tx', 'flags': {k: False for k in FLAG_BITS},
               'flags_value': 0, 'tooltip': None, 'max_length': None, 'default_value': None,
               'value': None, 'option_texts': [], 'option_values': [], 'format_script': '',
               'widgets': [{'page': 1, 'box': [100, 100, 300, 140], 'rect_pt': [0, 0, 1, 1],
                            'export_value': None, 'hidden': False}]}
        far = {'text': 'Text far away', 'box': [1000, 2000, 1200, 2030], 'score': 1.0, 'page': 1}
        fields, _ = link_fields([raw], [far], [np.full((2339, 1655, 3), 255, np.uint8)],
                                use_layoutlm=False)
        self.assertIsNone(fields[0]['label'])
        self.assertIsNone(fields[0]['label_box'])
        self.assertEqual(fields[0]['label_source'], 'none')
        self.assertTrue(fields[0]['needs_review'])


def _fillable_form(path):
    items = read_pdf_words(path, ocr_images=False)
    fields, _ = link_fields(read_acroform(path), items, prepare_pages(path), use_layoutlm=False)
    return {'form': {'pdf_kind': 'fillable', 'pages': describe_pdf(path)['pages']},
            'fields': fields, 'sections': []}


class FillTests(Tmp):
    def test_fillable_round_trip(self):
        from pypdf import PdfReader
        for seed, count in SEEDS:
            with self.subTest(seed=seed):
                path, out = self.tmp / f'f{seed}.pdf', self.tmp / f'o{seed}.pdf'
                truth = make_fillable_pdf(path, seed, count)
                form = _fillable_form(path)
                answers = {t['name']: example_answer(t) for t in truth['fields']}
                report = fill_form(path, form, answers, out)
                self.assertTrue(all(r['status'] == 'filled' for r in report), report)
                for r in report:
                    self.assertEqual(r['verified'], {'value_read_back': True, 'ink_in_box': True}, r)
                values = {k: v.get('/V') for k, v in PdfReader(str(out)).get_fields().items()}
                for t in truth['fields']:
                    field = next(f for f in form['fields'] if f['id'] == t['name'])
                    if t['style'] in ('line', 'box', 'combo'):
                        self.assertEqual(str(values[t['name']]), answers[t['name']])
                    else:  # radio: the export value of the chosen option
                        index = t['options'].index(answers[t['name']])
                        self.assertEqual(str(values[t['name']]), '/' + field['pdf']['option_values'][index])

    def test_fillable_skips_with_reasons(self):
        path, out = self.tmp / 'f.pdf', self.tmp / 'o.pdf'
        truth = make_fillable_pdf(path, 3, 10)
        form = _fillable_form(path)
        text = next(f for f in form['fields'] if f['pdf']['field_type'] == 'Tx' and f['type'] == 'text')
        text['pdf']['max_length'] = 2
        choice = next(f for f in form['fields'] if f['options'])
        report = {r['id']: r for r in fill_form(path, form, {
            text['id']: 'too long', choice['id']: 'not an option', 'no_such_field': 'x'}, out)}
        self.assertIn('max_length', report[text['id']]['reason'])
        self.assertIn('matches no option', report[choice['id']]['reason'])
        self.assertEqual(report['no_such_field']['reason'], 'no field with this id')
        self.assertEqual(len(truth['fields']) + 1, len(report))

    def test_check_value(self):
        from field_types import check_value
        for kind, good, bad in [('number', ['42', '-3.5', '1,200', '15%'], ['forty', '12a', '']),
                                ('date', ['01/02/2026', '2026-02-01', '1 February 2026', 'Feb 1, 2026'],
                                 ['31/31/2026', 'tomorrow', '2026']),
                                ('email', ['a.b@example.com'], ['a.b@', 'ab.com', 'a b@x.com']),
                                ('phone', ['08030000000', '+234 803 000 0000', '(01) 234-5678'],
                                 ['123', 'call me', '+234 803 000 0000 0000 00'])]:
            for value in good:
                self.assertIsNone(check_value(kind, value), (kind, value))
            for value in bad:
                self.assertIsNotNone(check_value(kind, value), (kind, value))
        self.assertIsNone(check_value('text', 'anything'))
        self.assertIsNone(check_value('unknown', ''))

    def test_invalid_values_are_refused(self):
        from pypdf import PdfReader
        found = 0
        for seed, count in SEEDS:
            path, out = self.tmp / f'f{seed}.pdf', self.tmp / f'o{seed}.pdf'
            make_fillable_pdf(path, seed, count)
            form = _fillable_form(path)
            typed = [f for f in form['fields'] if f['pdf']['field_type'] == 'Tx'
                     and f['type'] in ('number', 'date', 'email', 'phone')]
            if not typed:
                continue
            found += len(typed)
            report = {r['id']: r for r in fill_form(path, form, {f['id']: 'not valid' for f in typed}, out)}
            values = PdfReader(str(out)).get_fields()
            for field in typed:
                self.assertEqual(report[field['id']]['status'], 'refused', report[field['id']])
                self.assertIn(field['type'], report[field['id']]['reason'])
                self.assertNotEqual(str(values[field['pdf_field_name']].get('/V')), 'not valid')
        self.assertGreater(found, 0, 'no typed text field in the generated forms')

    def test_flat_invalid_values_are_refused(self):
        import pdfplumber
        path, out = self.tmp / 'b.pdf', self.tmp / 'o.pdf'
        truth = make_flat_pdf(path, 3, 10)
        render = prepare_pages(path)[0]
        fields, answers, expected = [], {}, {}
        for n, t in enumerate(truth['fields']):
            field = {'id': f'f{n}', 'label': t['label'], 'page': 1, 'type': t['type'],
                     'options': t.get('options', [])}
            if t['style'] in ('line', 'box', 'combo'):
                field.update(answer_box=to_px(t['rects'][0], truth, render), answer_method='box')
            else:
                boxes = [to_px(r, truth, render) for r in t['rects']]
                field.update(answer_box=boxes[0], answer_method='checkboxes', option_boxes=boxes)
            fields.append(field)
            if t['type'] in ('number', 'date', 'email', 'phone') or t.get('options'):
                answers[field['id']], expected[field['id']] = 'not valid', 'refused'
            else:
                answers[field['id']], expected[field['id']] = 'Lagos', 'filled'
        self.assertIn('refused', expected.values())
        form = {'form': {'pages': describe_pdf(path)['pages']}, 'fields': fields, 'sections': []}
        report = {r['id']: r for r in fill_form(path, form, answers, out)}
        for fid, status in expected.items():
            self.assertEqual(report[fid]['status'], status, report[fid])
        with pdfplumber.open(str(out)) as pdf:
            self.assertNotIn('valid', pdf.pages[0].extract_text())  # nothing drawn for refusals
        # yes_no without printed options takes yes/no words only
        field = dict(fields[0], type='yes_no', options=[], answer_method='box')
        report = fill_form(path, [field], {field['id']: 'perhaps'}, out)
        self.assertEqual(report[0]['status'], 'refused')
        self.assertEqual(fill_form(path, [field], {field['id']: 'Yes'}, out)[0]['status'], 'filled')

    def test_on_states_come_from_the_pdf(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject,
                                   NameObject, NumberObject, TextStringObject)
        path, out = self.tmp / 'box.pdf', self.tmp / 'o.pdf'
        writer = PdfWriter()
        page = writer.add_blank_page(300, 200)
        streams = {}
        for state in ('/Agreed', '/Off'):
            stream = DecodedStreamObject()
            stream.set_data(b'0 0 m 12 12 l S' if state != '/Off' else b'')
            stream.update({NameObject('/Type'): NameObject('/XObject'),
                           NameObject('/Subtype'): NameObject('/Form'),
                           NameObject('/BBox'): ArrayObject([FloatObject(v) for v in (0, 0, 12, 12)])})
            streams[NameObject(state)] = writer._add_object(stream)
        widget = DictionaryObject({
            NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'),
            NameObject('/FT'): NameObject('/Btn'), NameObject('/T'): TextStringObject('agree'),
            NameObject('/Rect'): ArrayObject([FloatObject(v) for v in (50, 100, 62, 112)]),
            NameObject('/F'): NumberObject(4), NameObject('/AS'): NameObject('/Off'),
            NameObject('/AP'): DictionaryObject({NameObject('/N'): DictionaryObject(streams)})})
        ref = writer._add_object(widget)
        page[NameObject('/Annots')] = ArrayObject([ref])
        label = DecodedStreamObject()  # printed label, so the page has a text layer (no OCR)
        label.set_data(b'BT /F1 10 Tf 70 102 Td (I agree to the terms) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(label)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): DictionaryObject({
                NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                NameObject('/BaseFont'): NameObject('/Helvetica')})})})
        writer._root_object[NameObject('/AcroForm')] = DictionaryObject(
            {NameObject('/Fields'): ArrayObject([ref])})
        writer.write(str(path))
        form = _fillable_form(path)
        field = form['fields'][0]
        self.assertEqual(field['type'], 'yes_no')  # a lone checkbox
        field['pdf']['widgets'][0]['export_value'] = 'Yes'  # a wrong JSON must not matter
        report = fill_form(path, form, {field['id']: 'yes'}, out)
        self.assertEqual(report[0]['status'], 'filled', report)
        self.assertEqual(str(PdfReader(str(out)).get_fields()['agree']['/V']), '/Agreed')

        radio_path = self.tmp / 'r.pdf'
        truth = make_fillable_pdf(radio_path, 1, 9)
        form = _fillable_form(radio_path)
        radio = next(f for f in form['fields'] if f['pdf']['field_type'] == 'Btn')
        radio['pdf']['option_values'][0] = 'NotInThePdf'
        report = {r['id']: r for r in fill_form(radio_path, form, {radio['id']: radio['options'][0]}, out)}
        self.assertIn('is not in the PDF', report[radio['id']]['reason'])
        self.assertEqual(len(report), len(truth['fields']))

    def test_filled_flagged_fields_are_listed(self):
        path, out = self.tmp / 'f.pdf', self.tmp / 'o.pdf'
        make_fillable_pdf(path, 3, 10)
        form = _fillable_form(path)  # no LayoutLM here: every label is a flagged fallback
        texts = [f for f in form['fields'] if f['pdf']['field_type'] == 'Tx' and f['type'] == 'text']
        texts[1]['needs_review'] = False
        report = {r['id']: r for r in fill_form(path, form, {texts[0]['id']: 'A', texts[1]['id']: 'B'}, out)}
        self.assertTrue(report[texts[0]['id']]['needs_review'])
        self.assertEqual(report[texts[0]['id']]['label'], texts[0]['label'])
        self.assertNotIn('needs_review', report[texts[1]['id']])
        flagged_unanswered = next(f for f in form['fields'] if f['needs_review'] and f is not texts[0])
        self.assertEqual(report[flagged_unanswered['id']]['status'], 'skipped')  # no answer, not filled
        self.assertNotIn('needs_review', report[flagged_unanswered['id']])

    def test_verification_catches_missing_ink(self):
        from fill_form import _verify
        path = self.tmp / 'b.pdf'
        make_flat_pdf(path, 1, 6)
        report = [{'id': 'x', 'status': 'filled', 'value': 'v',
                   '_check': {'page': 1, 'box': [0, 0, 40, 40], 'ink': True}}]
        _verify(path, path, report)  # nothing was drawn: same file before and after
        self.assertEqual(report[0]['verified'], {'ink_in_box': False})
        self.assertIn('verification failed', report[0]['warning'])

    def test_never_overwrites_the_original(self):
        path = self.tmp / 'my form.pdf'
        make_fillable_pdf(path, 1, 6)
        before = path.read_bytes()
        form = _fillable_form(path)
        answer = {form['fields'][0]['id']: 'x'}
        with self.assertRaises(ValueError):
            fill_form(path, form, answer, path)
        with self.assertRaises(ValueError):  # same file through another spelling
            fill_form(path, form, answer, str(self.tmp / '.' / 'my form.pdf'))
        self.assertEqual(path.read_bytes(), before)
        fill_form(path, form, answer, None)
        self.assertTrue((self.tmp / 'my form_filled.pdf').is_file())
        self.assertEqual(path.read_bytes(), before)

    def test_fields_list_or_form_object(self):
        """fill_form(pdf_path, fields, ...) takes the bare fields list too (page sizes from a render)."""
        import pdfplumber
        path = self.tmp / 'b.pdf'
        truth = make_flat_pdf(path, 2, 8)
        render = prepare_pages(path)[0]
        fields = [{'id': f'f{n}', 'label': t['label'], 'page': 1, 'options': [], 'answer_method': 'box',
                   'answer_box': to_px(t['rects'][0], truth, render)}
                  for n, t in enumerate(truth['fields']) if t['style'] in ('line', 'box')]
        answers = {f['id']: 'Lagos' for f in fields}
        form = {'form': {'pages': describe_pdf(path)['pages']}, 'fields': fields, 'sections': []}
        words = []
        for name, given in (('obj.pdf', form), ('list.pdf', fields)):
            report = fill_form(path, given, answers, self.tmp / name)
            self.assertTrue(all(r['status'] == 'filled' for r in report), report)
            with pdfplumber.open(str(self.tmp / name)) as pdf:
                words.append([(w['text'], round(w['x0'], 1), round(w['top'], 1))
                              for w in pdf.pages[0].extract_words()])
        self.assertEqual(words[0], words[1])

    def test_flat_text_and_crosses_land_in_place(self):
        import numpy as np
        import pdfplumber
        for seed, count in SEEDS:
            with self.subTest(seed=seed):
                path, out = self.tmp / f'b{seed}.pdf', self.tmp / f'o{seed}.pdf'
                truth = make_flat_pdf(path, seed, count)
                render = prepare_pages(path)[0]
                fields, answers = [], {}
                for number, t in enumerate(truth['fields']):
                    field = {'id': f'f{number}', 'label': t['label'], 'page': 1, 'options': t.get('options', [])}
                    if t['style'] in ('line', 'box', 'combo'):
                        field.update(answer_box=to_px(t['rects'][0], truth, render), answer_method='box')
                    else:
                        boxes = [to_px(r, truth, render) for r in t['rects']]
                        field.update(answer_box=boxes[0], answer_method='checkboxes', option_boxes=boxes)
                    fields.append(field)
                    answers[field['id']] = example_answer(t)
                form = {'form': {'pdf_kind': 'flat_text', 'pages': describe_pdf(path)['pages']},
                        'fields': fields, 'sections': []}
                report = fill_form(path, form, answers, out)
                self.assertTrue(all(r['status'] == 'filled' for r in report), report)
                for r in report:
                    self.assertEqual(r['verified'], {'ink_in_box': True}, r)

                before = render.mean(axis=2)
                after = prepare_pages(out)[0].mean(axis=2)
                with pdfplumber.open(str(out)) as pdf:
                    page = pdf.pages[0]
                    words = page.extract_words()
                    sx = render.shape[1] / float(page.width)
                for field in fields:
                    if field['answer_method'] == 'checkboxes':
                        index = field['options'].index(answers[field['id']])
                        for i, box in enumerate(field['option_boxes']):
                            x0, y0, x1, y1 = [int(round(v)) for v in box]
                            inner = slice(y0 + 4, y1 - 4), slice(x0 + 4, x1 - 4)
                            added = ((after[inner] < 128) & (before[inner] >= 128)).mean()
                            if i == index:
                                self.assertGreater(added, 0.03, f"no X in {field['options'][i]}")
                            else:
                                self.assertEqual(added, 0, f"X in wrong box {field['options'][i]}")
                        continue
                    x0, y0, x1, y1 = field['answer_box']
                    inside = [w['text'] for w in words
                              if x0 - 2 <= w['x0'] * sx and w['x1'] * sx <= x1 + 2
                              and y0 - 2 <= w['top'] * sx and w['bottom'] * sx <= y1 + 2]
                    self.assertEqual(' '.join(inside), answers[field['id']], field['label'])


def _link(path, tag_all_as_questions=False):
    """Fields of a generated fillable PDF. tag_all_as_questions: stand-in for LayoutLM that tags
    every printed line as a question (as the model did on real forms), so the question tier of
    the label linking is tested without loading the model."""
    items = read_pdf_words(path, ocr_images=False)
    entities = None
    if tag_all_as_questions:
        entities = [{'kind': 'question', 'text': i['text'], 'box': i['box'], 'page': i['page'],
                     'confidence': 0.99} for i in items]
    fields, _ = link_fields(read_acroform(path), items, prepare_pages(path),
                            use_layoutlm=tag_all_as_questions, entities=entities)
    return {f['id']: f for f in fields}


class LabelLinkingTests(Tmp):
    def test_prompt_beats_a_short_line_above_the_input(self):
        """A hint/example line between a prompt and its input is not the label. The line ending
        with ':' or '?' wins, and a field with two lines about as close is reviewed."""
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'rivals.pdf'
        make_widget_pdf(path, [
            (56, 700, 'Please choose your state of origin:'), (56, 684, 'First option'),
            (56, 600, 'Which state are you from?'), (56, 584, 'Example: Lagos'),
            (56, 500, 'Home town'), (56, 484, 'Write in full'),
            (56, 400, 'Surname:'),
        ], [
            {'name': 'Dropdown1', 'kind': 'combo', 'rect': [56, 662, 200, 678], 'options': ['A', 'B']},
            {'name': 'Text1', 'kind': 'text', 'rect': [56, 562, 300, 578]},
            {'name': 'Text2', 'kind': 'text', 'rect': [56, 462, 300, 478]},
            {'name': 'Text3', 'kind': 'text', 'rect': [56, 378, 300, 394]},
        ])
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields = _link(path, tagged)
                drop, state, town, surname = (fields[n] for n in ('Dropdown1', 'Text1', 'Text2', 'Text3'))
                self.assertEqual(drop['label'], 'Please choose your state of origin')
                self.assertEqual(drop['label_alternatives'], ['First option'])
                self.assertTrue(drop['needs_review'])
                self.assertEqual(state['label'], 'Which state are you from?')
                self.assertEqual(state['label_alternatives'], ['Example: Lagos'])
                self.assertTrue(state['needs_review'])
                # Neither line ends like a prompt: the nearest stays, but the choice is not clear.
                self.assertEqual(town['label'], 'Write in full')
                self.assertEqual(town['label_alternatives'], ['Home town'])
                self.assertTrue(town['needs_review'])
                self.assertEqual(surname['label'], 'Surname')
                self.assertEqual(surname['label_alternatives'], [])
                if tagged:  # a lone LayoutLM question with no rival is not flagged
                    self.assertEqual(state['label_source'], 'layoutlm_above')
                    self.assertEqual(surname['label_source'], 'layoutlm_above')
                    self.assertFalse(surname['needs_review'])

    def test_prompt_above_left_of_the_input(self):
        """A prompt above the input that ends before the input starts is its label (flagged),
        but only when nothing matches on the left or above."""
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'above_left.pdf'
        make_widget_pdf(path, [
            (56, 700, 'Please enter your full name:'),
            (56, 600, 'Your occupation:'),
            (56, 500, 'Notes about you:'), (56, 480, 'Town:'),
            (56, 400, 'Mother maiden name:'),
        ], [
            {'name': 'Name', 'kind': 'text', 'rect': [200, 674, 450, 690]},
            {'name': 'Job', 'kind': 'text', 'rect': [145, 574, 450, 590]},
            {'name': 'Town', 'kind': 'text', 'rect': [145, 476, 450, 492]},
            {'name': 'Far', 'kind': 'text', 'rect': [420, 374, 560, 390]},  # far right of its prompt
        ])
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields = _link(path, tagged)
                name, job, town, far = (fields[n] for n in ('Name', 'Job', 'Town', 'Far'))
                self.assertEqual(name['label'], 'Please enter your full name')
                # 'Please ...' lines are not LayoutLM label candidates (instructions), so plain text.
                self.assertEqual(name['label_source'], 'nearby_text_above_left')
                self.assertTrue(name['needs_review'])
                self.assertEqual(job['label'], 'Your occupation')
                self.assertEqual(job['label_source'],
                                 'layoutlm_above_left' if tagged else 'nearby_text_above_left')
                self.assertTrue(job['needs_review'])
                self.assertEqual(town['label'], 'Town')  # same row on the left still wins
                self.assertEqual(town['label_source'], 'layoutlm_left' if tagged else 'nearby_text_left')
                self.assertIsNone(far['label'])
                self.assertEqual(far['label_source'], 'none')


def _flat_form(path, tag_all_as_questions=False):
    """(fields, sections) of a generated flat PDF. tag_all_as_questions: stand-in for LayoutLM
    that tags every printed line as a question; otherwise the rules path."""
    from layout import find_fields_and_sections
    items = read_pdf_words(path, ocr_images=False)
    entities = None
    if tag_all_as_questions:
        entities = [{'kind': 'question', 'text': i['text'], 'box': i['box'], 'page': i['page'],
                     'confidence': 0.99} for i in items]
    return find_fields_and_sections(items, path, 'layoutlm' if tag_all_as_questions else 'rules',
                                    clean=False, entities=entities, checkbox_rule=True)


def _underlined(rows, size=10, x=56, right=540):
    """texts and lines for make_widget_pdf: each label with an underline starting right after it."""
    from make_test_pdfs import _text_width
    texts = [(x, y, label) for label, y in rows]
    lines = [(x + _text_width(label, size) + 6, y - 2, right) for label, y in rows]
    return texts, lines


class FlatLabelTests(Tmp):
    def test_item_numbers_are_not_part_of_labels(self):
        """'17. Have you ever ...?' is the question 'Have you ever ...?' (so it is typed yes_no);
        '(a)' and '10.' are dropped from labels and ids."""
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'numbered.pdf'
        texts, lines = _underlined([('1. Full name:', 700), ('10. Other commodity:', 670),
                                    ('17. Have you ever taken insurance on your farm?', 640),
                                    ('(a) How long:', 610)])
        texts.append((56, 740, 'Registration form for the members of our farmers club'))
        make_widget_pdf(path, texts, [], lines=lines)
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields = {f['label']: f for f in _flat_form(path, tagged)[0]}
                for label in ('Full name', 'Other commodity', 'How long'):
                    self.assertIn(label, fields)
                    self.assertFalse(re.match(r'\d', fields[label]['id']), fields[label]['id'])
                insurance = fields['Have you ever taken insurance on your farm?']
                self.assertEqual(insurance['type'], 'yes_no')
                self.assertTrue(insurance['id'].startswith('have_you_ever_taken'), insurance['id'])


    def test_wrapped_question_with_a_capital_second_line(self):
        """A question whose first line stops mid-sentence continues on the next line even when
        that line starts with a capital; it is one field, answered on the line after its end.
        Rows are spaced exactly like the wrapped lines, so only the unfinished text tells."""
        from make_test_pdfs import make_widget_pdf, _text_width
        path = self.tmp / 'wrapped.pdf'
        texts, lines = _underlined([('11. Full name:', 718), ('Other (Specify):', 682),
                                    ('13. Size of farm:', 664), ('14. State:', 646)])
        texts[1] = (68, 682, 'Other (Specify):')  # indented under the text, not the number
        lines[1] = (68 + _text_width('Other (Specify):', 10) + 6, 680, 540)
        texts.append((56, 700, '12. Are you a service provider (Agric input, Dealer, Processor,'))
        texts.append((56, 750, 'Registration form for the members of our farmers club'))
        make_widget_pdf(path, texts, [], lines=lines)
        question = 'Are you a service provider (Agric input, Dealer, Processor, Other (Specify)'
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields = {f['label']: f for f in _flat_form(path, tagged)[0]}
                self.assertIn(question, fields, list(fields))
                self.assertNotIn('Other (Specify)', fields)
                field = fields[question]
                self.assertEqual(field['answer_method'], 'underline')
                scale = 200 / 72
                self.assertAlmostEqual(field['answer_box'][3], (792 - 680) * scale, delta=6)
                for label in ('Full name', 'Size of farm', 'State'):  # finished lines stay apart
                    self.assertIn(label, fields)


    def test_label_printed_under_its_line(self):
        """'Signature' and 'Date' printed under their lines get those lines; a question with no
        line of its own does not take the underline of the row above."""
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'under.pdf'
        texts, lines = _underlined([('Full name:', 700), ('Bank details:', 670)])
        texts += [(56, 750, 'Registration form for the members of our farmers club'),
                  (56, 650, 'Have you ever been abroad?'),
                  (100, 590, 'Signature'), (410, 590, 'Date')]
        lines += [(56, 600, 220), (350, 600, 500)]
        make_widget_pdf(path, texts, [], lines=lines)
        scale = 200 / 72
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields = {f['label']: f for f in _flat_form(path, tagged)[0]}
                for label, (x0, x1) in (('Signature', (56, 220)), ('Date', (350, 500))):
                    field = fields[label]
                    self.assertEqual(field['answer_method'], 'line_above', field)
                    box = field['answer_box']
                    self.assertAlmostEqual(box[0], x0 * scale, delta=6)
                    self.assertAlmostEqual(box[2], x1 * scale, delta=6)
                    self.assertAlmostEqual(box[3], (792 - 600) * scale, delta=6)
                    self.assertFalse(field['needs_review'] and field['answer_method'] != 'line_above')
                self.assertNotEqual(fields['Have you ever been abroad?']['answer_method'], 'line_above')
                self.assertEqual(fields['Bank details']['answer_method'], 'underline')


    def test_answer_ruled_over_several_lines(self):
        """A blank ruled line under an answer line continues it (one area, filled line by line);
        a ruled line with a label on its row is the next field, however close."""
        import pdfplumber
        from make_test_pdfs import make_widget_pdf
        path, out = self.tmp / 'lines.pdf', self.tmp / 'lines_out.pdf'
        texts, lines = _underlined([('Address:', 700), ('Ward:', 680),
                                    ('Input uses - types, quantities and sources:', 640), ('Next of kin:', 598)])
        texts.append((56, 750, 'Registration form for the members of our farmers club'))
        lines[2] = (250, 638, 540)  # (the label really ends at about 243 pt)
        lines.append((68, 620, 540))  # the blank second line of 'Input uses'
        make_widget_pdf(path, texts, [], lines=lines)
        scale = 200 / 72
        for tagged in (True, False):
            with self.subTest(layoutlm_questions=tagged):
                fields, _ = _flat_form(path, tagged)
                by_label = {f['label']: f for f in fields}
                uses = by_label['Input uses - types, quantities and sources']
                self.assertEqual(len(uses['answer_lines']), 2)
                self.assertAlmostEqual(uses['answer_box'][3], (792 - 620) * scale, delta=6)
                self.assertAlmostEqual(uses['answer_box'][0], 68 * scale, delta=6)
                for label in ('Address', 'Ward', 'Next of kin'):
                    self.assertEqual(by_label[label]['answer_lines'], [], label)
                    self.assertEqual(by_label[label]['answer_method'], 'underline', label)
        answer = 'Fertiliser, two bags a season from the cooperative shop and seeds from the state farm'
        form = {'form': {'pages': describe_pdf(path)['pages']}, 'fields': fields, 'sections': []}
        report = {r['id']: r for r in fill_form(path, form, {uses['id']: answer, by_label['Address']['id']: 'Lagos'}, out)}
        self.assertEqual(report[uses['id']]['status'], 'filled')
        self.assertNotIn('warning', report[uses['id']])
        def page_words(pdf_path):
            with pdfplumber.open(str(pdf_path)) as pdf:
                return pdf.pages[0].extract_words()
        printed = {(w['text'], round(w['x0']), round(w['top'])) for w in page_words(path)}
        words = [w for w in page_words(out) if (w['text'], round(w['x0']), round(w['top'])) not in printed
                 and w['text'] != 'Lagos']
        rows = {round(792 - w['bottom']) for w in words}  # bottoms in PDF points
        self.assertEqual(' '.join(w['text'] for w in sorted(words, key=lambda w: (round(w['top']), w['x0']))), answer)
        self.assertTrue(any(abs(r - 638) <= 4 for r in rows) and any(abs(r - 620) <= 4 for r in rows), rows)


    def test_capital_headings_are_sections(self):
        """A heading printed in capitals that the model leaves untagged ('other') is a section,
        so the fields under it are assigned to it, not to the heading before."""
        from layout import find_fields_and_sections
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'caps.pdf'
        texts, lines = _underlined([('Full name:', 700), ('Home town:', 680), ('Remarks:', 610)])
        texts += [(56, 750, 'Registration form for the members of our farmers club'),
                  (56, 720, 'PERSONAL DETAILS'), (100, 640, 'RECOMMENDATION BY THE LOCAL COORDINATOR')]
        make_widget_pdf(path, texts, [], lines=lines)
        items = read_pdf_words(path, ocr_images=False)
        model_like = [{'kind': 'other' if i['text'].isupper() or i['text'].startswith('Registration')
                       else 'question', 'text': i['text'], 'box': i['box'], 'page': 1, 'confidence': 0.99}
                      for i in items]
        for mode, entities in (('layoutlm', model_like), ('rules', None)):
            with self.subTest(mode=mode):
                fields, sections = find_fields_and_sections(items, path, mode, clean=False,
                                                            entities=entities, checkbox_rule=True)
                titles = {s['id']: s['title'] for s in sections}
                self.assertIn('PERSONAL DETAILS', titles.values())
                self.assertIn('RECOMMENDATION BY THE LOCAL COORDINATOR', titles.values())
                by_label = {f['label']: f for f in fields}
                self.assertEqual(titles[by_label['Full name']['section']], 'PERSONAL DETAILS')
                self.assertEqual(titles[by_label['Remarks']['section']], 'RECOMMENDATION BY THE LOCAL COORDINATOR')
                self.assertNotIn('PERSONAL DETAILS', by_label)


    def test_printed_answer_is_not_a_field_on_a_blank_form(self):
        """On a blank PDF form, a label whose only 'answer' is printed text with nothing drawn
        there (a letterhead address) is not a field; a placeholder printed on a line is."""
        from layout import find_fields_and_sections
        from make_test_pdfs import make_widget_pdf, _text_width
        path = self.tmp / 'letterhead.pdf'
        texts = [(56, 760, 'SUNRISE FARMERS COOPERATIVE SOCIETY'),
                 (120, 740, 'Head Office:'), (190, 740, '12 Market Road, Ibadan, Oyo State'),
                 (56, 700, 'Date of birth:'), (150, 700, 'DD/MM/YYYY'), (56, 670, 'Full name:')]
        lines = [(56 + _text_width('Date of birth:', 10) + 6, 698, 540),
                 (56 + _text_width('Full name:', 10) + 6, 668, 540)]
        make_widget_pdf(path, texts, [], lines=lines)
        items = read_pdf_words(path, ocr_images=False)
        kinds = {'SUNRISE FARMERS COOPERATIVE SOCIETY': 'header', '12 Market Road, Ibadan, Oyo State': 'answer',
                 'DD/MM/YYYY': 'answer'}
        entities = [{'kind': kinds.get(i['text'], 'question'), 'text': i['text'], 'box': i['box'],
                     'page': 1, 'confidence': 0.99} for i in items]
        notes = []
        fields, _ = find_fields_and_sections(items, path, 'layoutlm', clean=False, entities=entities,
                                             checkbox_rule=True, blank_form=True, notes=notes)
        labels = [f['label'] for f in fields]
        self.assertNotIn('Head Office', labels)
        self.assertIn('Date of birth', labels)  # its 'answer' is a placeholder printed on a line
        self.assertIn('Full name', labels)
        self.assertTrue(any('Head Office' in n and 'printed' in n for n in notes), notes)
        # Photos of filled-in forms keep LayoutLM answers as answers.
        fields, _ = find_fields_and_sections(items, path, 'layoutlm', clean=False, entities=entities)
        self.assertIn('Head Office', [f['label'] for f in fields])


    def test_official_use_fields_are_not_asked(self):
        """Fields under a 'FOR OFFICIAL USE ONLY' heading, or labelled 'Endorsed by ...', are kept
        but not asked (and not filled); the applicant's own fields are asked."""
        from layout import analyse_form
        from make_test_pdfs import make_widget_pdf
        path, out = self.tmp / 'office.pdf', self.tmp / 'office_out.pdf'
        texts, lines = _underlined([('Full name:', 700), ('Endorsed by village head:', 680),
                                    ('Received by:', 620), ('Remarks:', 600)])
        texts += [(56, 760, 'Registration form for the members of our farmers club'),
                  (56, 730, 'PERSONAL DETAILS'), (56, 650, 'FOR OFFICIAL USE ONLY')]
        make_widget_pdf(path, texts, [], lines=lines)
        form = analyse_form(str(path), read_pdf_words(path, ocr_images=False), method='rules')
        by_label = {f['label']: f for f in form['fields']}
        self.assertTrue(by_label['Full name']['ask_user'])
        for label, why in (('Endorsed by village head', 'Endorsed by village head'),
                           ('Received by', 'FOR OFFICIAL USE ONLY'), ('Remarks', 'FOR OFFICIAL USE ONLY')):
            field = by_label[label]
            self.assertFalse(field['ask_user'], label)
            self.assertIn(why, field['skip_reason'])
            self.assertTrue(field['needs_review'])
        report = {r['id']: r for r in fill_form(path, form, {by_label['Full name']['id']: 'Ada Obi',
                                                             by_label['Remarks']['id']: 'ok'}, out)}
        self.assertEqual(report[by_label['Full name']['id']]['status'], 'filled')
        self.assertEqual(report[by_label['Remarks']['id']]['status'], 'skipped')
        self.assertIn('official use', report[by_label['Remarks']['id']]['reason'])


    def test_signature_fields_are_not_asked(self):
        """Signature and thumbprint fields are kept but not asked (signed by hand); a date of
        signature and ordinary fields are asked."""
        from layout import analyse_form
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'sign.pdf'
        texts, lines = _underlined([('Full name:', 700), ("Applicant's signature / right thumb print:", 670),
                                    ('Date of signature:', 640)])
        texts += [(56, 760, 'Registration form for the members of our farmers club'), (100, 590, 'Signature')]
        lines[1] = (290, 668, 540)
        lines.append((56, 600, 220))
        make_widget_pdf(path, texts, [], lines=lines)
        form = analyse_form(str(path), read_pdf_words(path, ocr_images=False), method='rules')
        by_label = {f['label']: f for f in form['fields']}
        for label in ("Applicant's signature / right thumb print", 'Signature'):
            self.assertFalse(by_label[label]['ask_user'], label)
            self.assertIn('signature', by_label[label]['skip_reason'])
        self.assertEqual(by_label['Date of signature']['type'], 'date')
        self.assertTrue(by_label['Date of signature']['ask_user'])
        self.assertTrue(by_label['Full name']['ask_user'])


class SharedLabelTests(Tmp):
    def test_fields_with_the_same_label_are_reviewed(self):
        """Two boxes after one printed label get the same label: each is flagged."""
        from layout import _flag_shared_labels
        from make_test_pdfs import make_widget_pdf
        path = self.tmp / 'shared.pdf'
        make_widget_pdf(path, [(56, 700, 'Phone number:'), (56, 660, 'Email:')], [
            {'name': 'code', 'kind': 'text', 'rect': [140, 696, 180, 712]},
            {'name': 'number', 'kind': 'text', 'rect': [190, 696, 320, 712]},
            {'name': 'email', 'kind': 'text', 'rect': [140, 656, 320, 672]},
        ])
        fields = _link(path, tag_all_as_questions=True)
        self.assertEqual(fields['code']['label'], 'Phone number')
        self.assertEqual(fields['number']['label'], 'Phone number')
        self.assertEqual([fields[n]['needs_review'] for n in ('code', 'number', 'email')],
                         [False, False, False])  # confident labels: not flagged for anything else
        _flag_shared_labels(list(fields.values()))
        self.assertEqual([fields[n]['needs_review'] for n in ('code', 'number', 'email')],
                         [True, True, False])


class EditableComboTests(Tmp):
    def test_editable_combo_takes_typed_text(self):
        from pypdf import PdfReader
        from make_test_pdfs import make_widget_pdf
        path, out = self.tmp / 'combo.pdf', self.tmp / 'combo_out.pdf'
        # (a title too: a page needs 3+ words to use its text layer instead of OCR)
        make_widget_pdf(path, [(56, 750, 'Order form'), (56, 700, 'Colour:'), (56, 660, 'Size:')], [
            {'name': 'colour', 'kind': 'combo', 'rect': [140, 696, 300, 712], 'options': ['Red', 'Blue'],
             'flags': 1 << 18},  # Edit: the user may type a value that is not in the list
            {'name': 'size', 'kind': 'combo', 'rect': [140, 656, 300, 672], 'options': ['Small', 'Large']},
        ])
        fields = _link(path)
        self.assertEqual((fields['colour']['type'], fields['colour']['editable']), ('choice', True))
        self.assertEqual((fields['size']['type'], fields['size']['editable']), ('choice', False))
        form = {'form': {'pages': describe_pdf(path)['pages']}, 'fields': list(fields.values()), 'sections': []}
        for answers, expected in (({'colour': 'Green', 'size': 'Medium'}, ('Green', None)),
                                  ({'colour': 'blue', 'size': 'large'}, ('Blue', 'Large'))):
            with self.subTest(answers=answers):
                report = {r['id']: r for r in fill_form(path, form, answers, out)}
                self.assertEqual(report['colour']['status'], 'filled', report['colour'])
                self.assertEqual(report['colour']['verified'], {'value_read_back': True, 'ink_in_box': True})
                values = {k: v.get('/V') for k, v in PdfReader(str(out)).get_fields().items()}
                self.assertEqual(str(values['colour']), expected[0])
                if expected[1] is None:  # not editable: a value outside the list is still refused
                    self.assertEqual(report['size']['status'], 'refused')
                    self.assertIn('matches no option', report['size']['reason'])
                else:
                    self.assertEqual(str(values['size']), expected[1])


class NotAskedFieldTests(Tmp):
    def test_read_only_calculated_and_hidden_fields(self):
        """Kept in fields, marked ask_user: false with a reason; hidden ones also flagged;
        fill_form writes none of them even when answers.json has a value."""
        from pypdf import PdfReader
        from make_test_pdfs import make_widget_pdf
        path, out = self.tmp / 'calc.pdf', self.tmp / 'calc_out.pdf'
        make_widget_pdf(path, [(56, 700, 'Price:'), (56, 660, 'Reference:'), (56, 620, 'Total:'),
                               (56, 580, 'Discount:'), (56, 540, 'Spouse name:')], [
            {'name': 'price', 'kind': 'text', 'rect': [140, 696, 300, 712]},
            {'name': 'ref', 'kind': 'text', 'rect': [140, 656, 300, 672], 'flags': 1, 'value': 'R-1'},
            {'name': 'total', 'kind': 'text', 'rect': [140, 616, 300, 632], 'flags': 1,
             'calculate': 'AFSimple_Calculate("SUM", new Array ("price"));'},
            {'name': 'discount', 'kind': 'text', 'rect': [140, 576, 300, 592],
             'calculate': 'event.value = 0;'},
            {'name': 'spouse', 'kind': 'text', 'rect': [140, 536, 300, 552], 'hidden': True,
             'value': 'kept'},
        ])
        fields = _link(path)
        expected = {'price': (True, None, False),
                    'ref': (False, 'read-only in the PDF', False),
                    'total': (False, 'read-only in the PDF; calculated by the PDF from other fields', False),
                    'discount': (False, 'calculated by the PDF from other fields', False),
                    'spouse': (False, 'hidden in the PDF', True)}
        for name, (ask, reason, hidden) in expected.items():
            field = fields[name]
            self.assertEqual((field['ask_user'], field['skip_reason'], field['hidden']), (ask, reason, hidden), name)
        self.assertTrue(fields['spouse']['needs_review'])
        self.assertEqual(fields['spouse']['label'], 'Spouse name')  # a hidden field keeps its label

        form = {'form': {'pages': describe_pdf(path)['pages']}, 'fields': list(fields.values()), 'sections': []}
        report = {r['id']: r for r in fill_form(path, form, {n: '12' for n in expected}, out)}
        self.assertEqual(report['price']['status'], 'filled')
        for name in ('ref', 'total', 'discount', 'spouse'):
            self.assertEqual(report[name]['status'], 'skipped', report[name])
            self.assertEqual(report[name]['reason'], 'not asked: ' + expected[name][1])
        values = {k: str(v.get('/V')) for k, v in PdfReader(str(out)).get_fields().items()}
        self.assertEqual((values['price'], values['ref'], values['spouse']), ('12', 'R-1', 'kept'))
        self.assertEqual(values['total'], 'None')  # not written
        self.assertEqual(values['discount'], 'None')

    def test_flat_fields_are_asked(self):
        from layout import analyse_form
        path = self.tmp / 'flat.pdf'
        make_flat_pdf(path, 1, 6)
        form = analyse_form(str(path), method='rules')
        self.assertTrue(form['fields'])
        for field in form['fields']:
            self.assertEqual((field['ask_user'], field['skip_reason'], field['hidden']), (True, None, False))


def check_groups(test, form, truth):
    """Fields of make_checkbox_group_pdf: one flagged 'choice' per group, a 'yes_no' lone box."""
    by_name = {tuple(f['pdf_field_name']) if isinstance(f['pdf_field_name'], list)
               else f['pdf_field_name']: f for f in form['fields']}
    test.assertEqual(len(form['fields']), len(truth['groups']) + 2, [f['id'] for f in form['fields']])
    for group in truth['groups']:
        field = by_name[tuple(group['names'])]
        test.assertEqual(field['type'], 'choice')
        test.assertEqual(norm(field['label']), norm(group['label']))
        test.assertEqual(field['options'], group['options'])
        test.assertTrue(field['multiple'])
        test.assertTrue(field['needs_review'])
    lone = by_name[truth['lone']['name']]
    test.assertEqual(lone['type'], 'yes_no')
    test.assertEqual(norm(lone['label']), norm(truth['lone']['label']))


def _fillable_plus_instructions(tmp):
    from pypdf import PdfReader, PdfWriter
    a, b, out = tmp / 'a.pdf', tmp / 'notes.pdf', tmp / 'with_notes.pdf'
    make_fillable_pdf(a, 1, 9)
    make_instructions_pdf(b)
    writer = PdfWriter(clone_from=PdfReader(str(a)))
    writer.append(str(b))
    writer.write(str(out))
    return out


class OutputFormatTests(Tmp):
    def test_pdf_kind(self):
        from layout import pdf_kind
        fillable = {'widgets': 3, 'word_source': 'pdf_text'}
        text = {'widgets': 0, 'word_source': 'pdf_text+ocr_images'}
        scanned = {'widgets': 0, 'word_source': 'ocr'}
        self.assertEqual(pdf_kind([fillable, fillable]), 'fillable')
        self.assertEqual(pdf_kind([text]), 'flat_text')
        self.assertEqual(pdf_kind([scanned, dict(scanned, word_source='none')]), 'flat_scanned')
        self.assertEqual(pdf_kind([fillable, text]), 'mixed')
        self.assertEqual(pdf_kind([text, scanned]), 'mixed')
        self.assertEqual(pdf_kind([fillable, dict(text, kind='instructions')]), 'fillable')

    def test_keys_from_labels(self):
        from layout import _add_keys
        fields = [{'id': 'Text1', 'pdf_field_name': 'Text1', 'label': 'Full name'},
                  {'id': 'Text2', 'pdf_field_name': 'Text2', 'label': 'Full name'},
                  {'id': 'surname', 'pdf_field_name': 'surname', 'label': 'Surname'},
                  {'id': 'full_name', 'pdf_field_name': None, 'label': 'Full name'},
                  {'id': 'Text3', 'pdf_field_name': 'Text3', 'label': None}]
        _add_keys(fields)
        self.assertEqual([f['key'] for f in fields],
                         ['full_name_2', 'full_name_3', 'surname', 'full_name', 'field'])

    def test_answers_by_key_or_id(self):
        from pypdf import PdfReader
        from layout import _add_keys
        path, out = self.tmp / 'f.pdf', self.tmp / 'o.pdf'
        truth = make_fillable_pdf(path, 3, 10)  # seed with at least 3 plain text fields
        form = _fillable_form(path)
        _add_keys(form['fields'])
        texts = [f for f in form['fields'] if f['pdf']['field_type'] == 'Tx' and f['type'] == 'text']
        by_key, by_id, both = texts[0], texts[1], texts[2]
        self.assertNotEqual(by_key['key'], by_key['id'])
        report = {r['id']: r for r in fill_form(path, form, {
            by_key['key']: 'Lagos', by_id['id']: 'Abuja',
            both['id']: 'Kano', both['key']: 'Ibadan'}, out)}
        self.assertEqual(report[by_key['id']]['status'], 'filled')
        self.assertEqual(report[by_key['id']]['key'], by_key['key'])
        self.assertEqual(report[by_id['id']]['status'], 'filled')
        self.assertIn('different answers for id and key', report[both['id']]['reason'])
        self.assertEqual(len(report), len(truth['fields']))
        values = PdfReader(str(out)).get_fields()
        self.assertEqual(str(values[by_key['pdf_field_name']]['/V']), 'Lagos')
        self.assertEqual(str(values[by_id['pdf_field_name']]['/V']), 'Abuja')

    def test_independent_checkbox_groups(self):
        """Separate checkbox fields side by side or stacked are one 'choice' field (flagged) that
        takes a list; a lone checkbox stays 'yes_no'."""
        from pypdf import PdfReader
        from layout import _add_keys
        path, out = self.tmp / 'cb.pdf', self.tmp / 'cb_out.pdf'
        truth = make_checkbox_group_pdf(path)
        form = _fillable_form(path)
        _add_keys(form['fields'])
        check_groups(self, form, truth)
        lone = next(f for f in form['fields'] if f['pdf_field_name'] == truth['lone']['name'])
        group1, group2 = [next(f for f in form['fields'] if f['pdf_field_name'] == g['names'])
                          for g in truth['groups']]
        text = next(f for f in form['fields'] if f['pdf_field_name'] == truth['text']['name'])
        o1, o2 = truth['groups'][0]['options'], truth['groups'][1]['options']
        report = {r['id']: r for r in fill_form(path, form, {
            group1['key']: [o1[0], o1[2]], group2['id']: o2[2], lone['id']: 'yes',
            text['id']: ['a', 'list']}, out)}
        for field in (group1, group2, lone):
            self.assertEqual(report[field['id']]['status'], 'filled', report[field['id']])
            self.assertEqual(report[field['id']]['verified'],
                             {'value_read_back': True, 'ink_in_box': True}, report[field['id']])
        self.assertTrue(report[group1['id']]['needs_review'])
        self.assertEqual(report[text['id']]['status'], 'refused')
        values = {k: str(v.get('/V')) for k, v in PdfReader(str(out)).get_fields().items()}
        names1, names2 = truth['groups'][0]['names'], truth['groups'][1]['names']
        self.assertNotEqual(values[names1[0]], '/Off')
        self.assertEqual(values[names1[1]], '/Off')
        self.assertNotEqual(values[names1[2]], '/Off')
        self.assertEqual([values[n] == '/Off' for n in names2], [True, True, False])
        # The real on-states differ per box ('/Yes' or '/On'); each is read from the PDF.
        from pdf_fields import read_on_states
        states = read_on_states(PdfReader(str(path)))
        self.assertEqual(values[names1[0]], '/' + states[names1[0]][0][0])
        report = {r['id']: r for r in fill_form(path, form, {group1['id']: [o1[0], 'French']}, out)}
        self.assertEqual(report[group1['id']]['status'], 'refused')
        self.assertIn('French', report[group1['id']]['reason'])

    def test_instructions_page_is_not_mixed(self):
        """Fillable page + instructions-only page: still 'fillable', no fields on the instructions."""
        from layout import analyse_form
        form = analyse_form(str(_fillable_plus_instructions(self.tmp)), method='rules')
        self.assertEqual(form['form']['pdf_kind'], 'fillable', form['form']['notes'])
        self.assertEqual([p['kind'] for p in form['form']['pages']], ['fillable', 'instructions'])
        self.assertEqual([f for f in form['fields'] if f['page'] == 2], [])
        self.assertEqual([s for s in form['sections'] if s['page'] == 2], [])

    def test_mixed_pdf_uses_both_paths(self):
        """Page 1 has widgets, page 2 is flat: each page goes through its own path and fills."""
        from pypdf import PdfReader, PdfWriter
        from layout import analyse_form
        a, b, mixed, out = (self.tmp / n for n in ('a.pdf', 'b.pdf', 'mixed.pdf', 'out.pdf'))
        truth = make_fillable_pdf(a, 2, 8)
        make_flat_pdf(b, 3, 8)
        writer = PdfWriter(clone_from=PdfReader(str(a)))
        writer.append(str(b))
        writer.write(str(mixed))
        form = analyse_form(str(mixed), read_pdf_words(mixed, ocr_images=False), method='rules')
        info = form['form']
        self.assertEqual(info['pdf_kind'], 'mixed')
        self.assertEqual([p['kind'] for p in info['pages']], ['fillable', 'flat_text'])
        self.assertEqual(set(info['pages'][0]) >= {'page', 'width_px', 'height_px', 'dpi'}, True)
        page1 = [f for f in form['fields'] if f['page'] == 1]
        page2 = [f for f in form['fields'] if f['page'] == 2]
        self.assertEqual({f['pdf_field_name'] for f in page1}, {t['name'] for t in truth['fields']})
        self.assertTrue(page2)
        for field in page2:
            self.assertIsNone(field['pdf_field_name'])
            self.assertIsNone(field['required'])
        for field in form['fields']:
            self.assertIn(field['type'], ALLOWED_TYPES)
        json.dumps(form)
        text = next(f for f in page1 if f['pdf']['field_type'] == 'Tx' and f['type'] == 'text')
        drawn = next(f for f in page2 if f['answer_box'] and f['answer_method'] != 'checkboxes'
                     and f['type'] in ('text', 'unknown'))
        report = {r['id']: r for r in fill_form(mixed, form, {text['id']: 'Lagos',
                                                              drawn['id']: 'Kano'}, out)}
        self.assertEqual(report[text['id']]['status'], 'filled')
        self.assertEqual(report[drawn['id']]['status'], 'filled')
        reader = PdfReader(str(out))
        self.assertEqual(str(reader.get_fields()[text['pdf_field_name']].get('/V')), 'Lagos')
        self.assertIn('Kano', reader.pages[1].extract_text())


@unittest.skipUnless(SLOW, 'set RUN_SLOW=1 to run PaddleOCR + LayoutLM')
class FullPipelineOnPdfs(Tmp):
    def check(self, form, truth, fillable):
        fields = {norm(f['label']): f for f in form['fields']}
        for t in truth['fields']:
            self.assertIn(norm(t['label']), fields, f"missed {t['label']}; got {list(fields)}")
            field = fields[norm(t['label'])]
            scanned = form['form']['pages'][field['page'] - 1].get('word_source') == 'ocr'
            if scanned and t.get('options') and set(field['options']) < set(t['options']):
                # Known OCR limit (REPORT section 4): an option next to its box can be missed,
                # and then the group is not seen as a group. The found options must still be real.
                continue
            self.assertEqual(field['type'], expected_type(t, fillable), t['label'])
            if fillable:
                self.assertEqual(field['id'], t['name'])
                # Brief: LayoutLM question first, then the tooltip (generated tooltips = label).
                self.assertTrue(field['label_source'].startswith('layoutlm')
                                or field['label_source'] == 'tooltip', field)
        # Extras (usually headings the model tagged as questions) are allowed only if flagged.
        expected = {norm(t['label']) for t in truth['fields']}
        extras = [f for f in form['fields'] if norm(f['label']) not in expected]
        self.assertLessEqual(len(extras), 2, [f['label'] for f in extras])
        for extra in extras:
            self.assertTrue(extra['needs_review'], f"unflagged extra field {extra['label']!r}")
        titles = {norm(s['title']) for s in form['sections']}
        flagged = {norm(f['label']) for f in extras}
        for title in truth['sections']:
            # A heading is in 'sections', or (known OCR-page limitation) a flagged extra field.
            self.assertIn(norm(title), titles | flagged)
        json.dumps(form)  # the whole object must be JSON-ready

    def test_generated_pdfs(self):
        from layout import analyse_form
        for seed, count in SEEDS[:3]:
            for kind in ('fillable', 'flat'):
                with self.subTest(seed=seed, kind=kind):
                    path = self.tmp / f'{kind}{seed}.pdf'
                    truth = (make_fillable_pdf if kind == 'fillable' else make_flat_pdf)(path, seed, count)
                    form = analyse_form(str(path))
                    self.assertEqual(form['form']['pdf_kind'], 'fillable' if kind == 'fillable' else 'flat_text')
                    self.assertEqual(form['form']['pages'][0]['word_source'], 'pdf_text')
                    self.check(form, truth, kind == 'fillable')

    def test_checkbox_groups_with_layoutlm(self):
        from layout import analyse_form
        path = self.tmp / 'cb.pdf'
        truth = make_checkbox_group_pdf(path)
        form = analyse_form(str(path))
        self.assertEqual(form['form']['pdf_kind'], 'fillable')
        check_groups(self, form, truth)

    def test_instructions_page_with_layoutlm(self):
        from layout import analyse_form
        form = analyse_form(str(_fillable_plus_instructions(self.tmp)))
        self.assertEqual(form['form']['pdf_kind'], 'fillable', form['form']['notes'])
        self.assertEqual(form['form']['pages'][1]['kind'], 'instructions')
        self.assertEqual([f['label'] for f in form['fields'] if f['page'] == 2], [])

    def test_watermark_does_not_cut_answer_lines(self):
        """OCR of embedded pictures keeps a dark picture label but drops pale watermark letters,
        so the underline under the watermark is still the whole answer area."""
        from layout import analyse_form
        from make_test_pdfs import make_watermark_pdf
        path = self.tmp / 'wm.pdf'
        truth = make_watermark_pdf(path)
        items = read_pdf_words(path)
        texts = ' '.join(i['text'] for i in items).lower()
        self.assertIn('signature', texts)  # the picture label is read
        self.assertNotIn('water', texts)
        self.assertNotIn('mark', texts)
        form = analyse_form(str(path), items)
        email = next(f for f in form['fields'] if norm(f['label']) == 'e mail')
        scale = 200 / 72
        line = [v * scale for v in truth['lines_pt']['E-mail']]
        self.assertEqual(email['answer_method'], 'underline')
        self.assertGreaterEqual(email['answer_box'][2] - email['answer_box'][0], 0.9 * (line[1] - line[0]))

    def test_image_only_pdf(self):
        from layout import analyse_form
        flat, image = self.tmp / 'flat.pdf', self.tmp / 'image.pdf'
        truth = make_flat_pdf(flat, 2, 8)
        make_image_pdf(flat, image)
        form = analyse_form(str(image))
        self.assertEqual(form['form']['pdf_kind'], 'flat_scanned')
        self.assertEqual(form['form']['pages'][0]['word_source'], 'ocr')
        self.check(form, truth, False)


if __name__ == '__main__':
    unittest.main()
