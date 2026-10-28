"""Fill a PDF form from answers.json (field id or key -> English text) and the form JSON from layout.py.

Fillable PDFs: values are written into the AcroForm fields with pypdf.
Flat PDFs: answers are drawn as text (Helvetica) inside each field's answer_box; checkbox
answers get an X in the chosen option's box. Every field gets a status in the report.

Usage: python fill_form.py FORM.pdf --form form_fields.json --answers answers.json --out filled.pdf
"""
import argparse
import io
import json
import re

# ---- Config ----
MAX_FONT_PT = 11       # largest font used for flat-PDF answers
MIN_FONT_PT = 6        # smallest; text that still does not fit is reported as 'overflow'
CHAR_WIDTH_EM = 0.56   # Helvetica average glyph width (conservative) used to fit text
LINE_GAP = 1.15        # line height as a multiple of the font size
PADDING_PT = 2         # space kept between the text and the answer box edge
TRUE_WORDS = {'yes', 'y', 'true', '1', 'x', 'checked', 'on', 'tick', 'ticked'}
FALSE_WORDS = {'no', 'n', 'false', '0', 'unchecked', 'off', ''}


def _norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).strip()


def _load(value):
    if isinstance(value, (dict, list)):
        return value
    with open(value, encoding='utf-8') as file:
        return json.load(file)


def _match_option(answer, texts, values):
    """Index of the option whose display text or export value matches the answer, else None."""
    wanted = _norm(answer)
    for options in (texts, values):
        for index, option in enumerate(options):
            if option is not None and _norm(option) == wanted:
                return index
    return None


def _resolve(fields, answers):
    """answers.json may name a field by its id or its readable key.
    Returns ({id: answer}, {id: report update for id/key conflicts}, names matching no field)."""
    by_id, conflicts, known = {}, {}, set()
    for field in fields:
        names = [field['id']] + ([field['key']] if field.get('key') not in (None, field['id']) else [])
        known.update(names)
        given = [name for name in names if name in answers]
        if len(given) == 2 and str(answers[given[0]]).strip() != str(answers[given[1]]).strip():
            conflicts[field['id']] = {'status': 'skipped',
                                      'reason': f"different answers for id and key {field['key']!r}"}
        elif given:
            by_id[field['id']] = answers[given[0]]
    return by_id, conflicts, sorted(set(answers) - known)


def _truth(answer):
    word = _norm(answer)
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return None


# ---------- fillable PDFs ----------

def _fill_acroform(reader, fields, answers):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject

    from pdf_fields import read_on_states
    writer = PdfWriter(clone_from=reader)
    states = read_on_states(reader)  # real checkbox/radio on-state names, from the PDF itself
    report, values = [], {}
    for field in fields:
        fid = field['id']
        name = field.get('pdf_field_name') or fid
        real_states = sorted({s for widget in states.get(name, []) for s in widget})
        if fid not in answers:
            report.append({'id': fid, 'status': 'skipped', 'reason': 'no answer'})
            continue
        answer = str(answers[fid]).strip()
        pdf = field['pdf']
        kind = pdf['field_type']
        if pdf.get('read_only'):
            report.append({'id': fid, 'status': 'skipped', 'reason': 'read-only field'})
            continue
        if kind == 'Tx':
            if pdf.get('max_length') and len(answer) > pdf['max_length']:
                report.append({'id': fid, 'status': 'skipped',
                               'reason': f"answer longer than max_length {pdf['max_length']}"})
                continue
            values[name] = answer
        elif kind == 'Btn':
            exports = pdf.get('option_values') or []
            if not real_states:
                report.append({'id': fid, 'status': 'skipped',
                               'reason': 'the PDF has no on-state for this checkbox/radio'})
                continue
            if len(exports) >= 2:  # radio group or same-name checkboxes: pick one option
                index = _match_option(answer, field.get('options', []), exports)
                if index is None:
                    report.append({'id': fid, 'status': 'skipped',
                                   'reason': f'answer {answer!r} matches no option {field.get("options")}'})
                    continue
                if exports[index] not in real_states:
                    report.append({'id': fid, 'status': 'skipped',
                                   'reason': f'on-state {exports[index]!r} of option '
                                             f'{field["options"][index]!r} is not in the PDF {real_states}'})
                    continue
                values[name] = NameObject('/' + exports[index])
            else:
                if len(real_states) > 1:
                    report.append({'id': fid, 'status': 'skipped',
                                   'reason': f'single checkbox with several on-states {real_states}'})
                    continue
                truth = _truth(answer)
                if truth is None:
                    report.append({'id': fid, 'status': 'skipped',
                                   'reason': f'answer {answer!r} is not yes/no for a checkbox'})
                    continue
                values[name] = NameObject('/' + real_states[0] if truth else '/Off')
        elif kind == 'Ch':
            index = _match_option(answer, field.get('options', []), pdf.get('option_values') or [])
            if index is None:
                report.append({'id': fid, 'status': 'skipped',
                               'reason': f'answer {answer!r} matches no option {field.get("options")}'})
                continue
            values[name] = pdf['option_values'][index]
        else:
            report.append({'id': fid, 'status': 'skipped', 'reason': f'{kind or "unknown"} field cannot be filled with text'})
            continue
        report.append({'id': fid, 'status': 'filled', 'value': str(values[name])})

    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    writer.set_need_appearances_writer(True)
    return writer, report


# ---------- flat PDFs ----------

def _escape(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _page_geometry(page, size_px):
    """Display-space size in points, pixel->point scale, and the cm matrix from display space
    (origin bottom-left, y up, rotation applied) to the page's default user space."""
    crop = page.cropbox
    left, bottom, right, top = float(crop.left), float(crop.bottom), float(crop.right), float(crop.top)
    rotation = (page.rotation or 0) % 360
    width, height = right - left, top - bottom
    shown_w, shown_h = (height, width) if rotation in (90, 270) else (width, height)
    matrix = {0: (1, 0, 0, 1, left, bottom), 90: (0, 1, -1, 0, right, bottom),
              180: (-1, 0, 0, -1, right, top), 270: (0, -1, 1, 0, left, top)}[rotation]
    return shown_w, shown_h, shown_w / size_px[0], shown_h / size_px[1], matrix


def _box_to_points(box, geometry):
    shown_w, shown_h, sx, sy, _ = geometry
    return box[0] * sx, shown_h - box[3] * sy, box[2] * sx, shown_h - box[1] * sy  # x0, y0, x1, y1


def _fit_text(text, width, height):
    """Font size and lines so text fits the box (single line preferred); flag overflow."""
    def wrap(size):
        per_line = max(1, int(width / (CHAR_WIDTH_EM * size)))
        lines, current = [], ''
        for word in text.split():
            candidate = f'{current} {word}'.strip()
            if len(candidate) <= per_line or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        return lines + ([current] if current else [])

    size = min(MAX_FONT_PT, height * 0.75)
    while size >= MIN_FONT_PT:
        if len(text) * CHAR_WIDTH_EM * size <= width:
            return size, [text], False
        size -= 0.5
    size = max(MIN_FONT_PT, min(MAX_FONT_PT, height * 0.75))
    while size >= MIN_FONT_PT:
        lines = wrap(size)
        if len(lines) * size * LINE_GAP <= height and all(len(l) * CHAR_WIDTH_EM * size <= width for l in lines):
            return size, lines, False
        size -= 0.5
    return MIN_FONT_PT, wrap(MIN_FONT_PT), True


def _text_ops(text, box_pt):
    x0, y0, x1, y1 = box_pt
    width, height = x1 - x0 - 2 * PADDING_PT, y1 - y0 - 2 * PADDING_PT
    size, lines, overflow = _fit_text(text, max(1, width), max(1, height))
    block = len(lines) * size * LINE_GAP
    # Single lines sit near the bottom (on an underline); blocks start at the top of the box.
    first = (y0 + PADDING_PT + size * 0.25 if len(lines) == 1
             else y1 - PADDING_PT - size)
    ops = []
    for index, line in enumerate(lines):
        y = first - index * size * LINE_GAP
        ops.append(f'BT /FNat {size:.1f} Tf {x0 + PADDING_PT:.2f} {y:.2f} Td ({_escape(line)}) Tj ET')
    return ops, overflow or block > height + size


def _cross_ops(box_pt):
    x0, y0, x1, y1 = box_pt
    inset = 0.2 * min(x1 - x0, y1 - y0)
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    return [f'q 1.2 w {x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S {x0:.2f} {y1:.2f} m {x1:.2f} {y0:.2f} l S Q']


def _overlay_reader(page_ops, geometry, mediabox):
    """A one-page PDF holding only the answer text, in the same user space as the form page."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject, RectangleObject)
    writer = PdfWriter()
    page = writer.add_blank_page(width=float(mediabox.width), height=float(mediabox.height))
    page.mediabox = RectangleObject([float(v) for v in mediabox])
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/FNat'): font})})
    matrix = ' '.join(f'{v:g}' for v in geometry[4])
    stream = DecodedStreamObject()
    stream.set_data(f'q {matrix} cm 0 0 0 rg 0 0 0 RG\n{chr(10).join(page_ops)}\nQ\n'.encode('latin-1'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    return PdfReader(buffer)


def _fill_flat(reader, fields, answers, sizes_px, writer=None):
    """writer: continue an existing writer (a mixed PDF's AcroForm values are already in it)."""
    from pypdf import PdfWriter
    writer = writer or PdfWriter(clone_from=reader)
    ops_by_page, report = {}, []
    geometries = {n: _page_geometry(p, sizes_px[n - 1]) for n, p in enumerate(writer.pages, start=1)}
    for field in fields:
        fid = field['id']
        if fid not in answers:
            report.append({'id': fid, 'status': 'skipped', 'reason': 'no answer'})
            continue
        answer = str(answers[fid]).strip()
        page = field.get('page', 1)
        geometry = geometries[page]
        option_boxes = field.get('option_boxes') or []
        if field.get('answer_method') == 'checkboxes' and option_boxes:
            index = _match_option(answer, field.get('options', []), [])
            if index is None and len(option_boxes) == 1 and _truth(answer) is not None:
                index = 0 if _truth(answer) else None
                if index is None:
                    report.append({'id': fid, 'status': 'filled', 'value': 'left unticked'})
                    continue
            if index is None or index >= len(option_boxes):
                report.append({'id': fid, 'status': 'skipped',
                               'reason': f'answer {answer!r} matches no option {field.get("options")}'})
                continue
            ops_by_page.setdefault(page, []).extend(_cross_ops(_box_to_points(option_boxes[index], geometry)))
            report.append({'id': fid, 'status': 'filled', 'value': f"X in '{field['options'][index]}'"})
            continue
        if not field.get('answer_box'):
            report.append({'id': fid, 'status': 'skipped', 'reason': 'no answer_box'})
            continue
        try:
            answer.encode('cp1252')
        except UnicodeEncodeError:
            report.append({'id': fid, 'status': 'skipped',
                           'reason': 'answer has characters the built-in Helvetica font cannot show'})
            continue
        ops, overflow = _text_ops(answer, _box_to_points(field['answer_box'], geometry))
        ops_by_page.setdefault(page, []).extend(ops)
        entry = {'id': fid, 'status': 'filled', 'value': answer}
        if overflow:
            entry['warning'] = 'text may not fit the answer box'
        report.append(entry)

    for number, ops in ops_by_page.items():
        page = writer.pages[number - 1]
        overlay = _overlay_reader(ops, geometries[number], page.mediabox)
        page.merge_page(overlay.pages[0])
    return writer, report


def fill_form(pdf_path, form, answers, out_path):
    """Fill pdf_path with answers; write out_path. form = the JSON object from layout.py (or its
    path); answers = {field id: English text} (or its path). Returns the per-field report."""
    from pypdf import PdfReader
    form, answers = _load(form), _load(answers)
    reader = PdfReader(str(pdf_path))
    answers, conflicts, unknown = _resolve(form['fields'], answers)
    # Each field is filled the way it was found: AcroForm widget, or drawn on the page.
    fillable = [f for f in form['fields'] if f.get('pdf_field_name')]
    flat = [f for f in form['fields'] if not f.get('pdf_field_name')]
    writer, report = _fill_acroform(reader, fillable, answers) if fillable else (None, [])
    if flat:
        sizes = [(p['width_px'], p['height_px']) for p in form['form']['pages']]
        writer, flat_report = _fill_flat(reader, flat, answers, sizes, writer)
        report += flat_report
    if writer is None:
        from pypdf import PdfWriter
        writer = PdfWriter(clone_from=reader)
    order = {f['id']: n for n, f in enumerate(form['fields'])}
    report.sort(key=lambda entry: order[entry['id']])
    keys = {f['id']: f.get('key') for f in form['fields']}
    for entry in report:
        entry.update(conflicts.get(entry['id'], {}))
        if keys.get(entry['id']):
            entry['key'] = keys[entry['id']]
    report.extend({'id': fid, 'status': 'skipped', 'reason': 'no field with this id'} for fid in unknown)
    with open(out_path, 'wb') as file:
        writer.write(file)
    return report


def main():
    parser = argparse.ArgumentParser(description='Fill a PDF form from answers.json.')
    parser.add_argument('pdf')
    parser.add_argument('--form', default='form_fields.json', help='JSON written by layout.py')
    parser.add_argument('--answers', default='answers.json')
    parser.add_argument('--out', default='form_filled.pdf')
    parser.add_argument('--report', help='also save the per-field report as JSON here')
    args = parser.parse_args()
    report = fill_form(args.pdf, args.form, args.answers, args.out)
    for entry in report:
        detail = entry.get('value') or entry.get('reason', '')
        warning = f"  [{entry['warning']}]" if entry.get('warning') else ''
        print(f"{entry['status']:8} {entry['id']!r:40} {detail}{warning}")
    filled = sum(1 for e in report if e['status'] == 'filled')
    print(f'{filled} filled, {len(report) - filled} skipped. Saved {args.out}')
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as file:
            json.dump(report, file, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    main()
