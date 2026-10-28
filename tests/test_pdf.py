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
