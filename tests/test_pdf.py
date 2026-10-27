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
from make_test_pdfs import make_fillable_pdf, make_flat_pdf, make_image_pdf  # noqa: E402
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
                    self.assertEqual(field['type'], expected_type(t, True), t)
                    self.assertIn(field['type'], ALLOWED_TYPES)
                    self.assertTrue(field['needs_review'], 'fallback labels must be flagged')
                    if t.get('options'):
                        self.assertEqual(field['options'], t['options'])


def _fillable_form(path):
    items = read_pdf_words(path, ocr_images=False)
    fields, _ = link_fields(read_acroform(path), items, prepare_pages(path), use_layoutlm=False)
    return {'kind': 'fillable', 'fields': fields, 'sections': [], 'pages': describe_pdf(path)['pages']}


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
        text = next(f for f in form['fields'] if f['pdf']['field_type'] == 'Tx')
        text['pdf']['max_length'] = 2
        choice = next(f for f in form['fields'] if f['options'])
        report = {r['id']: r for r in fill_form(path, form, {
            text['id']: 'too long', choice['id']: 'not an option', 'no_such_field': 'x'}, out)}
        self.assertIn('max_length', report[text['id']]['reason'])
        self.assertIn('matches no option', report[choice['id']]['reason'])
        self.assertEqual(report['no_such_field']['reason'], 'no field with this id')
        self.assertEqual(len(truth['fields']) + 1, len(report))

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
                form = {'kind': 'flat', 'fields': fields, 'sections': [],
                        'pages': describe_pdf(path)['pages']}
                report = fill_form(path, form, answers, out)
                self.assertTrue(all(r['status'] == 'filled' for r in report), report)

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


@unittest.skipUnless(SLOW, 'set RUN_SLOW=1 to run PaddleOCR + LayoutLM')
class FullPipelineOnPdfs(Tmp):
    def check(self, form, truth, fillable):
        fields = {norm(f['label']): f for f in form['fields']}
        for t in truth['fields']:
            self.assertIn(norm(t['label']), fields, f"missed {t['label']}; got {list(fields)}")
            field = fields[norm(t['label'])]
            self.assertEqual(field['type'], expected_type(t, fillable), t['label'])
            if fillable:
                self.assertEqual(field['id'], t['name'])
                self.assertTrue(field['label_source'].startswith('layoutlm'), field)
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
                    self.assertEqual(form['kind'], kind)
                    self.assertEqual(form['pages'][0]['word_source'], 'pdf_text')
                    self.check(form, truth, kind == 'fillable')

    def test_image_only_pdf(self):
        from layout import analyse_form
        flat, image = self.tmp / 'flat.pdf', self.tmp / 'image.pdf'
        truth = make_flat_pdf(flat, 2, 8)
        make_image_pdf(flat, image)
        form = analyse_form(str(image))
        self.assertEqual(form['pages'][0]['word_source'], 'ocr')
        self.check(form, truth, False)


if __name__ == '__main__':
    unittest.main()
