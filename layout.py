"""Form understanding: OCR items + page images -> list of fields (Shape 2).

LayoutLM is the primary method; layout_rules is used only if LayoutLM fails or finds nothing.

Usage:  python layout.py FORM_IMAGE_OR_PDF [--fields form_fields.json] [--boxes form_boxes.png]
"""
import argparse
import json
import re
import sys

from answer_areas import (detect_regions, find_answer_box, median_text_height, nearby_checkboxes,
                          next_to_checkbox)
from field_types import guess_type
from layout_rules import (_merge_wrapped_labels, clean_items, clean_label, draw_boxes,
                          extract_fields, is_option_word, union_box)

REVIEW_BELOW_CONFIDENCE = 0.6
# Answer areas found this way are plausible but often wrong (e.g. a section heading's own row).
GUESSED_METHODS = {'own_cell', 'empty_right', 'empty_below', 'none'}


def _same_row(a, b, share=0.5):
    overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap >= share * min(a[3] - a[1], b[3] - b[1])


INSTRUCTION_START = re.compile(r'^(please|kindly|note|n\.b|important)\b', re.IGNORECASE)
MAX_QUESTION_WORDS = 12


def _items_in(box, items, page):
    """OCR items on `page` that overlap box (a LayoutLM entity can be part of an OCR line)."""
    return [item for item in items if item['page'] == page
            and min(box[2], item['box'][2]) > max(box[0], item['box'][0])
            and min(box[3], item['box'][3]) > max(box[1], item['box'][1])]


def _is_instruction(text):
    """Sentences telling the user what to do are not fields, even if tagged as questions."""
    return bool(INSTRUCTION_START.match(text)) or (
        len(text.split()) > MAX_QUESTION_WORDS and not text.rstrip().endswith('?'))


def _layoutlm_candidates(items, pages):
    """Return (label candidates, other LayoutLM entities: answers/headers/other text)."""
    from layout_lm import extract_entities
    entities = extract_entities(items, pages)
    questions = [e for e in entities if e['kind'] == 'question']
    others = [e for e in entities if e['kind'] != 'question']

    # Join question pieces that sit side by side on one row (the model sometimes splits a label).
    questions.sort(key=lambda e: (e['page'], e['box'][1], e['box'][0]))
    merged = []
    for entity in questions:
        last = merged[-1] if merged else None
        height = entity['box'][3] - entity['box'][1]
        if (last and last['page'] == entity['page'] and _same_row(last['box'], entity['box'])
                and 0 <= entity['box'][0] - last['box'][2] <= height):
            last['text'] += ' ' + entity['text']
            last['box'] = union_box([last['box'], entity['box']])
            last['confidence'] = min(last['confidence'], entity['confidence'])
        else:
            merged.append(dict(entity))

    candidates = []
    for entity in merged:
        label = clean_label(entity['text'])
        if not re.search(r'[A-Za-z]{2,}', label) or is_option_word(label):
            others.append(entity)
            continue
        candidates.append({
            'label': label,
            'label_box': entity['box'],
            'page': entity['page'],
            'confidence': entity['confidence'],
            'source': 'layoutlm',
            'label_items': _items_in(entity['box'], items, entity['page']),
        })
    candidates, _ = _merge_wrapped_labels(candidates, items)
    # Instructions are dropped after merging, so their wrapped second lines go with them.
    kept = []
    for candidate in candidates:
        # Check the whole OCR line too: the model may split 'Please' off its sentence.
        if _is_instruction(candidate['label']) or any(
                INSTRUCTION_START.match(item['text']) for item in candidate['label_items']):
            others.append({'kind': 'other', 'text': candidate['label'],
                           'box': candidate['label_box'], 'page': candidate['page']})
        else:
            kept.append(candidate)
    return kept, others


def _slug(label, used):
    base = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')[:40].strip('_') or 'field'
    slug, number = base, 2
    while slug in used:
        slug, number = f'{base}_{number}', number + 1
    used.add(slug)
    return slug


def _finish(candidates, items, pages, entities=()):
    """Add answer_box, type, id and needs_review to each label candidate.
    entities = non-question LayoutLM entities (answers are used; other text blocks empty space)."""
    answers = [e for e in entities if e['kind'] == 'answer']
    blockers = [{'text': e['text'], 'box': e['box'], 'page': e['page']}
                for e in entities if e['kind'] != 'answer']
    regions, heights = {}, {}
    for page in {c['page'] for c in candidates}:
        page_items = [item for item in items if item['page'] == page]
        heights[page] = median_text_height(page_items)
        regions[page] = detect_regions(pages[page - 1], heights[page], page_items)
    # Text at or just right of a checkbox is an option of another field, not a label.
    candidates = [c for c in candidates
                  if not next_to_checkbox(c['label_box'], regions[c['page']]['checkboxes'],
                                          heights[c['page']])]
    fields, used_ids = [], set()
    candidates = sorted(candidates, key=lambda c: (c['page'], c['label_box'][1], c['label_box'][0]))
    for candidate in candidates:
        page = candidate['page']
        page_items = [item for item in items if item['page'] == page]
        image = pages[page - 1]
        text_height = heights[page]
        box = candidate['label_box']

        # Do not let an answer area run into the next label on the same row.
        next_labels = [c['label_box'][0] for c in candidates
                       if c is not candidate and c['page'] == page
                       and _same_row(box, c['label_box']) and c['label_box'][0] > box[2]]
        right_limit = min(next_labels) - text_height * 0.3 if next_labels else None

        page_answers = [a for a in answers if a['page'] == page]
        blocking = page_items + [b for b in blockers if b['page'] == page]
        answer_box, method = find_answer_box(
            box, blocking, regions[page], (image.shape[1], image.shape[0]), text_height,
            page_answers, candidate['label_items'], right_limit)

        limit = right_limit if right_limit is not None else image.shape[1]
        checkboxes = nearby_checkboxes(box, regions[page], page_items, text_height, limit)
        options = [item['text'] for item in page_items
                   if _same_row(box, item['box'], 0.3) and box[2] < item['box'][0] < limit
                   and (is_option_word(item['text'])
                        or next_to_checkbox(item['box'], checkboxes, text_height))]
        field_type = guess_type(candidate['label'], options, len(checkboxes))

        confidence = round(float(candidate['confidence']), 3)
        fields.append({
            'id': _slug(candidate['label'], used_ids),
            'label': candidate['label'],
            'label_box': [int(v) for v in box],
            'answer_box': [int(v) for v in answer_box] if answer_box else None,
            'type': field_type,
            'source': candidate['source'],
            'confidence': confidence,
            'needs_review': confidence < REVIEW_BELOW_CONFIDENCE or method in GUESSED_METHODS,
            'page': page,
            'answer_method': method,
            'options': options,
        })
    return fields


def find_fields(ocr_items, image_path, method='auto', clean=True):
    """OCR items (Shape 1) + the form file they came from -> list of fields (Shape 2).

    method: 'auto' (LayoutLM, falling back to rules), 'layoutlm', or 'rules'.
    """
    from ocr import prepare_pages
    pages = prepare_pages(image_path, clean)
    items = clean_items(ocr_items)
    entities = []
    candidates = None
    if method in ('auto', 'layoutlm'):
        try:
            candidates, entities = _layoutlm_candidates(items, pages)
            if not candidates:
                raise RuntimeError('LayoutLM found no question/label text.')
        except Exception as error:
            if method == 'layoutlm':
                raise
            print(f'LayoutLM failed ({error!r}); using rule-based fallback.', file=sys.stderr)
            candidates, entities = None, []
    if candidates is None:
        candidates = extract_fields(items)
    return _finish(candidates, items, pages, entities)


def explain_fields_in_language(fields, language):
    """TODO (later stage): explain each field in Hausa/Yoruba/Igbo with the glossary + N-ATLaS."""
    raise NotImplementedError('N-ATLaS explanation is not part of this prototype yet.')


def main():
    parser = argparse.ArgumentParser(description='Find fields on a form image or PDF.')
    parser.add_argument('input', help='form image (photo/scan) or PDF')
    parser.add_argument('--ocr-json', help='reuse OCR output from this file instead of running OCR')
    parser.add_argument('--ocr-out', default='ocr_output.json')
    parser.add_argument('--fields', default='form_fields.json')
    parser.add_argument('--boxes', default='form_boxes.png')
    parser.add_argument('--method', choices=['auto', 'layoutlm', 'rules'], default='auto')
    parser.add_argument('--no-clean', action='store_true', help='skip photo cleaning')
    args = parser.parse_args()
    clean = not args.no_clean

    if args.ocr_json:
        with open(args.ocr_json, encoding='utf-8') as file:
            ocr_items = json.load(file)
    else:
        from ocr import read_form
        ocr_items = read_form(args.input, clean)
        with open(args.ocr_out, 'w', encoding='utf-8') as file:
            json.dump(ocr_items, file, indent=2, ensure_ascii=False)

    fields = find_fields(ocr_items, args.input, args.method, clean)
    with open(args.fields, 'w', encoding='utf-8') as file:
        json.dump(fields, file, indent=2, ensure_ascii=False)
    draw_boxes(fields, args.input, args.boxes, clean=clean)

    for field in fields:
        flag = ' (review)' if field['needs_review'] else ''
        print(f"p{field['page']} {field['label']!r:45} {field['type']:8} "
              f"{field['source']}/{field['answer_method']}{flag}")
    print(f'{len(fields)} fields found. Saved {args.fields} and {args.boxes} '
          '(red = label, blue = answer area).')


if __name__ == '__main__':
    main()
