"""Fillable PDFs: read every AcroForm field with pypdf and link it to its printed label.

Boxes are converted to pixels of the PDF_DPI render of the page (same space as pdf_input words).
Label linking uses LayoutLM question entities first; tooltip, then nearby text are fallbacks
(flagged needs_review). Field names are not labels. Nothing here knows any particular form.
"""
import re

from field_types import guess_type
from ocr import prepare_pages

# ---- Config (all distances relative to the page's median text height) ----
LEFT_MAX = 15        # a label left of a widget may be at most this many text heights away
ABOVE_MAX = 2.5      # ...or this far above it
RIGHT_MAX = 3        # checkbox/radio labels and option texts sit right of the box, this close
ROW_SHARE = 0.3      # vertical overlap (share of the smaller height) to count as the same row
INSIDE_SHARE = 0.5   # text covered this much by a widget is the widget's value, not a label
REVIEW_BELOW_CONFIDENCE = 0.6
GROUP_ROW_GAP = 12      # lone checkboxes in one row this close (text heights) form one group
GROUP_COLUMN_GAP = 1.5  # ...or stacked, left edges aligned, at most this far apart
FALLBACK_CONFIDENCE = {'tooltip': 0.5, 'nearby_text': 0.4, 'none': 0.0}
ABOVE_LEFT_MAX = 3   # a prompt above-left of a widget may end at most this far left of it
COMPETE_GAP = 2      # another line above, this many text heights nearer or farther, competes for the label
PROMPT_END = re.compile(r'[:?]\s*$')  # a prompt ends with ':' or '?'; a hint or example usually not

# Field flags (PDF 32000-1, tables 221, 226, 228, 230); bit n -> 1 << (n - 1).
FLAG_BITS = {
    'read_only': 1, 'required': 2, 'no_export': 3,
    'multiline': 13, 'password': 14, 'no_toggle_to_off': 15, 'radio': 16, 'pushbutton': 17,
    'combo': 18, 'edit': 19, 'multi_select': 22, 'do_not_spell_check': 23, 'comb': 25,
}
ANNOT_HIDDEN = 1 << 1  # annotation flag: widget is not shown

# Format actions written by Acrobat-style forms (AFNumber_Format, AFDate_FormatEx, ...).
FORMAT_HINTS = [
    ('date', r'AFDate_|AFTime_'),
    ('phone', r'AFSpecial_(Format|Keystroke)\(\s*2\s*\)'),
    ('number', r'AFNumber_|AFPercent_|AFSpecial_(Format|Keystroke)\(\s*[013]\s*\)'),
]
TEXT_TYPES_FROM_WORDS = {'number', 'date', 'email', 'phone'}


# ---------- reading fields ----------

def _get(node, key):
    """Field attribute, inherited from parent fields if the widget does not have it."""
    while node is not None:
        if key in node:
            return node[key]
        parent = node.get('/Parent')
        node = parent.get_object() if parent is not None else None
    return None


def _full_name(widget):
    names, node = [], widget
    while node is not None:
        if '/T' in node:
            names.append(str(node['/T']))
        parent = node.get('/Parent')
        node = parent.get_object() if parent is not None else None
    return '.'.join(reversed(names))


def _text(value):
    if value is None:
        return None
    if hasattr(value, 'get_object'):
        value = value.get_object()
    if hasattr(value, 'get_data'):
        return value.get_data().decode('latin-1', 'replace')
    return str(value)


def _format_script(widget):
    actions = _get(widget, '/AA')
    if actions is None:
        return ''
    actions = actions.get_object()
    scripts = []
    for key in ('/F', '/K'):  # format and keystroke actions
        if key in actions:
            scripts.append(_text(actions[key].get_object().get('/JS')) or '')
    return ' '.join(scripts)


def _options(widget):
    """(display texts, export values) of a choice field's /Opt."""
    raw = _get(widget, '/Opt')
    if raw is None:
        return [], []
    displays, exports = [], []
    for entry in raw.get_object():
        entry = entry.get_object()
        if isinstance(entry, list) and len(entry) == 2:
            exports.append(_text(entry[0]))
            displays.append(_text(entry[1]))
        else:
            exports.append(_text(entry))
            displays.append(_text(entry))
    return displays, exports


def _export_value(widget):
    """On-state name of a checkbox/radio widget (the /AP /N key that is not /Off)."""
    appearance = widget.get('/AP')
    if appearance is None:
        return None
    normal = appearance.get_object().get('/N')
    if normal is None or not hasattr(normal.get_object(), 'keys'):
        return None
    states = [str(k).lstrip('/') for k in normal.get_object().keys() if str(k) != '/Off']
    return states[0] if states else None


def read_on_states(reader):
    """{full field name: [on-state names of each widget, in page order]} read from the PDF itself
    (the /AP /N and /D keys that are not /Off). Used when filling, so the JSON is not trusted."""
    states = {}
    for page in reader.pages:
        for ref in page.get('/Annots') or []:
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget' or not _full_name(widget):
                continue
            names = []
            appearance = widget.get('/AP')
            for key in ('/N', '/D'):
                group = appearance.get_object().get(key) if appearance is not None else None
                if group is not None and hasattr(group.get_object(), 'keys'):
                    names += [str(k).lstrip('/') for k in group.get_object().keys()
                              if str(k) != '/Off' and str(k).lstrip('/') not in names]
            states.setdefault(_full_name(widget), []).append(names)
    return states


def _to_pixels(rect, page, size_px):
    """PDF rect (points, bottom-left origin, unrotated) -> render pixels (top-left, rotated)."""
    crop = page.cropbox
    left, bottom, right, top = float(crop.left), float(crop.bottom), float(crop.right), float(crop.top)
    width_pt, height_pt = right - left, top - bottom
    rotation = (page.rotation or 0) % 360
    points = []
    for x, y in ((rect[0], rect[1]), (rect[2], rect[3])):
        u, v = x - left, top - y  # unrotated, top-left origin
        if rotation == 90:
            u, v = height_pt - v, u
        elif rotation == 180:
            u, v = width_pt - u, height_pt - v
        elif rotation == 270:
            u, v = v, width_pt - u
        points.append((u, v))
    shown_w, shown_h = (height_pt, width_pt) if rotation in (90, 270) else (width_pt, height_pt)
    sx, sy = size_px[0] / shown_w, size_px[1] / shown_h
    xs = [p[0] * sx for p in points]
    ys = [p[1] * sy for p in points]
    return [int(round(max(0, min(size_px[0], min(xs))))), int(round(max(0, min(size_px[1], min(ys))))),
            int(round(max(0, min(size_px[0], max(xs))))), int(round(max(0, min(size_px[1], max(ys)))))]


def read_acroform(path):
    """Every AcroForm field with its widgets. Returns a list of raw field dicts (pixel boxes)."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    renders = prepare_pages(path, clean=False)
    fields = {}
    for page_number, (page, render) in enumerate(zip(reader.pages, renders), start=1):
        size_px = (render.shape[1], render.shape[0])
        for ref in page.get('/Annots') or []:
            widget = ref.get_object()
            if widget.get('/Subtype') != '/Widget':
                continue
            name = _full_name(widget)
            if not name:
                continue
            flags_value = int(_get(widget, '/Ff') or 0)
            field = fields.get(name)
            if field is None:
                displays, exports = _options(widget)
                max_length = _get(widget, '/MaxLen')
                field = fields[name] = {
                    'name': name,
                    'pdf_type': str(_get(widget, '/FT') or '').lstrip('/'),
                    'flags': {flag: bool(flags_value & (1 << (bit - 1))) for flag, bit in FLAG_BITS.items()},
                    'flags_value': flags_value,
                    'tooltip': _text(_get(widget, '/TU')),
                    'max_length': int(max_length) if max_length is not None else None,
                    'default_value': _text(_get(widget, '/DV')),
                    'value': _text(_get(widget, '/V')),
                    'option_texts': displays,
                    'option_values': exports,
                    'format_script': _format_script(widget),
                    'widgets': [],
                }
            rect = [float(v) for v in widget['/Rect']]
            rect = [min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])]
            field['widgets'].append({
                'page': page_number,
                'box': _to_pixels(rect, page, size_px),
                'rect_pt': [round(v, 2) for v in rect],
                'export_value': _export_value(widget),
                'hidden': bool(int(widget.get('/F', 0)) & ANNOT_HIDDEN),
            })
    return list(fields.values())


# ---------- linking labels ----------

def _overlap(a1, a2, b1, b2):
    return max(0, min(a2, b2) - max(a1, b1))


def _same_row(a, b):
    return _overlap(a[1], a[3], b[1], b[3]) >= ROW_SHARE * max(1, min(a[3] - a[1], b[3] - b[1]))


def _covered(box, other):
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    return _overlap(box[0], box[2], other[0], other[2]) * _overlap(box[1], box[3], other[1], other[3]) / area


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _nearest(target, candidates, text_height, sides, exclude=()):
    """Closest candidate (dict with 'box') on the allowed sides of target, or (None, None).
    Sides are tried in the given order: a label on an earlier side beats a closer one on a
    later side (a label on the same row beats a heading just above the input)."""
    ranked = _ranked(target, candidates, text_height, sides, exclude)
    return (ranked[0][0], ranked[0][1]) if ranked else (None, None)


def _ranked(target, candidates, text_height, sides, exclude=()):
    """Every candidate on the allowed sides of target, best first: [(candidate, side, distance)]."""
    found = []
    for candidate in candidates:
        box = candidate['box']
        if any(box == other for other in exclude):
            continue
        distance, side = None, None
        if 'left' in sides and _same_row(box, target) and box[2] <= target[0] + text_height * 0.5:
            gap = target[0] - box[2]
            if gap <= LEFT_MAX * text_height:
                distance, side = max(0, gap), 'left'
        if distance is None and 'above' in sides and box[3] <= target[1] + text_height * 0.3:
            gap = target[1] - box[3]
            horizontal = (_overlap(box[0], box[2], target[0], target[2]) > 0
                          or abs(box[0] - target[0]) <= 2 * text_height)
            if gap <= ABOVE_MAX * text_height and horizontal:
                distance, side = max(0, gap), 'above'
        if distance is None and 'right' in sides and _same_row(box, target) and box[0] >= target[2] - text_height * 0.5:
            gap = box[0] - target[2]
            if gap <= RIGHT_MAX * text_height:
                distance, side = max(0, gap), 'right'
        if (distance is None and 'above_left' in sides and box[3] <= target[1] + text_height * 0.3
                and box[0] < target[0] and box[2] <= target[0] + text_height * 0.5):
            # A prompt above the input but ending before it starts ("Name:" with the box below
            # it and to the right): only used when no left/above match exists (sides order).
            gap, across = target[1] - box[3], max(0, target[0] - box[2])
            if gap <= ABOVE_MAX * text_height and across <= ABOVE_LEFT_MAX * text_height:
                distance, side = max(0, gap) + across, 'above_left'
        if distance is None:
            continue
        found.append(((sides.index(side), distance), candidate, side))
    found.sort(key=lambda entry: entry[0])
    return [(candidate, side, rank[1]) for rank, candidate, side in found]


def _line_text(box, page_items):
    """The printed text under a label box, punctuation kept (LayoutLM labels are cleaned)."""
    inside = sorted((i for i in page_items if _covered(i['box'], box) > INSIDE_SHARE),
                    key=lambda i: (i['box'][1], i['box'][0]))
    return ' '.join(i['text'] for i in inside)


def _rival_lines(target, chosen_box, page_items, text_height, sides, exclude=()):
    """Other text lines above the input about as close as the chosen label (within
    COMPETE_GAP text heights of its distance): [(item, side, distance)], nearest first."""
    ranked = _ranked(target, page_items, text_height, sides, exclude)
    chosen = next((d for c, _, d in ranked if _covered(c['box'], chosen_box) > INSIDE_SHARE), None)
    if chosen is None:
        return []
    return [(c, s, d) for c, s, d in ranked
            if _covered(c['box'], chosen_box) <= INSIDE_SHARE and abs(d - chosen) <= COMPETE_GAP * text_height]


def _field_type(raw, label, options):
    flags, kind = raw['flags'], raw['pdf_type']
    if kind == 'Tx':
        for field_type, pattern in FORMAT_HINTS:
            if re.search(pattern, raw['format_script']):
                return field_type, 'format_action'
        words = ' '.join(t for t in (label, raw['tooltip']) if t)
        guessed = guess_type(words)
        if guessed in TEXT_TYPES_FROM_WORDS:
            return guessed, 'label_words'
        return 'text', 'pdf_field'
    if kind == 'Btn':  # a group of options (even Yes/No) is a choice; a lone checkbox is yes/no
        return ('choice' if len(options) >= 2 else 'yes_no'), 'pdf_field'
    if kind == 'Ch':
        return 'choice', 'pdf_field'
    return 'unknown', 'pdf_field'  # signature fields and anything else


def _humanize(name):
    last = name.split('.')[-1]
    last = re.sub(r'\[\d+\]$', '', last)
    last = re.sub(r'([a-z])([A-Z])', r'\1 \2', last)
    return re.sub(r'[_\-]+', ' ', last).strip() or name


def _checkbox_groups(raw_fields, shown_widgets, text_height_of):
    """Lone checkboxes (separate fields, one widget each, not radio) that sit next to each other
    in a row or a column -> list of groups (each a list of raw fields, reading order, 2+)."""
    lone = [raw for raw in raw_fields
            if raw['pdf_type'] == 'Btn' and not raw['flags']['radio'] and not raw['flags']['pushbutton']
            and len(shown_widgets(raw)) == 1]
    boxes = {raw['name']: shown_widgets(raw)[0] for raw in lone}
    parent = {raw['name']: raw['name'] for raw in lone}

    def root(name):
        while parent[name] != name:
            name = parent[name]
        return name

    for i, a in enumerate(lone):
        for b in lone[i + 1:]:
            wa, wb = boxes[a['name']], boxes[b['name']]
            if wa['page'] != wb['page']:
                continue
            h = text_height_of(wa['page'])
            ba, bb = wa['box'], wb['box']
            in_row = _same_row(ba, bb) and max(bb[0] - ba[2], ba[0] - bb[2]) <= GROUP_ROW_GAP * h
            in_column = (abs(ba[0] - bb[0]) <= h
                         and max(bb[1] - ba[3], ba[1] - bb[3]) <= GROUP_COLUMN_GAP * h)
            if in_row or in_column:
                parent[root(a['name'])] = root(b['name'])
    groups = {}
    for raw in lone:
        groups.setdefault(root(raw['name']), []).append(raw)
    ordered = []
    for group in groups.values():
        if len(group) >= 2:
            group.sort(key=lambda r: (boxes[r['name']]['box'][1], boxes[r['name']]['box'][0]))
            ordered.append(group)
    return ordered


def link_fields(raw_fields, items, pages, use_layoutlm=True, entities=None):
    """Raw AcroForm fields + words on the pages -> (Shape 2 fields (source 'acroform'), error).
    entities: reuse an earlier layout_lm.extract_entities() result."""
    from answer_areas import median_text_height
    from layout_rules import clean_items

    items = clean_items(items)
    widget_boxes = {}
    for raw in raw_fields:
        for widget in raw['widgets']:
            widget_boxes.setdefault(widget['page'], []).append(widget['box'])

    def free(entries, page):
        """Text on page that is not the content of a widget."""
        return [e for e in entries if e['page'] == page
                and not any(_covered(e['box'], w) > INSIDE_SHARE for w in widget_boxes.get(page, []))]

    questions, headers, layoutlm_error = [], [], None
    if use_layoutlm and items:
        try:
            from layout import _layoutlm_candidates
            candidates, others = _layoutlm_candidates(items, pages, entities)
            questions = [{'text': c['label'], 'box': c['label_box'], 'page': c['page'],
                          'confidence': c['confidence']} for c in candidates]
            # The model sometimes tags a label as a heading; next to an input it is still a label.
            headers = [{'text': e['text'], 'box': e['box'], 'page': e['page'],
                        'confidence': e['confidence']} for e in others if e['kind'] == 'header']
        except Exception as error:  # LayoutLM missing or failed: nearby text is still used
            layoutlm_error = repr(error)

    def find_label(box, page, page_items, text_height, sides, option_boxes, tooltip):
        """(label, label_box, label_source, confidence, alternatives): LayoutLM question, then
        tooltip, then the nearest text (a LayoutLM header first). The field name (e.g. 'Text1') is
        never a label: with none of these, label is None. alternatives: other lines above the
        input about as close as the label; when there are any, the field is reviewed."""
        from layout_rules import clean_label
        label, label_box, label_source, confidence, side = None, None, 'none', None, None
        hit, side = _nearest(box, free(questions, page), text_height, sides, option_boxes)
        if hit:
            label, label_box, confidence = hit['text'], hit['box'], hit['confidence']
            label_source = f'layoutlm_{side}'
        elif tooltip and tooltip.strip():
            label, label_source = tooltip.strip(), 'tooltip'
        else:
            header_hit, side = _nearest(box, free(headers, page), text_height, sides, option_boxes)
            if header_hit:
                label, label_box = header_hit['text'], header_hit['box']
                # Tagged as a heading, so less sure: always reviewed (see needs_review below).
                confidence = min(header_hit['confidence'], REVIEW_BELOW_CONFIDENCE - 0.01)
                label_source = f'layoutlm_header_{side}'
            else:
                hit, side = _nearest(box, page_items, text_height, sides, option_boxes)
                if hit:
                    label, label_box, label_source = hit['text'], hit['box'], f'nearby_text_{side}'
        alternatives = []
        if label_box is not None and side in ('above', 'above_left'):
            # A short line right above the input (a hint, an example, a printed default) can
            # sit between the input and its real prompt: prefer the line that ends like a prompt.
            rivals = _rival_lines(box, label_box, page_items, text_height, ('above', 'above_left'),
                                  option_boxes)
            if rivals:
                prompts = [r for r in rivals if PROMPT_END.search(r[0]['text'])]
                if not PROMPT_END.search(_line_text(label_box, page_items)) and prompts:
                    old_label = label
                    rival = prompts[0][0]
                    tagged = next((q for q in free(questions, page)
                                   if _covered(rival['box'], q['box']) > INSIDE_SHARE), None)
                    label, label_box = (tagged or rival)['text'], (tagged or rival)['box']
                    side = prompts[0][1]
                    label_source = f"{'layoutlm' if tagged else 'nearby_text'}_{side}"
                    confidence = tagged['confidence'] if tagged else None
                    rivals = [r for r in rivals if r[0] is not rival]
                    alternatives.append(clean_label(old_label))
                alternatives += [clean_label(r[0]['text']) for r in rivals]
        if confidence is None:
            confidence = FALLBACK_CONFIDENCE['nearby_text' if label_source.startswith('nearby_text')
                                             else label_source]
        label = clean_label(label) if label else None
        if not label:
            return None, None, 'none', FALLBACK_CONFIDENCE['none'], []
        return label, label_box, label_source, confidence, [a for a in alternatives if a and a != label]

    def shown_widgets(raw):
        """The visible widgets on the field's first page (all widgets if none is visible)."""
        shown = [w for w in raw['widgets'] if not w['hidden']] or raw['widgets']
        return [w for w in shown if w['page'] == shown[0]['page']]

    heights = {}

    def text_height_of(page):
        if page not in heights:
            heights[page] = median_text_height([i for i in items if i['page'] == page])
        return heights[page]

    groups = _checkbox_groups(raw_fields, shown_widgets, text_height_of)
    grouped = {raw['name'] for group in groups for raw in group}

    fields = []
    for raw in raw_fields:
        if raw['pdf_type'] == 'Btn' and raw['flags']['pushbutton']:
            continue  # buttons do not hold answers
        if raw['name'] in grouped:
            continue  # an option of an independent-checkbox group (built below)
        on_page = shown_widgets(raw)
        page = on_page[0]['page']
        page_items = free(items, page)
        text_height = text_height_of(page)
        group_box = _union([w['box'] for w in on_page])
        is_box = raw['pdf_type'] == 'Btn'

        # Options: choice-list entries, or one per checkbox/radio widget (text right of it).
        option_texts, option_values, option_boxes = list(raw['option_texts']), list(raw['option_values']), []
        if is_box and len(on_page) >= 2:
            option_texts, option_values = [], []
            for widget in on_page:
                text, _ = _nearest(widget['box'], page_items, text_height, ('right',))
                option_values.append(widget['export_value'])
                option_texts.append(text['text'] if text else widget['export_value'])
                if text:
                    option_boxes.append(text['box'])

        sides = (('left', 'right', 'above', 'above_left') if is_box and len(on_page) == 1
                 else ('left', 'above', 'above_left'))
        label, label_box, label_source, confidence, alternatives = find_label(
            group_box, page, page_items, text_height, sides, option_boxes, raw['tooltip'])
        field_type, type_source = _field_type(raw, label, option_texts)
        flags = raw['flags']
        fields.append({
            'id': raw['name'],
            'label': label,
            'label_box': [int(v) for v in label_box] if label_box else None,
            'answer_box': [int(v) for v in group_box],
            'type': field_type,
            'source': 'acroform',
            'confidence': round(float(confidence), 3),
            'needs_review': (confidence < REVIEW_BELOW_CONFIDENCE
                             or not label_source.startswith('layoutlm') or bool(alternatives)
                             or label_source.endswith('above_left')),
            'page': page,
            'pdf_field_name': raw['name'],
            'required': flags['required'],  # the PDF's own Required flag, never guessed
            'answer_method': 'acroform_widget',
            'options': option_texts,
            'label_source': label_source,
            'label_alternatives': alternatives,
            'type_source': type_source,
            'pdf': {
                'name': raw['name'],
                'field_type': raw['pdf_type'],
                'flags': {k: v for k, v in flags.items() if v},
                'required': flags['required'],
                'read_only': flags['read_only'],
                'tooltip': raw['tooltip'],
                'max_length': raw['max_length'],
                'default_value': raw['default_value'],
                'value': raw['value'],
                'option_values': option_values,
                'format_script': raw['format_script'] or None,
                'widgets': raw['widgets'],
            },
        })

    # Independent checkboxes (one field each) side by side or stacked: one 'choice' field that
    # takes a list of values. Always reviewed: the grouping is inferred from the layout.
    for group in groups:
        widgets = [shown_widgets(raw)[0] for raw in group]
        page = widgets[0]['page']
        page_items = free(items, page)
        text_height = text_height_of(page)
        members, option_boxes = [], []
        for raw, widget in zip(group, widgets):
            text, _ = _nearest(widget['box'], page_items, text_height, ('right',))
            if text:
                option_boxes.append(text['box'])
            option = text['text'] if text else ((raw['tooltip'] or '').strip() or widget['export_value'])
            members.append({'name': raw['name'], 'option': option, 'export_value': widget['export_value'],
                            'box': widget['box'], 'read_only': raw['flags']['read_only'],
                            'required': raw['flags']['required']})
        box = _union([w['box'] for w in widgets])
        label, label_box, label_source, confidence, alternatives = find_label(
            box, page, page_items, text_height, ('left', 'above', 'above_left'), option_boxes, None)
        names = [m['name'] for m in members]
        fields.append({
            'id': '+'.join(names),
            'label': label,
            'label_box': [int(v) for v in label_box] if label_box else None,
            'answer_box': [int(v) for v in box],
            'type': 'choice',
            'source': 'acroform',
            'confidence': round(float(confidence), 3),
            'needs_review': True,
            'page': page,
            'pdf_field_name': names,  # one PDF field per option
            'required': any(m['required'] for m in members),
            'answer_method': 'acroform_checkbox_group',
            'options': [m['option'] for m in members],
            'multiple': True,
            'label_source': label_source,
            'label_alternatives': alternatives,
            'type_source': 'independent_checkboxes',
            'pdf': {
                'name': None,
                'field_type': 'Btn',
                'flags': {},
                'required': any(m['required'] for m in members),
                'read_only': all(m['read_only'] for m in members),
                'tooltip': None,
                'max_length': None,
                'default_value': None,
                'value': None,
                'option_values': [m['export_value'] for m in members],
                'format_script': None,
                'widgets': [w for raw in group for w in raw['widgets']],
                'members': members,
            },
        })
    fields.sort(key=lambda f: (f['page'], f['answer_box'][1], f['answer_box'][0]))
    return fields, layoutlm_error


def find_fillable_fields(path, items, use_layoutlm=True, entities=None):
    """All fillable fields of a PDF, linked to labels. items = words from pdf_input.read_pdf_words.
    Returns (fields, LayoutLM error message or None)."""
    pages = prepare_pages(path, clean=False)
    return link_fields(read_acroform(path), items, pages, use_layoutlm, entities)
