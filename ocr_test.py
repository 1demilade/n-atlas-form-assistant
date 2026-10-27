"""Check that read_form returns Shape 1 and that boxes fit the image that was OCR'd.

Usage: python ocr_test.py [FORM_IMAGE_OR_PDF]   (default: a freshly generated synthetic form)
"""
import sys
import tempfile
from pathlib import Path

from ocr import prepare_pages, read_form


def test_read_form_returns_list(path):
    items = read_form(path)
    pages = prepare_pages(path)
    assert isinstance(items, list)
    assert items
    for item in items:
        # 'words' (exact word boxes) is only present on PDF text-layer items.
        assert set(item) - {'words'} == {'text', 'box', 'score', 'page', 'source'}, item
        assert item['source'] in ('pdf_text', 'ocr'), item
        assert isinstance(item['box'], list) and len(item['box']) == 4
        height, width = pages[item['page'] - 1].shape[:2]
        x1, y1, x2, y2 = item['box']
        assert 0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height, (item, width, height)
    return items


if __name__ == '__main__':
    if len(sys.argv) > 1:
        form_path = sys.argv[1]
    else:
        from make_synthetic_form import make_form
        form_path = str(Path(tempfile.mkdtemp()) / 'synthetic.png')
        make_form(1300, 900, seed=4)[0].save(form_path)
    result = test_read_form_returns_list(form_path)
    print(f'PASSED: {len(result)} items from {form_path}; first: {result[0]}')
