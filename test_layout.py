"""Run the rule-based FALLBACK on saved OCR output (no LayoutLM). Useful as a sanity check.

Usage: python test_layout.py FORM_IMAGE_OR_PDF --input OCR_JSON_FROM_THAT_FORM
"""
import argparse
import json

from layout import find_fields
from layout_rules import draw_boxes


def main():
    parser = argparse.ArgumentParser(description='Rule-based fields from saved OCR output.')
    parser.add_argument('form', help='the image/PDF the OCR output was made from')
    parser.add_argument('--input', default='ocr_output.json')
    parser.add_argument('--output', default='form_fields_rules.json')
    parser.add_argument('--boxes', default='form_boxes_rules.png')
    parser.add_argument('--no-clean', action='store_true')
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as input_file:
        ocr_items = json.load(input_file)
    if not isinstance(ocr_items, list):
        raise ValueError(f'{args.input} must contain a JSON list of OCR items.')

    fields = find_fields(ocr_items, args.form, method='rules', clean=not args.no_clean)
    if not fields:
        raise ValueError('No form fields were recognized. Check the OCR text.')
    draw_boxes(fields, args.form, args.boxes, clean=not args.no_clean)
    with open(args.output, 'w', encoding='utf-8') as output_file:
        json.dump(fields, output_file, indent=2, ensure_ascii=False)

    print('--- Fields ---')
    for field in fields:
        print(f"p{field['page']} {field['label']} | {field['type']} | {field['answer_method']}")
    print(f'{len(fields)} fields found')
    print(f'Saved {args.boxes}: red = label, blue = answer area. Open it and check.')


if __name__ == '__main__':
    main()
