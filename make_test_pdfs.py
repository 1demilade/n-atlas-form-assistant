"""Generate test PDFs with ground truth: fillable (AcroForm), flat with a text layer, image-only.

Labels come from make_synthetic_form.FIELD_POOL (test data, not used by the pipeline). Layout,
page size, field styles, tooltips and format actions vary with --seed.

Usage:
  python make_test_pdfs.py fillable --out samples/test_fillable.pdf --seed 1
  python make_test_pdfs.py flat     --out samples/test_flat.pdf --seed 1
  python make_test_pdfs.py image    --src samples/test_flat.pdf --out samples/test_image.pdf
"""
import argparse
import json
import random

from make_synthetic_form import FIELD_POOL, TITLES

PAGE_SIZES = [(612, 792), (595.28, 841.89), (500, 700)]  # Letter, A4, custom (points)
RADIO, PUSHBUTTON, COMBO = 1 << 15, 1 << 16, 1 << 17


def _escape(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _text_width(text, size):
    return len(text) * size * 0.52  # rough Helvetica width, only used for layout


def _layout(seed, count):
    rng = random.Random(seed)
    width, height = rng.choice(PAGE_SIZES)
    size = rng.choice([9, 10, 11])
    margin = rng.uniform(36, 60)
    fields = rng.sample(FIELD_POOL, min(count, len(FIELD_POOL)))
    combo_index = rng.randrange(len(fields))
    title = rng.choice(TITLES)
    sections = ['Personal details', 'Contact information', 'Other information']
    row_h = size * rng.uniform(2.6, 3.2)
    y = height - margin - size * 2
    ops = [f'BT /F1 {size * 1.5:.1f} Tf {margin:.2f} {y:.2f} Td ({_escape(title)}) Tj ET']
    y -= row_h
    layout, truth_sections = [], []
    per_section = max(1, (len(fields) + 2) // 3)
    for index, (label, kind, style) in enumerate(fields):
        if index % per_section == 0:
            name = sections[min(index // per_section, 2)]
            ops.append(f'BT /F1 {size * 1.2:.1f} Tf {margin:.2f} {y:.2f} Td ({_escape(name)}) Tj ET')
            truth_sections.append({'title': name, 'y_pt': y})
            y -= row_h
        text = label if label.endswith('?') else label + rng.choice([':', ''])
        above = style in ('line', 'box') and rng.random() < 0.3  # label above the input sometimes
        ops.append(f'BT /F1 {size} Tf {margin:.2f} {y:.2f} Td ({_escape(text)}) Tj ET')
        x = margin if above else margin + _text_width(text, size) + size
        wy = y - row_h * 0.75 if above else y - size * 0.35
        entry = {'label': label, 'text': text, 'type': kind, 'style': style, 'label_above': above}
        if style in ('line', 'box'):
            right = width - margin
            rect = [x, wy, min(right, x + rng.uniform(150, 300)), wy + size * 1.6]
            if style == 'line':
                ops.append(f'0.8 w {rect[0]:.2f} {rect[1]:.2f} m {rect[2]:.2f} {rect[1]:.2f} l S')
            else:
                ops.append(f'0.8 w {rect[0]:.2f} {rect[1]:.2f} {rect[2] - rect[0]:.2f} {rect[3] - rect[1]:.2f} re S')
            entry['rect'] = rect
        else:
            options = ['Yes', 'No'] if style == 'yesno' else style.split(':', 1)[1].split('|')
            entry['options'] = options
            if style.startswith('choice') and index == combo_index:
                rect = [x, wy, x + 120, wy + size * 1.6]
                ops.append(f'0.8 w {rect[0]:.2f} {rect[1]:.2f} {rect[2] - rect[0]:.2f} {rect[3] - rect[1]:.2f} re S')
                entry.update(style='combo', rect=rect)
            else:
                boxes, cx = [], x
                for option in options:
                    box = [cx, y - size * 0.15, cx + size, y + size * 0.85]
                    ops.append(f'0.8 w {box[0]:.2f} {box[1]:.2f} {size:.2f} {size:.2f} re S')
                    ops.append(f'BT /F1 {size} Tf {cx + size * 1.4:.2f} {y:.2f} Td ({_escape(option)}) Tj ET')
                    boxes.append(box)
                    cx += size * 1.4 + _text_width(option, size) + size * 2
                entry['option_rects'] = boxes
        layout.append(entry)
        y -= row_h * (1.8 if above else 1)
    return rng, (width, height), size, ops, layout, truth_sections, title


def _build(out_path, seed=1, count=8, fillable=True):
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject, NumberObject, TextStringObject)

    rng, (width, height), size, ops, layout, sections, title = _layout(seed, count)
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=height)
    helv = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')}))
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): helv})})
    content = DecodedStreamObject()
    content.set_data('\n'.join(ops).encode('latin-1'))
    page[NameObject('/Contents')] = writer._add_object(content)

    def name(s):
        return NameObject(s)

    def appearance(w, h, mark):
        stream = DecodedStreamObject()
        body = (f'q 1.2 w {w * .2:.2f} {h * .2:.2f} m {w * .8:.2f} {h * .8:.2f} l S '
                f'{w * .2:.2f} {h * .8:.2f} m {w * .8:.2f} {h * .2:.2f} l S Q') if mark else ''
        stream.set_data(body.encode('latin-1'))
        stream.update({name('/Type'): name('/XObject'), name('/Subtype'): name('/Form'),
                       name('/BBox'): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(w), FloatObject(h)])})
        return writer._add_object(stream)

    def widget(rect, extra):
        d = DictionaryObject({name('/Type'): name('/Annot'), name('/Subtype'): name('/Widget'),
                              name('/Rect'): ArrayObject([FloatObject(v) for v in rect]),
                              name('/F'): NumberObject(4), name('/P'): page.indirect_reference})
        d.update(extra)
        return d

    annots, acro_fields, truth = ArrayObject(), ArrayObject(), []
    for number, entry in enumerate(layout, start=1):
        field_name = f'f{number}_{rng.choice(["txt", "fld", "q"])}{rng.randint(10, 99)}'
        record = {'name': field_name, 'label': entry['label'], 'type': entry['type'],
                  'style': entry['style'], 'label_above': entry['label_above']}
        tooltip = entry['label'] if rng.random() < 0.4 else None
        common = {name('/T'): TextStringObject(field_name)}
        if tooltip:
            common[name('/TU')] = TextStringObject(tooltip)
            record['tooltip'] = tooltip
        if entry['style'] in ('line', 'box'):
            extra = dict(common, **{name('/FT'): name('/Tx'), name('/DA'): TextStringObject('/Helv 0 Tf 0 g')})
            if entry['type'] in ('date', 'number') and rng.random() < 0.5:
                script = ('AFDate_FormatEx("dd/mm/yyyy");' if entry['type'] == 'date'
                          else 'AFNumber_Format(0, 0, 0, 0, "", true);')
                js = DictionaryObject({name('/S'): name('/JavaScript'), name('/JS'): TextStringObject(script)})
                extra[name('/AA')] = DictionaryObject({name('/F'): js})
                record['format_action'] = script
            if rng.random() < 0.3:
                extra[name('/Ff')] = NumberObject(2)  # required
                record['required'] = True
            obj = writer._add_object(widget(entry['rect'], extra))
            annots.append(obj)
            acro_fields.append(obj)
            record['rects'] = [entry['rect']]
        elif entry['style'] == 'combo':
            extra = dict(common, **{name('/FT'): name('/Ch'), name('/Ff'): NumberObject(COMBO),
                                    name('/DA'): TextStringObject('/Helv 0 Tf 0 g'),
                                    name('/Opt'): ArrayObject([TextStringObject(o) for o in entry['options']])})
            obj = writer._add_object(widget(entry['rect'], extra))
            annots.append(obj)
            acro_fields.append(obj)
            record.update(rects=[entry['rect']], options=entry['options'])
        else:  # radio group: one parent field, one widget per option
            parent = DictionaryObject(dict(common, **{name('/FT'): name('/Btn'), name('/Ff'): NumberObject(RADIO),
                                                      name('/V'): name('/Off')}))
            parent_ref = writer._add_object(parent)
            kids = ArrayObject()
            for option, rect in zip(entry['options'], entry['option_rects']):
                export = f'opt{len(kids)}' if rng.random() < 0.5 else option  # cryptic or readable
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                ap = DictionaryObject({name('/N'): DictionaryObject({name('/' + export): appearance(w, h, True),
                                                                    name('/Off'): appearance(w, h, False)})})
                kid = writer._add_object(widget(rect, {name('/Parent'): parent_ref, name('/AS'): name('/Off'),
                                                       name('/AP'): ap}))
                kids.append(kid)
                annots.append(kid)
            parent[name('/Kids')] = kids
            acro_fields.append(parent_ref)
            record.update(rects=entry['option_rects'], options=entry['options'])
        truth.append(record)

    if fillable:
        page[name('/Annots')] = annots
        writer._root_object[name('/AcroForm')] = DictionaryObject({
            name('/Fields'): acro_fields, name('/NeedAppearances'): BooleanObject(True),
            name('/DA'): TextStringObject('/Helv 0 Tf 0 g'),
            name('/DR'): DictionaryObject({name('/Font'): DictionaryObject({name('/Helv'): helv})})})
    with open(out_path, 'wb') as file:
        writer.write(file)
    return {'seed': seed, 'page_size_pt': [width, height], 'font_size': size, 'title': title,
            'fillable': fillable, 'fields': truth, 'sections': [s['title'] for s in sections]}


def make_fillable_pdf(out_path, seed=1, count=8):
    return _build(out_path, seed, count, fillable=True)


def make_flat_pdf(out_path, seed=1, count=8):
    """Same drawing as make_fillable_pdf, but without any AcroForm fields."""
    return _build(out_path, seed, count, fillable=False)


def make_image_pdf(src_path, out_path, dpi=200):
    """Image-only copy of a PDF: every page rendered and saved as a picture (no text layer)."""
    import cv2
    from PIL import Image

    from ocr import render_pdf
    images = [Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB)) for page in render_pdf(src_path, dpi)]
    images[0].save(out_path, save_all=True, append_images=images[1:], resolution=dpi)
    return {'source': str(src_path), 'pages': len(images), 'dpi': dpi}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['fillable', 'flat', 'image'])
    parser.add_argument('--out', required=True)
    parser.add_argument('--src', help='image: the PDF to rasterise')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--count', type=int, default=8)
    args = parser.parse_args()
    if args.kind == 'image':
        if not args.src:
            parser.error('image needs --src')
        truth = make_image_pdf(args.src, args.out)
    else:
        truth = (make_fillable_pdf if args.kind == 'fillable' else make_flat_pdf)(args.out, args.seed, args.count)
    truth_path = args.out.rsplit('.', 1)[0] + '_truth.json'
    with open(truth_path, 'w', encoding='utf-8') as file:
        json.dump(truth, file, indent=2)
    print(f'Saved {args.out} and {truth_path}')


if __name__ == '__main__':
    main()
