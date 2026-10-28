"""Form understanding: OCR items + page images -> list of fields (Shape 2).

LayoutLM is the primary method; layout_rules is used only if LayoutLM fails or finds nothing.

Usage:  python layout.py FORM_IMAGE_OR_PDF [--fields form_fields.json] [--boxes form_boxes.png]
"""
import argparse
import json
import re
import sys
from collections import Counter

from answer_areas import (continuation_lines, detect_regions, find_answer_box, median_text_height,
                          nearby_checkboxes, next_to_checkbox)
from field_types import guess_type
from layout_rules import (_merge_wrapped_labels, clean_items, clean_label, draw_boxes,
                          extract_fields, is_option_word, union_box)

REVIEW_BELOW_CONFIDENCE = 0.6
# Answer areas found this way are plausible but often wrong (e.g. a section heading's own row).
GUESSED_METHODS = {'own_cell', 'empty_right', 'empty_below', 'none'}
# Answer areas drawn on the form itself: text tagged as a heading that has one is a field.
DRAWN_METHODS = {'table_cell', 'box', 'underline', 'checkboxes', 'layoutlm_answer',
                 'box_below', 'underline_below', 'line_above'}
# A label alone in a table row at least this wide (share of the page's text width) is a heading.
SECTION_ROW_SHARE = 0.6
# A label with only a guessed answer area, printed this much taller than the page's median
# text, is a heading (headings are usually set larger).
SECTION_TEXT_SCALE = 1.15


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


def _layoutlm_candidates(items, pages, entities=None):
    """Return (label candidates, other LayoutLM entities: answers/headers/other text).
    entities: reuse an earlier extract_entities() result instead of running the model again."""
    from layout_lm import extract_entities
    entities = extract_entities(items, pages) if entities is None else entities
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
        # A long question wrapped over lines that ends in ':' or '?' asks for an answer.
        long_but_prompt = candidate.get('ends_like_prompt') and not INSTRUCTION_START.match(candidate['label'])
        if (_is_instruction(candidate['label']) and not long_but_prompt) or any(
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


def _finish(candidates, items, pages, entities=(), checkbox_rule=False):
    """Add answer_box, type, id and needs_review to each label candidate.
    entities = non-question LayoutLM entities (answers are used; other text blocks empty space).
    checkbox_rule (PDFs): a checkbox group is 'choice', a lone checkbox is 'yes_no'."""
    answers = [e for e in entities if e['kind'] == 'answer']
    header_boxes = [c['label_box'] for c in candidates if c.get('from_header')]
    blockers = [{'text': e['text'], 'box': e['box'], 'page': e['page']}
                for e in entities if e['kind'] != 'answer' and e['box'] not in header_boxes]
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
        # A question wrapped over lines: its answer sits next to its last line.
        anchor = candidate.get('anchor_box') or box

        # Do not let an answer area run into the next label on the same row.
        next_labels = [c['label_box'][0] for c in candidates
                       if c is not candidate and c['page'] == page
                       and _same_row(anchor, c['label_box']) and c['label_box'][0] > anchor[2]]
        right_limit = min(next_labels) - text_height * 0.3 if next_labels else None

        page_answers = [a for a in answers if a['page'] == page]
        blocking = page_items + [b for b in blockers if b['page'] == page]
        answer_box, method = find_answer_box(
            anchor, blocking, regions[page], (image.shape[1], image.shape[0]), text_height,
            page_answers, candidate['label_items'], right_limit)

        answer_lines = []
        if method in ('underline', 'underline_below', 'line_above'):
            more = continuation_lines(answer_box, regions[page]['lines'], page_items, text_height)
            if more:  # an answer ruled over several lines: one area, filled line by line
                answer_lines = [list(answer_box)] + more
                answer_box = [min(b[0] for b in answer_lines), answer_box[1],
                              max(b[2] for b in answer_lines), more[-1][3]]

        limit = right_limit if right_limit is not None else image.shape[1]
        checkboxes = nearby_checkboxes(anchor, regions[page], page_items, text_height, limit)
        option_items = [item for item in page_items
                        if _same_row(anchor, item['box'], 0.3) and anchor[2] < item['box'][0] < limit
                        and (is_option_word(item['text'])
                             or next_to_checkbox(item['box'], checkboxes, text_height))]
        options = [item['text'] for item in option_items]
        field_type = guess_type(candidate['label'], options, len(checkboxes))
        if checkbox_rule and method == 'checkboxes':
            field_type = 'choice' if len(checkboxes) >= 2 else 'yes_no'
        # The checkbox each option belongs to (the nearest one to the option's left), for filling.
        option_boxes = []
        for item in option_items:
            if checkboxes:
                left_of = [c for c in checkboxes if c[0] <= item['box'][0] + text_height
                           and _same_row(c, item['box'], 0.3)]
                if left_of:
                    option_boxes.append(max(left_of, key=lambda c: c[0]))

        confidence = round(float(candidate['confidence']), 3)
        section_reason = _section_reason(candidate, method, box, regions[page], page_items, text_height)
        fields.append({
            'id': _slug(candidate['label'], used_ids),
            'label': candidate['label'],
            'label_box': [int(v) for v in box],
            'answer_box': [int(v) for v in answer_box] if answer_box else None,
            'type': field_type,
            'source': candidate['source'],
            'confidence': confidence,
            'needs_review': (confidence < REVIEW_BELOW_CONFIDENCE or method in GUESSED_METHODS
                             or bool(candidate.get('from_header'))),
            'page': page,
            'answer_method': method,
            'options': options,
            'option_boxes': [[int(v) for v in b] for b in option_boxes]
            if len(option_boxes) == len(options) else [],
            'answer_lines': [[int(v) for v in b] for b in answer_lines],
            'section_reason': section_reason,
        })
    return fields


def _section_reason(candidate, method, label_box, regions, page_items, text_height=None):
    """Why this label is a section heading rather than a field, or None.
    Generic: uses the model's own 'header' tag, the shape of the row and the text size,
    never the wording."""
    from answer_areas import _cell_of
    if candidate.get('from_header'):
        return None if method in DRAWN_METHODS else candidate.get('heading_reason', 'layoutlm_header')
    if method == 'none':
        return 'no_answer_area'
    line_heights = [item['box'][3] - item['box'][1] for item in candidate.get('label_items', [])]
    if (text_height and method in GUESSED_METHODS and line_heights
            and min(line_heights) >= SECTION_TEXT_SCALE * text_height):
        return 'larger_text_no_drawn_area'
    if method == 'own_cell':
        cell = _cell_of(label_box, regions['cells'])
        left = min(item['box'][0] for item in page_items)
        right = max(item['box'][2] for item in page_items)
        if cell and (cell[2] - cell[0]) >= SECTION_ROW_SHARE * max(1, right - left):
            return 'alone_in_full_width_row'
    return None


def _split_sections(entries):
    """Separate section headings from fields; link every field to the nearest heading above it."""
    fields, sections = [], []
    for entry in sorted(entries, key=lambda e: (e['page'], e['label_box'][1], e['label_box'][0])):
        reason = entry.pop('section_reason', None)
        if reason:
            sections.append({
                'id': 'section_' + entry['id'],
                'title': entry['label'],
                'box': entry['label_box'],
                'page': entry['page'],
                'source': entry['source'],
                'reason': reason,
                'confidence': entry['confidence'],
                # The model's own header tag is trusted; geometry-only headings are a guess.
                'needs_review': reason != 'layoutlm_header' or entry['confidence'] < REVIEW_BELOW_CONFIDENCE,
            })
        else:
            fields.append(entry)
    _assign_sections(fields, sections)
    return fields, sections


def _inside(box, outer, share=0.8):
    """True if at least `share` of box's area lies within outer."""
    ix = max(0, min(box[2], outer[2]) - max(box[0], outer[0]))
    iy = max(0, min(box[3], outer[3]) - max(box[1], outer[1]))
    return ix * iy >= share * max(1, (box[2] - box[0]) * (box[3] - box[1]))


def _whole_line(entity, items):
    """(text, box) of the text lines a heading entity sits in: the model may tag only part of a
    heading (e.g. 'information' of 'Other information') as header."""
    lines = _items_in(entity['box'], items, entity['page'])
    if not lines:
        return entity['text'], entity['box']
    lines.sort(key=lambda item: (item['box'][1], item['box'][0]))
    return ' '.join(item['text'] for item in lines), union_box([item['box'] for item in lines])


def _header_candidates(entities, items):
    """Text the model tagged as a heading, as label candidates (checked for an answer area)."""
    candidates, seen = [], set()
    for entity in entities:
        if entity['kind'] != 'header':
            continue
        text, box = _whole_line(entity, items)
        if (entity['page'], tuple(box)) in seen:
            continue  # two header pieces of one line
        seen.add((entity['page'], tuple(box)))
        entity = dict(entity, text=text, box=box)
        label = clean_label(entity['text'])
        if not re.search(r'[A-Za-z]{2,}', label) or _is_instruction(label):
            continue
        candidates.append({'label': label, 'label_box': entity['box'], 'page': entity['page'],
                           'confidence': entity['confidence'], 'source': 'layoutlm',
                           'label_items': _items_in(entity['box'], items, entity['page']),
                           'from_header': True})
    return candidates


def _caps_heading_candidates(items, candidates):
    """Lines printed in capitals (2+ words, alone on their row, no ':' and no final '.') that no
    label candidate covers: headings the model left untagged ('other'). Checked for an answer
    area like the model's own headers."""
    found = []
    for item in items:
        text = item['text'].strip()
        words = re.findall(r'[A-Za-z]{2,}', text)
        if (len(words) < 2 or not ''.join(words).isupper() or ':' in text or text.endswith('.')
                or _is_instruction(text)):
            continue
        if any(c['page'] == item['page'] and _inside(item['box'], c['label_box'], 0.5) for c in candidates):
            continue
        if any(other is not item and other['page'] == item['page'] and _same_row(other['box'], item['box'])
               for other in items):
            continue
        found.append({'label': clean_label(text), 'label_box': list(item['box']), 'page': item['page'],
                      'confidence': 0.5, 'source': 'rules', 'label_items': [item],
                      'from_header': True, 'heading_reason': 'caps_line'})
    return found


def find_fields_and_sections(ocr_items, image_path, method='auto', clean=True, entities=None,
                             checkbox_rule=False):
    """Flat forms: words (Shape 1) + the form file -> (fields (Shape 2), section headings).

    method: 'auto' (LayoutLM, falling back to rules), 'layoutlm', or 'rules'.
    entities: reuse an earlier layout_lm.extract_entities() result.
    checkbox_rule: see _finish (on for PDFs; the photo path keeps guess_type's types).
    """
    from ocr import prepare_pages
    pages = prepare_pages(image_path, clean)
    items = clean_items(ocr_items)
    others = []
    candidates = None
    if method in ('auto', 'layoutlm'):
        try:
            candidates, others = _layoutlm_candidates(items, pages, entities)
            if not candidates:
                raise RuntimeError('LayoutLM found no question/label text.')
            headers = _header_candidates(others, items)
            # A 'question' piece inside a heading's line is part of that heading, not a field.
            candidates = [c for c in candidates if not any(
                h['page'] == c['page'] and _inside(c['label_box'], h['label_box']) for h in headers)]
            candidates += headers
        except Exception as error:
            if method == 'layoutlm':
                raise
            print(f'LayoutLM failed ({error!r}); using rule-based fallback.', file=sys.stderr)
            candidates, others = None, []
    if candidates is None:
        candidates = extract_fields(items)
    candidates += _caps_heading_candidates(items, candidates)
    return _split_sections(_finish(candidates, items, pages, others, checkbox_rule))


def find_fields(ocr_items, image_path, method='auto', clean=True):
    """OCR items (Shape 1) + the form file they came from -> list of fields (Shape 2).
    Section headings are left out; use find_fields_and_sections() to get them too."""
    return find_fields_and_sections(ocr_items, image_path, method, clean)[0]


def _assign_sections(fields, sections):
    for field in fields:
        anchor = field['label_box'] or field['answer_box']
        above = [s for s in sections if (s['page'], s['box'][1]) <= (field['page'], anchor[1])]
        field['section'] = above[-1]['id'] if above else None


def _fillable_sections(entities, fields, items):
    """Headings on a fillable PDF: text the model tagged as a header that is not a field label."""
    labels = [(f['page'], f['label_box']) for f in fields if f['label_box']]
    widgets = [(w['page'], w['box']) for f in fields for w in f['pdf']['widgets']]
    sections, used, seen = [], set(), set()
    for entity in entities:
        if entity['kind'] == 'header':
            text, box = _whole_line(entity, items)
            if (entity['page'], tuple(box)) in seen:
                continue  # two header pieces of one line
            seen.add((entity['page'], tuple(box)))
            entity = dict(entity, text=text, box=box)
        title = clean_label(entity['text'])
        if (entity['kind'] != 'header' or not re.search(r'[A-Za-z]{2,}', title)
                or _is_instruction(title)):
            continue
        box = entity['box']
        if any(page == entity['page'] and min(box[2], b[2]) > max(box[0], b[0])
               and min(box[3], b[3]) > max(box[1], b[1]) for page, b in labels + widgets):
            continue
        sections.append({'id': 'section_' + _slug(title, used), 'title': title, 'box': box,
                         'page': entity['page'], 'source': 'layoutlm', 'reason': 'layoutlm_header',
                         'confidence': round(float(entity['confidence']), 3),
                         'needs_review': entity['confidence'] < REVIEW_BELOW_CONFIDENCE})
    return sorted(sections, key=lambda s: (s['page'], s['box'][1], s['box'][0]))


PDF_KINDS = ('fillable', 'flat_text', 'flat_scanned', 'mixed')


def page_kind(page):
    """'fillable' (has widgets), 'flat_text' (words from the text layer) or 'flat_scanned'."""
    if page.get('widgets'):
        return 'fillable'
    return 'flat_text' if str(page.get('word_source', '')).startswith('pdf_text') else 'flat_scanned'


def pdf_kind(pages):
    """The pages' common kind, or 'mixed' when pages differ. 'instructions' pages (no widgets and
    no real fields, in a PDF that has widgets) do not count."""
    kinds = {page.get('kind') or page_kind(page) for page in pages} - {'instructions'}
    return kinds.pop() if len(kinds) == 1 else 'mixed'


def _anchor(field):
    box = field['label_box'] or field['answer_box'] or [0, 0, 0, 0]
    return field['page'], box[1], box[0]


def _add_keys(fields):
    """Readable key next to each id (answers.json may use either). Flat ids are already made from
    the label, so key = id; fillable keys come from the label, with a suffix on collisions with
    another key or another field's id."""
    ids = {f['id'] for f in fields}
    used = {f['id'] for f in fields if f.get('pdf_field_name') is None}
    for field in fields:
        if field.get('pdf_field_name') is None:
            field['key'] = field['id']
            continue
        taken = used | (ids - {field['id']})
        base = _slug(field['label'] or '', set())
        key, number = base, 2
        while key in taken:
            key, number = f'{base}_{number}', number + 1
        used.add(key)
        field['key'] = key


def _flag_shared_labels(fields):
    """Fields with the same label (e.g. several boxes under one printed label) cannot be told
    apart by a user who only hears the label: each one is reviewed."""
    def norm(label):
        return re.sub(r'[^a-z0-9]+', ' ', label.lower()).strip()
    counts = Counter(norm(f['label']) for f in fields if f.get('label'))
    for field in fields:
        if field.get('label') and counts[norm(field['label'])] > 1:
            field['needs_review'] = True


def analyse_form(path, ocr_items=None, method='auto', clean=True):
    """Whole pipeline for one form -> one JSON-ready object:
    {'form': {source_file, pdf_kind, pages: [{page, width_px, height_px, dpi, ...}], method, notes},
     'sections': [...], 'fields': [...]}.
    Pages with widgets use the AcroForm fields; other pages use the flat path. In a PDF with
    widgets, flagged flat fields are dropped, and a page left with no fields is 'instructions';
    'mixed' means a page without widgets still holds real fields. All boxes are pixels of the page images from ocr.prepare_pages (PDFs: the dpi render)."""
    from pathlib import Path

    from ocr import PDF_SUFFIXES, prepare_pages, read_form
    items = read_form(path, clean) if ocr_items is None else ocr_items
    pages = prepare_pages(path, clean)
    is_pdf = Path(path).suffix.lower() in PDF_SUFFIXES
    if is_pdf:
        from pdf_input import describe_pdf
        info = describe_pdf(path, items)
    else:  # photo fallback: an image is a scanned flat page
        info = {'file': str(path), 'dpi': None,
                'pages': [{'page': n, 'width_px': int(p.shape[1]), 'height_px': int(p.shape[0]),
                           'dpi': None, 'word_source': 'ocr'} for n, p in enumerate(pages, start=1)]}
    notes, entities = [], None
    if method != 'rules':
        try:
            from layout_lm import extract_entities
            entities = extract_entities(clean_items(items), pages)
        except Exception as error:
            if method == 'layoutlm':
                raise
            notes.append(f'LayoutLM failed ({error!r}); labels come from rules/nearby text.')

    for page in info['pages']:
        page['kind'] = page_kind(page)
    widget_pages = {p['page'] for p in info['pages'] if p['kind'] == 'fillable'}
    fields, sections, used = [], [], []
    if widget_pages:
        from pdf_fields import find_fillable_fields
        fillable, error = find_fillable_fields(path, items, entities is not None, entities)
        if error:
            notes.append(f'LayoutLM label linking failed ({error}).')
        on_pages = [e for e in entities or [] if e['page'] in widget_pages]
        sections += _fillable_sections(on_pages, fillable, clean_items(items))
        fields += fillable
        used.append('acroform+layoutlm' if entities is not None else 'acroform')
    flat_items = [item for item in items if item['page'] not in widget_pages]
    if flat_items:
        flat_entities = None if entities is None else [
            e for e in entities if e['page'] not in widget_pages]
        flat, flat_sections = find_fields_and_sections(
            flat_items, path, 'rules' if entities is None else method, clean, flat_entities,
            checkbox_rule=is_pdf)
        if widget_pages:
            # A fillable PDF: pages without widgets are usually instructions. Only confident flat
            # fields count as real ones there; flagged ones (low confidence, guessed answer area,
            # heading-like) are dropped.
            dropped = [f for f in flat if f['needs_review']]
            if dropped:
                notes.append(f'{len(dropped)} low-confidence field(s) dropped on pages without widgets: '
                             + ', '.join(f"p{f['page']} {f['label']!r}" for f in dropped))
            flat = [f for f in flat if not f['needs_review']]
            flat_sections = [s for s in flat_sections if s['page'] in {f['page'] for f in flat}]
        taken = {f['id'] for f in fields}
        for field in flat:
            if field['id'] in taken:  # mixed PDF: a flat id equal to an AcroForm name
                field['id'] = _slug(field['id'], taken)
            field.update(pdf_field_name=None, required=None)  # flat pages print no 'required' flag
        seen = {s['id'] for s in sections}
        for section in flat_sections:
            if section['id'] in seen:
                section['id'] = _slug(section['id'], seen)
        sections += flat_sections
        fields += flat
        if flat or not widget_pages:  # instructions pages add no method
            used.append('+'.join(sorted({f['source'] for f in flat})) or 'none')
    if widget_pages:
        field_pages = {f['page'] for f in fields}
        for page in info['pages']:
            if page['kind'] != 'fillable' and page['page'] not in field_pages:
                page['kind'] = 'instructions'
    for field in fields:  # only AcroForm fields can be read-only, calculated or hidden
        field.setdefault('ask_user', True)
        field.setdefault('skip_reason', None)
        field.setdefault('hidden', False)
        field.setdefault('editable', False)
    _flag_shared_labels(fields)
    fields.sort(key=_anchor)
    sections.sort(key=lambda s: (s['page'], s['box'][1], s['box'][0]))
    _assign_sections(fields, sections)
    _add_keys(fields)
    form = {'source_file': info['file'], 'pdf_kind': pdf_kind(info['pages']),
            'pages': info['pages'], 'method': ', '.join(used) or 'none', 'notes': notes}
    return {'form': form, 'sections': sections, 'fields': fields}


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

    form = analyse_form(args.input, ocr_items, args.method, clean)
    fields, sections = form['fields'], form['sections']
    with open(args.fields, 'w', encoding='utf-8') as file:
        json.dump(form, file, indent=2, ensure_ascii=False)
    draw_boxes(fields, args.input, args.boxes, clean=clean, sections=sections)

    info = form['form']
    pages = ', '.join(f"p{p['page']}={p['kind']}/{p.get('word_source')}" for p in info['pages'])
    print(f"pdf_kind={info['pdf_kind']} method={info['method']} pages: {pages}")
    for note in info['notes']:
        print('NOTE:', note)
    for section in sections:
        flag = ' (review)' if section['needs_review'] else ''
        print(f"p{section['page']} SECTION {section['title']!r} [{section['reason']}]{flag}")
    for field in fields:
        flag = ' (review)' if field['needs_review'] else ''
        how = field.get('label_source') or field['answer_method']
        print(f"p{field['page']} {field['key']:28} {field['label']!r:45} {field['type']:8} "
              f"{field['source']}/{how}{flag}")
    print(f'{len(fields)} fields, {len(sections)} sections. Saved {args.fields} and {args.boxes} '
          '(red = label, blue = answer area, green = section).')


if __name__ == '__main__':
    main()
