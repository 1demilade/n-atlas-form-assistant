"""Check the LayoutLM step on its own: load the checkpoint, print its real label names,
and print the entities it finds on a form.

Usage: python test_layoutlm.py FORM_IMAGE_OR_PDF [--ocr-json OCR_JSON_FROM_THAT_FORM]
"""
import argparse
import json
from collections import Counter

from layout_lm import MODEL_NAME, TOKENIZER_NAME, extract_entities, load_model
from ocr import prepare_pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('form')
    parser.add_argument('--ocr-json', help='reuse OCR output instead of running PaddleOCR')
    parser.add_argument('--no-clean', action='store_true')
    args = parser.parse_args()

    model, tokenizer, device = load_model()
    print(f'model={MODEL_NAME} tokenizer={TOKENIZER_NAME} device={device}')
    print('id2label =', model.config.id2label)

    if args.ocr_json:
        with open(args.ocr_json, encoding='utf-8') as file:
            ocr_items = json.load(file)
    else:
        from ocr import read_form
        ocr_items = read_form(args.form, clean=not args.no_clean)

    pages = prepare_pages(args.form, clean=not args.no_clean)
    entities = extract_entities(ocr_items, pages)
    for entity in entities:
        print(f"p{entity['page']} {entity['kind']:9} {entity['confidence']:.2f} {entity['text']!r}")
    print('counts:', dict(Counter(entity['kind'] for entity in entities)))


if __name__ == '__main__':
    main()
