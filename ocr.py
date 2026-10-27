import argparse
import json
from pathlib import Path

from paddleocr import PaddleOCR


def read_form(input_path):
    """Run OCR on an image or PDF and return text records with page numbers."""
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f'Input form was not found: {path}')

    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    items = []

    for page_number, result in enumerate(ocr.predict(str(path)), start=1):
        texts = result.get('rec_texts', [])
        scores = result.get('rec_scores', [])
        boxes = result.get('rec_boxes', [])
        if not (len(texts) == len(scores) == len(boxes)):
            raise ValueError(f'OCR returned mismatched text, score, and box data on page {page_number}.')

        for text, score, box in zip(texts, scores, boxes):
            items.append({
                'text': str(text),
                'score': float(score),
                'box': [int(value) for value in box],
                'page': page_number,
            })

    if not items:
        raise ValueError(f'OCR did not recognize any text in {path}.')
    return items


def main():
    parser = argparse.ArgumentParser(description='Extract OCR text from a form image or PDF.')
    parser.add_argument('input', nargs='?', default='Business-Name-Form.pdf')
    parser.add_argument('--output', default='ocr_output.json')
    args = parser.parse_args()

    items = read_form(args.input)
    with open(args.output, 'w', encoding='utf-8') as output_file:
        json.dump(items, output_file, indent=2, ensure_ascii=False)
    print(f'{len(items)} text items read from {args.input} across {max(item["page"] for item in items)} page(s)')


if __name__ == '__main__':
    main()
