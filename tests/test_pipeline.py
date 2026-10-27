"""Generic tests: no dependence on any one sample form.

Fast tests:  .venv\\Scripts\\python.exe -m unittest discover -s tests -v
Slow tests (PaddleOCR + LayoutLM): set RUN_SLOW=1 first.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from field_types import ALLOWED_TYPES, guess_type  # noqa: E402
from layout import find_fields  # noqa: E402
from layout_lm import normalize_box, split_into_words, split_label  # noqa: E402
from make_synthetic_form import make_form  # noqa: E402

SLOW = os.environ.get('RUN_SLOW') == '1'
SHAPE2_KEYS = {'id', 'label', 'label_box', 'answer_box', 'type', 'source', 'confidence',
               'needs_review'}
# Different seeds, sizes and aspect ratios so nothing depends on one layout.
CASES = [(1, 1400, 1000), (2, 900, 1300), (5, 2000, 1500), (7, 1100, 800)]


def overlap_ratio(a, b):
    """Intersection over the smaller box."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / max(1, smaller)


def fake_ocr(truth):
    """OCR-like items straight from the generator's ground truth (no PaddleOCR needed)."""
    items = []
    for field in truth['fields']:
        items.append({'text': field['text'], 'box': field['label_box'], 'score': 1.0, 'page': 1})
        for option in field['options']:
            items.append({'text': option['text'], 'box': option['box'], 'score': 1.0, 'page': 1})
    return items


def check_shape2(test, fields, width, height):
    for field in fields:
        test.assertTrue(SHAPE2_KEYS <= set(field), field)
        test.assertIn(field['type'], ALLOWED_TYPES)
        test.assertIn(field['source'], ('layoutlm', 'rules'))
        test.assertTrue(0.0 <= field['confidence'] <= 1.0)
        test.assertIsInstance(field['needs_review'], bool)
        for key in ('label_box', 'answer_box'):
            box = field[key]
            if box is None:
                continue
            test.assertEqual(len(box), 4)
            test.assertTrue(0 <= box[0] <= box[2] <= width and 0 <= box[1] <= box[3] <= height,
                            f'{key} {box} outside {width}x{height}')
    test.assertEqual(len({f['id'] for f in fields}), len(fields), 'ids must be unique')


class FieldTypeTests(unittest.TestCase):
    def test_keywords(self):
        self.assertEqual(guess_type('E-mail'), 'email')
        self.assertEqual(guess_type('Contact telephone'), 'phone')
        self.assertEqual(guess_type('Date of arrival'), 'date')
        self.assertEqual(guess_type('Have you travelled abroad?'), 'yes_no')
        self.assertEqual(guess_type('Total amount'), 'number')
        self.assertEqual(guess_type('Signature'), 'unknown')

    def test_options_beat_keywords(self):
        self.assertEqual(guess_type('Anything', ['Yes', 'No']), 'yes_no')
        self.assertEqual(guess_type('Colour', ['Red', 'Blue', 'Green']), 'choice')
        self.assertEqual(guess_type('Colour', [], checkbox_count=3), 'choice')


class LayoutLMInputTests(unittest.TestCase):
    def test_words_get_own_boxes_inside_line(self):
        words = split_into_words([{'text': 'First  name here', 'box': [100, 10, 400, 30]}])
        self.assertEqual([w['text'] for w in words], ['First', 'name', 'here'])
        for word in words:
            self.assertTrue(100 <= word['box'][0] < word['box'][2] <= 400)
        self.assertTrue(words[0]['box'][2] <= words[1]['box'][0])

    def test_normalize_uses_real_size(self):
        self.assertEqual(normalize_box([0, 0, 640, 480], 640, 480), [0, 0, 1000, 1000])
        self.assertEqual(normalize_box([320, 240, 640, 480], 640, 480), [500, 500, 1000, 1000])

    def test_label_names_are_parsed_not_assumed(self):
        self.assertEqual(split_label('B-QUESTION'), ('B', 'question'))
        self.assertEqual(split_label('I-ANSWER'), ('I', 'answer'))
        self.assertEqual(split_label('O'), ('O', 'other'))


class RulesOnSyntheticForms(unittest.TestCase):
    def test_generated_forms(self):
        for seed, width, height in CASES:
            with self.subTest(seed=seed, size=(width, height)), tempfile.TemporaryDirectory() as tmp:
                image, truth = make_form(width, height, seed, count=8)
                path = Path(tmp) / 'form.png'
                image.save(path)
                fields = find_fields(fake_ocr(truth), str(path), method='rules', clean=False)
                check_shape2(self, fields, width, height)

                found = 0
                for expected in truth['fields']:
                    match = next((f for f in fields
                                  if overlap_ratio(f['label_box'], expected['label_box']) > 0.8), None)
                    if match is None:
                        continue
                    found += 1
                    self.assertIsNotNone(match['answer_box'], expected['label'])
                    self.assertGreater(overlap_ratio(match['answer_box'], expected['answer_box']), 0.5,
                                       f"answer box for {expected['label']}")
                    self.assertEqual(match['type'], expected['type'], expected['label'])
                self.assertEqual(found, len(truth['fields']))


@unittest.skipUnless(SLOW, 'set RUN_SLOW=1 to run PaddleOCR + LayoutLM')
class FullPipelineSlow(unittest.TestCase):
    def test_ocr_and_layoutlm_on_synthetic(self):
        from ocr import prepare_pages, read_form
        with tempfile.TemporaryDirectory() as tmp:
            image, truth = make_form(1500, 1100, 11, count=8)
            path = Path(tmp) / 'form.png'
            image.save(path)
            items = read_form(str(path))
            page = prepare_pages(str(path))[0]
            height, width = page.shape[:2]
            for item in items:
                self.assertEqual(set(item), {'text', 'box', 'score', 'page'})
                self.assertTrue(item['box'][2] <= width and item['box'][3] <= height)
            fields = find_fields(items, str(path), method='layoutlm')
            check_shape2(self, fields, width, height)
            self.assertTrue(fields)


if __name__ == '__main__':
    unittest.main()
