"""Rule-based FALLBACK for finding field labels from OCR text alone. Generic: no form-specific
names, wording or coordinates. Used when LayoutLM fails, and as a sanity check."""
import re

import cv2
import numpy as np

MAX_LABEL_WORDS = 8        # longer lines are treated as instructions, not labels
MAX_PLAIN_LABEL_WORDS = 5  # labels without ':' or '?' must be this short
OPTION_WORDS = {'yes', 'no', 'y', 'n', 'true', 'false'}
BOX_GLYPHS = '□■☐☑☒▢▣◻◼'


def clean_items(raw):
    """Normalize OCR output to text, score, box, and 1-based page records."""
    items = []
    for item in raw:
        if isinstance(item, dict):
            text = item.get('text') or item.get('rec_text') or ''
            box = item.get('box') or item.get('bbox') or item.get('rec_box')
            score = item.get('score', item.get('confidence', 1.0))
            page = item.get('page', 1)
        else:
            box, (text, score) = item[0], item[1]
            page = 1

        # OCR sometimes reads a printed checkbox as a glyph glued to its option ('□No').
        text = str(text).strip().strip(BOX_GLYPHS).strip()
        if not text or box is None:
            continue
        if len(box) == 4 and isinstance(box[0], (list, tuple)):
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            box = [min(xs), min(ys), max(xs), max(ys)]

        cleaned = {
            'text': str(text).strip(),
            'box': [int(value) for value in box],
            'score': float(score),
            'page': int(page),
        }
        # Keep where the text came from and exact word boxes (PDF text layer), if present.
        if isinstance(item, dict):
            for key in ('source', 'words'):
                if key in item:
                    cleaned[key] = item[key]
        items.append(cleaned)
    return items


def get_rows(items):
    """Group OCR pieces that share a line, without mixing pages."""
    pages = {}
    for item in items:
        pages.setdefault(item.get('page', 1), []).append(item)

    rows = []
    for page, page_items in sorted(pages.items()):
        page_items.sort(key=lambda item: (item['box'][1], item['box'][0]))
        page_rows = []
        for item in page_items:
            top, bottom = item['box'][1], item['box'][3]
            centre = (top + bottom) / 2
            height = max(1, bottom - top)
            matching_row = next(
                (
                    row for row in reversed(page_rows)
                    if abs(centre - row['centre']) <= max(
                        6, min(height, row['height']) * 0.55
                    )
                ),
                None,
            )
            if matching_row is None:
                page_rows.append({
                    'page': page,
                    'items': [item],
                    'centre': centre,
                    'height': height,
                })
            else:
                matching_row['items'].append(item)
                matching_row['centre'] = sum(
                    (part['box'][1] + part['box'][3]) / 2
                    for part in matching_row['items']
                ) / len(matching_row['items'])
                matching_row['height'] = max(matching_row['height'], height)

        for row in page_rows:
            parts = sorted(row['items'], key=lambda item: item['box'][0])
            rows.append({
                'page': page,
                'text': ' '.join(part['text'] for part in parts),
                'items': parts,
                'box': [
                    min(part['box'][0] for part in parts),
                    min(part['box'][1] for part in parts),
                    max(part['box'][2] for part in parts),
                    max(part['box'][3] for part in parts),
                ],
            })
    return rows


def _key(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _words(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.lower()))


def _has_label(text, label):
    text_words = _words(text)
    label_words = _words(label)
    return bool(re.search(
        rf'(?<![a-z0-9]){re.escape(label_words)}(?![a-z0-9])',
        text_words,
    ))


def _starts_with_label(text, label):
    return _words(text).startswith(_words(label))


def union_box(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def clean_label(text):
    """Strip filler around a label: trailing ':', '*', dots/underscores, brackets of blanks."""
    text = re.sub(r'[_.…]{2,}', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' :*-–—\t')
    return text


def is_option_word(text):
    return _words(text) in OPTION_WORDS


def _merge_wrapped_labels(labels, items):
    """Join a label with a short continuation line directly below it that starts lowercase
    (e.g. a label wrapped over two lines). Works on any form; no wording is assumed."""
    used = set()
    for label in labels:
        height = label['label_box'][3] - label['label_box'][1]
        left = min([label['label_box'][0]] + [i['box'][0] for i in label.get('label_items', [])])
        for index, item in enumerate(items):
            if index in used or item.get('page', 1) != label['page']:
                continue
            box = item['box']
            words = item['text'].split()
            if (0 <= box[1] - label['label_box'][3] <= 0.6 * height
                    and abs(box[0] - left) <= height
                    and 1 <= len(words) <= 3 and item['text'][:1].islower()
                    and not item['text'].rstrip().endswith('.')):
                label['label'] = clean_label(f"{label['label']} {item['text']}")
                label['label_box'] = union_box([label['label_box'], box])
                label.setdefault('label_items', []).append(item)
                used.add(index)
                break
    # A label made only of lines that were merged into another label is dropped.
    absorbed = {id(items[index]) for index in used}
    kept = [label for label in labels
            if not label.get('label_items')
            or not all(id(item) in absorbed for item in label['label_items'])]
    return kept, used


def label_from_text(text):
    """Return (label, confidence) if an OCR line looks like a field label, else (None, 0)."""
    text = text.strip()
    if not re.search(r'[A-Za-z]{2,}', text) or is_option_word(text):
        return None, 0.0
    if ':' in text:
        before = clean_label(text.split(':', 1)[0])
        if before and 1 <= len(before.split()) <= MAX_LABEL_WORDS:
            return before, 0.7
    if text.endswith('?') and len(text.split()) <= 2 * MAX_LABEL_WORDS:
        return clean_label(text), 0.6
    words = text.split()
    letters = re.sub(r'[^A-Za-z]', '', text)
    looks_like_heading = len(words) >= 3 and letters.isupper()
    if (len(words) <= MAX_PLAIN_LABEL_WORDS and not text.endswith('.')
            and not looks_like_heading):
        return clean_label(text), 0.4
    return None, 0.0


def extract_fields(ocr_items):
    """Find label candidates from OCR text alone. Returns partial Shape 2 dicts
    (answer_box and type are filled in by layout.find_fields)."""
    items = clean_items(ocr_items)
    labels = []
    for item in items:
        label, confidence = label_from_text(item['text'])
        if not label:
            continue
        labels.append({
            'label': label,
            'label_box': list(item['box']),
            'page': item['page'],
            'confidence': confidence,
            'source': 'rules',
            'label_items': [item],
        })
    labels, _ = _merge_wrapped_labels(labels, items)
    return labels


def draw_boxes(fields, form_path, out_path='form_boxes.png', ocr_items=None, clean=True,
               sections=None):
    """Draw labels (red), answer areas (blue) and section headings (green) on the same page
    images that were OCR'd (PDFs: the colour render). Fillable fields: every widget is drawn.
    ocr_items is kept for backward compatibility; when given, OCR text is outlined in grey."""
    from ocr import prepare_pages
    pages = [page.copy() for page in prepare_pages(form_path, clean)]
    for item in clean_items(ocr_items or []):
        if 1 <= item['page'] <= len(pages):
            x1, y1, x2, y2 = item['box']
            cv2.rectangle(pages[item['page'] - 1], (x1, y1), (x2, y2), (190, 190, 190), 1)
    for field in fields:
        page_index = field.get('page', 1) - 1
        if not 0 <= page_index < len(pages):
            raise ValueError(f"Field {field['id']} refers to missing page {field.get('page')}.")
        page = pages[page_index]
        thickness = max(2, page.shape[1] // 600)
        if field.get('label_box'):
            x1, y1, x2, y2 = field['label_box']
            cv2.rectangle(page, (x1, y1), (x2, y2), (0, 0, 255), thickness)
        widgets = (field.get('pdf') or {}).get('widgets')
        if widgets:
            for widget in widgets:
                x1, y1, x2, y2 = widget['box']
                cv2.rectangle(pages[widget['page'] - 1], (x1, y1), (x2, y2), (255, 0, 0), thickness)
        elif field.get('answer_box'):
            x1, y1, x2, y2 = field['answer_box']
            cv2.rectangle(page, (x1, y1), (x2, y2), (255, 0, 0), thickness)
    for section in sections or []:
        page = pages[section['page'] - 1]
        x1, y1, x2, y2 = section['box']
        cv2.rectangle(page, (x1, y1), (x2, y2), (0, 160, 0), max(2, page.shape[1] // 600))

    gutter = 20
    width = max(page.shape[1] for page in pages)
    canvas = np.full((sum(p.shape[0] for p in pages) + gutter * (len(pages) - 1), width, 3),
                     255, np.uint8)
    y = 0
    for page in pages:
        canvas[y:y + page.shape[0], :page.shape[1]] = page
        y += page.shape[0] + gutter
    cv2.imwrite(str(out_path), canvas)
