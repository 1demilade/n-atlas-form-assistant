"""PDF input: what kind of PDF this is, page sizes, and words with boxes for every page.

Per page, words come from the cheapest reliable source:
  - the PDF text layer (pdfplumber; exact boxes, no OCR) when the page has real text, plus OCR of
    the page's embedded images only (text inside images is not in the text layer);
  - otherwise PaddleOCR on the whole page render.
Every box is converted to pixels of the PDF_DPI render of its page (ocr.render_pdf), top-left
origin, so all sources share one coordinate system. Each item records its 'source'.
"""
import re

from ocr import PDF_DPI, ocr_image, prepare_pages

# ---- Config (no form-specific values) ----
MIN_TEXT_WORDS = 3          # fewer real words than this -> the page is treated as image-only
MAX_BAD_WORD_SHARE = 0.2    # more garbage words ('(cid:12)', U+FFFD) than this -> no real text
PHRASE_GAP = 0.8            # words on a row join into one item if the gap < this * word height
ROW_OVERLAP = 0.5           # words share a row if they overlap vertically by this share
MIN_IMAGE_SIDE_PT = 6       # embedded images thinner than this cannot hold readable text
MAX_IMAGE_PAGE_SHARE = 0.9  # an image covering the whole page is a scan behind its own text layer
IMAGE_PAD_PX = 12           # white border added around an image crop before OCR
OCR_OVERLAP_DROP = 0.5      # OCR text overlapping text-layer words this much is a duplicate
INK_PIXEL = 235             # a render pixel darker than this (0-255 grey) is ink
PALE_INK = 180              # OCR text whose median ink is lighter than this is a watermark

BAD_WORD = re.compile(r'\(cid:\d+\)|�')


def _bad_share(words):
    return sum(1 for w in words if BAD_WORD.search(w['text'])) / max(1, len(words))


def has_real_text(words):
    """True if a page's text-layer words are enough, and clean enough, to skip OCR."""
    real = [w for w in words if re.search(r'[A-Za-z0-9]', w['text']) and not BAD_WORD.search(w['text'])]
    return len(real) >= MIN_TEXT_WORDS and _bad_share(words) <= MAX_BAD_WORD_SHARE


def _overlap_share(box, other):
    """Share of box's area covered by other."""
    ix = max(0, min(box[2], other[2]) - max(box[0], other[0]))
    iy = max(0, min(box[3], other[3]) - max(box[1], other[1]))
    return ix * iy / max(1, (box[2] - box[0]) * (box[3] - box[1]))


def _to_pixels(x0, top, x1, bottom, frame):
    """pdfplumber coordinates (points, top-left origin) -> pixels of the page render."""
    left, upper, scale_x, scale_y, width_px, height_px = frame
    box = [(x0 - left) * scale_x, (top - upper) * scale_y,
           (x1 - left) * scale_x, (bottom - upper) * scale_y]
    return [int(round(max(0, min(width_px, box[0])))), int(round(max(0, min(height_px, box[1])))),
            int(round(max(0, min(width_px, box[2])))), int(round(max(0, min(height_px, box[3]))))]


def _frame(pypdf_page, render):
    """Offset and scale from pdfplumber coordinates to the render of the page.

    pdfplumber reports words in display orientation (page rotation applied) relative to the
    MEDIA box; pdfium renders only the CROP box. So the crop box is moved to top-left
    coordinates, rotated like the page, and used as the origin."""
    height_px, width_px = render.shape[:2]
    media, crop = pypdf_page.mediabox, pypdf_page.cropbox
    media_w, media_h = float(media.width), float(media.height)
    # Crop box corners, unrotated, top-left origin relative to the media box.
    x0, x1 = float(crop.left) - float(media.left), float(crop.right) - float(media.left)
    y0, y1 = float(media.top) - float(crop.top), float(media.top) - float(crop.bottom)
    rotation = (pypdf_page.rotation or 0) % 360
    corners = []
    for u, v in ((x0, y0), (x1, y1)):
        if rotation == 90:
            u, v = media_h - v, u
        elif rotation == 180:
            u, v = media_w - u, media_h - v
        elif rotation == 270:
            u, v = v, media_w - u
        corners.append((u, v))
    left, right = sorted(c[0] for c in corners)
    upper, lower = sorted(c[1] for c in corners)
    return (left, upper, width_px / (right - left), height_px / (lower - upper), width_px, height_px)


def group_phrases(words, page):
    """Join words that sit close together on one row into OCR-line-like items.
    Each item keeps its exact word boxes in 'words' (LayoutLM uses them directly)."""
    rows = []
    for word in sorted(words, key=lambda w: ((w['box'][1] + w['box'][3]) / 2, w['box'][0])):
        top, bottom = word['box'][1], word['box'][3]
        row = next((r for r in reversed(rows[-3:])
                    if min(bottom, r['bottom']) - max(top, r['top'])
                    >= ROW_OVERLAP * min(bottom - top, r['bottom'] - r['top'])), None)
        if row is None:
            rows.append({'top': top, 'bottom': bottom, 'words': [word]})
        else:
            row['words'].append(word)
            row['top'], row['bottom'] = min(row['top'], top), max(row['bottom'], bottom)

    items = []
    for row in rows:
        phrase = []
        for word in sorted(row['words'], key=lambda w: w['box'][0]):
            if phrase:
                last = phrase[-1]['box']
                height = min(last[3] - last[1], word['box'][3] - word['box'][1])
                if word['box'][0] - last[2] > PHRASE_GAP * max(1, height):
                    items.append(_phrase_item(phrase, page))
                    phrase = []
            phrase.append(word)
        if phrase:
            items.append(_phrase_item(phrase, page))
    return items


def _phrase_item(words, page):
    boxes = [w['box'] for w in words]
    return {
        'text': ' '.join(w['text'] for w in words),
        'box': [min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes)],
        'score': 1.0,
        'page': page,
        'source': 'pdf_text',
        'words': [{'text': w['text'], 'box': w['box']} for w in words],
    }


def is_pale_text(render, box):
    """True if the ink inside box is pale grey (a watermark or background art), not printed
    text. The median of the inked pixels is used, so a dark line crossing the box (an underline
    drawn over a watermark) does not count."""
    import cv2
    import numpy as np
    crop = render[max(0, box[1]):box[3], max(0, box[0]):box[2]]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    ink = gray[gray < INK_PIXEL]
    return bool(ink.size) and float(np.median(ink)) > PALE_INK


def _ocr_images(plumber_page, render, frame, page_number, layer_items):
    """OCR only the embedded images of a text-layer page; drop text the layer already has."""
    page_area = plumber_page.width * plumber_page.height
    found = []
    for image in plumber_page.images:
        x0, top = max(image['x0'], plumber_page.bbox[0]), max(image['top'], plumber_page.bbox[1])
        x1, bottom = min(image['x1'], plumber_page.bbox[2]), min(image['bottom'], plumber_page.bbox[3])
        if min(x1 - x0, bottom - top) < MIN_IMAGE_SIDE_PT:
            continue
        if (x1 - x0) * (bottom - top) > MAX_IMAGE_PAGE_SHARE * page_area:
            continue
        box = _to_pixels(x0, top, x1, bottom, frame)
        crop = render[box[1]:box[3], box[0]:box[2]]
        if crop.size == 0:
            continue
        import cv2
        padded = cv2.copyMakeBorder(crop, IMAGE_PAD_PX, IMAGE_PAD_PX, IMAGE_PAD_PX, IMAGE_PAD_PX,
                                    cv2.BORDER_CONSTANT, value=(255, 255, 255))
        for item in ocr_image(padded, page_number):
            b = item['box']
            item['box'] = [max(box[0], b[0] - IMAGE_PAD_PX + box[0]), max(box[1], b[1] - IMAGE_PAD_PX + box[1]),
                           min(box[2], b[2] - IMAGE_PAD_PX + box[0]), min(box[3], b[3] - IMAGE_PAD_PX + box[1])]
            if item['box'][2] <= item['box'][0] or item['box'][3] <= item['box'][1]:
                continue
            if any(_overlap_share(item['box'], other['box']) > OCR_OVERLAP_DROP for other in layer_items):
                continue
            if is_pale_text(render, item['box']):
                continue  # watermark letters would block answer lines and confuse the model
            found.append(item)
    return found


def read_pdf_words(path, ocr_images=True):
    """Return Shape 1 items (+ 'source') for every page of a PDF, in render pixel coordinates.
    ocr_images=False skips OCR of embedded images on text-layer pages (faster; used in tests)."""
    import pdfplumber
    from pypdf import PdfReader
    renders = prepare_pages(path, clean=False)
    pypdf_pages = PdfReader(str(path)).pages
    items = []
    with pdfplumber.open(str(path)) as pdf:
        if not len(pdf.pages) == len(renders) == len(pypdf_pages):
            raise ValueError(f'{path}: pdfplumber sees {len(pdf.pages)} pages, render has {len(renders)}.')
        for number, (plumber_page, render) in enumerate(zip(pdf.pages, renders), start=1):
            frame = _frame(pypdf_pages[number - 1], render)
            words = [{'text': w['text'], 'box': _to_pixels(w['x0'], w['top'], w['x1'], w['bottom'], frame)}
                     for w in plumber_page.extract_words(keep_blank_chars=False, use_text_flow=False)]
            words = [w for w in words if w['box'][2] > w['box'][0] and w['box'][3] > w['box'][1]]
            if has_real_text(words):
                layer = group_phrases([w for w in words if not BAD_WORD.search(w['text'])], number)
                items.extend(layer)
                if ocr_images:
                    items.extend(_ocr_images(plumber_page, render, frame, number, layer))
            else:
                items.extend(ocr_image(render, number))
    return items


def count_widgets(path):
    """Number of AcroForm widgets (fillable fields) on each page, read with pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    counts = []
    for page in reader.pages:
        annots = page.get('/Annots') or []
        counts.append(sum(1 for a in annots if a.get_object().get('/Subtype') == '/Widget'))
    return counts


def describe_pdf(path, items=None):
    """PDF kind and per-page facts. With items (from read_pdf_words), also which word source
    each page used: 'pdf_text', 'pdf_text+ocr_images', 'ocr', or 'none' (no text found)."""
    import pdfplumber
    renders = prepare_pages(path, clean=False)
    widgets = count_widgets(path)
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for number, (plumber_page, render) in enumerate(zip(pdf.pages, renders), start=1):
            info = {
                'page': number,
                'dpi': PDF_DPI,
                'width_px': int(render.shape[1]),
                'height_px': int(render.shape[0]),
                'width_pt': round(float(plumber_page.width), 2),
                'height_pt': round(float(plumber_page.height), 2),
                'rotation': int(plumber_page.rotation or 0),
                'widgets': widgets[number - 1],
            }
            if items is not None:
                sources = {item.get('source', 'ocr') for item in items if item['page'] == number}
                if 'pdf_text' in sources:
                    info['word_source'] = 'pdf_text+ocr_images' if 'ocr' in sources else 'pdf_text'
                else:
                    info['word_source'] = 'ocr' if sources else 'none'
            pages.append(info)
    return {'file': str(path), 'kind': 'fillable' if sum(widgets) else 'flat', 'dpi': PDF_DPI,
            'pages': pages}
