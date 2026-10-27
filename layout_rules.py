import re
from pathlib import Path
from PIL import Image, ImageDraw


FIELD_DEFINITIONS = {
    'option_1': ('Proposed business name (option 1)', 'text',
                 'Enter your first-choice business name.', 'business_names', None),
    'option_2': ('Proposed business name (option 2)', 'text',
                 'Enter your second-choice business name.', 'business_names', None),
    'option_3': ('Proposed business name (option 3)', 'text',
                 'Enter your third-choice business name.', 'business_names', None),
    'commencement_date': ('Date of commencement of business', 'date',
                          'Enter the date the business commenced.', 'business', None),
    'business_nature': ('General nature of business', 'multiline_text',
                        'Briefly describe the business activities.', 'business', None),
    'principal_address': ('Principal place of business - address', 'text',
                          'Enter the street/building address.', 'principal_address', None),
    'principal_city': ('Principal place of business - city/town/village', 'text',
                       'Enter the city, town, or village.', 'principal_address', None),
    'principal_lga': ('Principal place of business - local government', 'text',
                      'Enter the local government area.', 'principal_address', None),
    'principal_state': ('Principal place of business - state', 'text',
                        'Enter the state.', 'principal_address', None),
    'branch_address': ('Branch address', 'text',
                       'Enter the branch street/building address, if applicable.',
                       'branch_address', False),
    'branch_city': ('Branch city/town/village', 'text',
                    'Enter the branch city, town, or village, if applicable.',
                    'branch_address', False),
    'branch_lga': ('Branch local government', 'text',
                   'Enter the branch local government area, if applicable.',
                   'branch_address', False),
    'branch_state': ('Branch state', 'text',
                     'Enter the branch state, if applicable.', 'branch_address', False),
    'surname': ('Surname', 'text', 'Enter the proprietor surname.', 'proprietor', None),
    'first_name': ('First name', 'text', 'Enter the proprietor first name.',
                   'proprietor', None),
    'other_names': ('Other name(s)', 'text', 'Enter other names, if any.',
                    'proprietor', False),
    'former_names': ('Former name(s)', 'text', 'Enter former names, if any.',
                     'proprietor', False),
    'nationality': ('Nationality', 'text', 'Enter the proprietor nationality.',
                    'proprietor', None),
    'former_nationality': ('Former nationality', 'text',
                           'Enter former nationality, if applicable.',
                           'proprietor', False),
    'gender': ('Gender', 'text', 'Enter the proprietor gender as requested by the form.',
               'proprietor', None),
    'date_of_birth': ('Date of birth', 'date', 'Enter the date of birth.',
                      'proprietor', None),
    'phone_number': ('Phone number', 'phone',
                     'Enter a contact telephone number, including country code if needed.',
                     'proprietor', None),
    'passport_photo': ('Recent passport photograph', 'file',
                       'Upload a recent passport photograph (image file).',
                       'proprietor', True),
    'email': ('Email', 'email', 'Enter a valid email address.', 'proprietor', None),
    'identity_number': ('Identity number', 'text',
                        'Enter the number shown on the selected identity document.',
                        'identity', None),
    'nin': ('NIN', 'text', 'Enter the 11-digit National Identification Number.',
            'identity', None),
    'identity_type': ('Identity type', 'choice',
                      "Choose one: International Passport, Driver's License, National "
                      "Identity Card, or Voter's Card.",
                      'identity', None),
    'occupation': ('Occupation', 'text', 'Enter the proprietor occupation.',
                   'proprietor', None),
    'proprietor_address': ('Proprietor address - address', 'text',
                           'Enter the proprietor residential street/building address.',
                           'proprietor_address', None),
    'proprietor_city': ('Proprietor address - city/town/village', 'text',
                        'Enter the proprietor city, town, or village.',
                        'proprietor_address', None),
    'proprietor_lga': ('Proprietor address - local government', 'text',
                       'Enter the proprietor local government area.',
                       'proprietor_address', None),
    'proprietor_state': ('Proprietor address - state', 'text',
                         'Enter the proprietor state.', 'proprietor_address', None),
    'signature': ('Signature', 'signature',
                  'Sign the completed application.', 'attestation', True),
    'attestation_date': ('Date', 'date',
                         'Enter the date the application is signed.',
                         'attestation', True),
}

FORM_NOTES = [
    'Fill and sign the application form.',
    'Upload a recent passport photograph and signature.',
    'Ensure the principal business address is easily traceable.',
    'Submit the completed form as a PDF with a scanned recognized identity document: '
    "International Passport data page, Driver's License, National Identity Card, "
    "or Voter's Card. Send it by email to quickservice@cac.gov.ng.",
]

FIELD_LABEL_HINTS = {
    'option_1': 'Option 1',
    'option_2': 'Option 2',
    'option_3': 'Option 3',
    'commencement_date': 'Date of commencement of',
    'business_nature': 'General Nature of Business',
    'principal_address': 'Address',
    'principal_city': 'City/Town/Village',
    'principal_lga': 'Local Government',
    'principal_state': 'State',
    'branch_address': 'Address',
    'branch_city': 'City/Town/Village',
    'branch_lga': 'Local Government',
    'branch_state': 'State',
    'surname': 'Surname',
    'first_name': 'First name',
    'other_names': 'Other name(s)',
    'former_names': 'Former name(s)',
    'nationality': 'Nationality',
    'former_nationality': 'Former nationality',
    'gender': 'Gender',
    'date_of_birth': 'Date of birth',
    'phone_number': 'Phone number',
    'passport_photo': 'Recent Passport Photograph',
    'email': 'Email',
    'identity_number': 'Identity Number',
    'nin': 'NIN',
    'identity_type': 'Identity Type',
    'occupation': 'Occupation',
    'proprietor_address': 'Address',
    'proprietor_city': 'City/Town/Village',
    'proprietor_lga': 'Local Government',
    'proprietor_state': 'State',
    'signature': 'Signature',
    'attestation_date': 'Date',
}


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

        if not str(text).strip() or box is None:
            continue
        if len(box) == 4 and isinstance(box[0], (list, tuple)):
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            box = [min(xs), min(ys), max(xs), max(ys)]

        items.append({
            'text': str(text).strip(),
            'box': [int(value) for value in box],
            'score': float(score),
            'page': int(page),
        })
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


def _merge_wrapped_labels(rows):
    merged = []
    index = 0
    while index < len(rows):
        row = dict(rows[index])
        if (
            row['page'] == 1
            and _key(row['text']).startswith('dateofcommencementof')
            and index + 1 < len(rows)
            and rows[index + 1]['page'] == row['page']
            and _key(rows[index + 1]['text']) == 'business'
        ):
            next_row = rows[index + 1]
            row['text'] = f"{row['text']} {next_row['text']}"
            row['box'] = [
                min(row['box'][0], next_row['box'][0]),
                min(row['box'][1], next_row['box'][1]),
                max(row['box'][2], next_row['box'][2]),
                max(row['box'][3], next_row['box'][3]),
            ]
            index += 1
        merged.append(row)
        index += 1
    return merged


def extract_fields(ocr_items):
    """Extract the known application fields and the expected value for each."""
    items = clean_items(ocr_items)
    rows = _merge_wrapped_labels(get_rows(items))
    fields = []
    seen = set()
    address_section = None
    proprietor_section = False
    attestation_section = False

    for row in rows:
        text = row['text'].strip()
        normalized = _key(text)
        if not normalized:
            continue

        if normalized.startswith('addressofprincipalplaceofbusiness'):
            address_section = 'principal'
            attestation_section = False
            continue
        if normalized.startswith('addressofbranch'):
            address_section = 'branch'
            attestation_section = False
            continue
        if normalized.startswith('proprietorsaddress'):
            address_section = 'proprietor'
            proprietor_section = True
            attestation_section = False
            continue
        if normalized.startswith('proprietorsdetails'):
            proprietor_section = True
            address_section = None
            attestation_section = False
            continue
        if _has_label(text, 'Attestation'):
            if proprietor_section and _has_label(text, 'Signature'):
                field_id = 'signature'
                if field_id not in seen:
                    fields.append(_make_field(field_id, row, text, items))
                    seen.add(field_id)
            attestation_section = True
            address_section = None
            continue

        field_ids = []
        if address_section:
            address_labels = {
                'address': 'address',
                'city/town/village': 'city',
                'local government': 'lga',
                'state': 'state',
            }
            for label, suffix in address_labels.items():
                if _starts_with_label(text, label):
                    field_ids.append(f'{address_section}_{suffix}')
                    break
        elif attestation_section and _starts_with_label(text, 'Date'):
            field_ids.append('attestation_date')
        elif proprietor_section:
            aliases = {
                'Surname': 'surname',
                'First name': 'first_name',
                'Other name(s)': 'other_names',
                'Former name(s)': 'former_names',
                'Nationality': 'nationality',
                'Former nationality': 'former_nationality',
                'Gender': 'gender',
                'Date of birth': 'date_of_birth',
                'Phone number': 'phone_number',
                'Recent Passport Photograph': 'passport_photo',
                'Email': 'email',
                'Identity Number': 'identity_number',
                'NIN': 'nin',
                'Identity Type': 'identity_type',
                'Occupation': 'occupation',
            }
            field_ids.extend(
                field_id for label, field_id in aliases.items()
                if (
                    _has_label(text, label)
                    if label == 'Recent Passport Photograph'
                    else _starts_with_label(text, label)
                )
            )
        else:
            aliases = {
                'Option 1': 'option_1',
                'Option 2': 'option_2',
                'Option 3': 'option_3',
                'Date of commencement of business': 'commencement_date',
                'General Nature of Business': 'business_nature',
            }
            field_ids.extend(
                field_id for label, field_id in aliases.items()
                if _starts_with_label(text, label)
            )

        for field_id in field_ids:
            if field_id in seen:
                if (
                    field_id == 'business_nature'
                    and normalized == 'generalnatureofbusiness'
                ):
                    existing = next(
                        field for field in fields if field['id'] == field_id
                    )
                    existing.update(_make_field(field_id, row, text, items))
                continue
            fields.append(_make_field(field_id, row, text, items))
            seen.add(field_id)

    return fields


def _make_field(field_id, row, source_label, ocr_items):
    label, value_type, expected_input, section, required = (
        FIELD_DEFINITIONS[field_id]
    )
    label_box = row['box']
    if field_id != 'commencement_date':
        hint = FIELD_LABEL_HINTS[field_id]
        matching_items = [
            item for item in ocr_items
            if item['page'] == row['page']
            and _starts_with_label(item['text'], hint)
        ]
        if matching_items:
            row_centre = (row['box'][1] + row['box'][3]) / 2
            best_match = min(
                matching_items,
                key=lambda item: abs(
                    (item['box'][1] + item['box'][3]) / 2 - row_centre
                ),
            )
            label_box = best_match['box']

    return {
        'id': field_id,
        'label': label,
        'source_label': source_label,
        'type': value_type,
        'expected_input': expected_input,
        'section': section,
        'required': required,
        'page': row['page'],
        'label_box': label_box,
    }


def draw_boxes(fields, form_path, out_path='form_boxes.png', ocr_items=None):
    """Draw field labels and corresponding answer areas on the form pages."""
    form_path = Path(form_path)
    if form_path.suffix.lower() == '.pdf':
        import pypdfium2

        document = pypdfium2.PdfDocument(str(form_path))
        pages = [
            page.render(scale=2).to_pil().convert('RGB')
            for page in document
        ]
    else:
        pages = [Image.open(form_path).convert('RGB')]

    gutter = 20
    page_width = max(page.width for page in pages)
    page_height = max(page.height for page in pages)
    canvas = Image.new(
        'RGB',
        (page_width, len(pages) * page_height + (len(pages) - 1) * gutter),
        'white',
    )
    offsets = []
    for index, page in enumerate(pages):
        y_offset = index * (page_height + gutter)
        offsets.append(y_offset)
        canvas.paste(page, (0, y_offset))

    draw = ImageDraw.Draw(canvas)
    page_right_edges = {}
    if ocr_items:
        for item in clean_items(ocr_items):
            page_right_edges[item['page']] = max(
                page_right_edges.get(item['page'], 0),
                item['box'][2] + 10,
            )
    for field in fields:
        page_index = field['page'] - 1
        if page_index < 0 or page_index >= len(pages):
            raise ValueError(f"Field {field['id']} refers to missing page {field['page']}.")

        page = pages[page_index]
        x1, y1, x2, y2 = field['label_box']
        label_box = [
            max(0, min(x1, page.width - 1)),
            max(0, min(y1, page.height - 1)),
            max(0, min(x2, page.width - 1)),
            max(0, min(y2, page.height - 1)),
        ]
        answer_left = min(label_box[2] + 10, page.width - 2)
        answer_right = min(
            page_right_edges.get(field['page'], page.width - 2),
            page.width - 2,
        )
        answer_box = [
            answer_left,
            label_box[1],
            max(answer_left, answer_right),
            max(label_box[1] + 1, label_box[3]),
        ]
        field['answer_box'] = answer_box

        y_offset = offsets[page_index]
        draw.rectangle(
            (label_box[0], label_box[1] + y_offset,
             label_box[2], label_box[3] + y_offset),
            outline='red',
            width=3,
        )
        if answer_box[0] < answer_box[2]:
            draw.rectangle(
                (answer_box[0], answer_box[1] + y_offset,
                 answer_box[2], answer_box[3] + y_offset),
                outline='blue',
                width=2,
            )

    canvas.save(out_path)
