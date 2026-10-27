import argparse
import json

from layout_rules import FORM_NOTES, draw_boxes, extract_fields


def main():
    parser = argparse.ArgumentParser(
        description='Turn OCR output into application fields and expected inputs.'
    )
    parser.add_argument('--input', default='ocr_output.json')
    parser.add_argument('--output', default='form_fields.json')
    parser.add_argument('--form', default='Business-Name-Form.pdf')
    parser.add_argument('--boxes', default='form_boxes.png')
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as input_file:
        ocr_items = json.load(input_file)
    if not isinstance(ocr_items, list):
        raise ValueError(f'{args.input} must contain a JSON list of OCR items.')

    fields = extract_fields(ocr_items)
    if not fields:
        raise ValueError(
            'No form fields were recognized. Regenerate OCR from the complete PDF '
            'with ocr.py and check the OCR text.'
        )

    draw_boxes(fields, args.form, args.boxes, ocr_items)
    result = {'fields': fields, 'notes': FORM_NOTES}
    with open(args.output, 'w', encoding='utf-8') as output_file:
        json.dump(result, output_file, indent=2, ensure_ascii=False)

    print('--- Fields ---')
    for field in fields:
        print(f"{field['label']} | {field['type']}")
    print(f'{len(fields)} fields found')
    print(
        f'Saved {args.boxes}: red = question, blue = answer box. '
        'Open it and check.'
    )


if __name__ == '__main__':
    main()
