import argparse
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

# ---- Config (no form-specific values) ----
PDF_DPI = 200              # PDF pages are rendered at this resolution before OCR
MAX_SIDE = 2400            # larger photos are downscaled to this longest side (speed)
MIN_SIDE = 1000            # smaller images are upscaled so text is big enough to read
DESKEW_MAX_DEGREES = 15    # only straighten small rotations; larger ones are left alone
DESKEW_MIN_DEGREES = 0.3   # ignore rotations smaller than this
PDF_SUFFIXES = {'.pdf'}

_OCR = None


def get_ocr():
    """Load PaddleOCR once and reuse it (imported lazily because it is slow)."""
    global _OCR
    if _OCR is None:
        from paddleocr import PaddleOCR
        _OCR = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    return _OCR


def render_pdf(path, dpi=PDF_DPI):
    """Render every PDF page to a BGR image with PyMuPDF."""
    import fitz
    pages = []
    with fitz.open(str(path)) as document:
        for page in document:
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8)
            image = image.reshape(pixmap.height, pixmap.width, pixmap.n)
            if pixmap.n == 1:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            else:
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            pages.append(image)
    return pages


def _order_corners(points):
    points = points.reshape(4, 2).astype(np.float32)
    total = points.sum(axis=1)
    diff = np.diff(points, axis=1).ravel()
    return np.array([
        points[np.argmin(total)], points[np.argmin(diff)],
        points[np.argmax(total)], points[np.argmax(diff)],
    ], dtype=np.float32)


def _find_paper(image):
    """Return the 4 corners of a sheet of paper lying on a darker background, or None."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small_scale = 800 / max(gray.shape)
    small = cv2.resize(gray, None, fx=small_scale, fy=small_scale) if small_scale < 1 else gray
    small_scale = min(small_scale, 1)
    _, mask = cv2.threshold(cv2.GaussianBlur(small, (5, 5), 0), 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    area_ratio = cv2.contourArea(biggest) / float(small.shape[0] * small.shape[1])
    # Paper must be most of the photo but not the whole frame (then there is no background).
    if not 0.25 <= area_ratio <= 0.97:
        return None
    quad = cv2.approxPolyDP(biggest, 0.02 * cv2.arcLength(biggest, True), True)
    if len(quad) != 4:
        return None
    inside = np.zeros_like(small)
    cv2.fillConvexPoly(inside, quad.reshape(-1, 2), 255)
    # Paper must be clearly brighter than what surrounds it.
    if small[inside > 0].mean() - small[inside == 0].mean() < 40:
        return None
    return _order_corners(quad / small_scale)


def _flatten_paper(image, corners):
    top_left, top_right, bottom_right, bottom_left = corners
    width = int(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
    height = int(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                      dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(image, matrix, (width, height), borderValue=(255, 255, 255))


def _skew_angle(gray):
    """Median angle of long, nearly horizontal straight lines (table rules, underlines, text)."""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=100,
                            minLineLength=gray.shape[1] // 8, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) <= DESKEW_MAX_DEGREES:
            angles.append(angle)
    return float(np.median(angles)) if angles else 0.0


def _rotate(image, angle):
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                          borderValue=(255, 255, 255))


def clean_photo(image):
    """Make a phone photo or scan look like a flat page: crop, straighten, even out lighting."""
    longest = max(image.shape[:2])
    if longest > MAX_SIDE:
        image = cv2.resize(image, None, fx=MAX_SIDE / longest, fy=MAX_SIDE / longest,
                           interpolation=cv2.INTER_AREA)
    corners = _find_paper(image)
    if corners is not None:
        image = _flatten_paper(image, corners)
    angle = _skew_angle(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    if DESKEW_MIN_DEGREES <= abs(angle) <= DESKEW_MAX_DEGREES:
        image = _rotate(image, angle)
    longest = max(image.shape[:2])
    if longest < MIN_SIDE:
        image = cv2.resize(image, None, fx=MIN_SIDE / longest, fy=MIN_SIDE / longest,
                           interpolation=cv2.INTER_CUBIC)
    # Remove shadows / uneven light: divide by a blurred estimate of the background.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    kernel = max(15, (min(gray.shape) // 20) | 1)
    background = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), kernel)
    flat = cv2.divide(gray, background, scale=255)
    return cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR)


@lru_cache(maxsize=4)
def _prepare_pages_cached(path_str, mtime, clean):
    path = Path(path_str)
    if path.suffix.lower() in PDF_SUFFIXES:
        return tuple(render_pdf(path))
    image = cv2.imread(path_str, cv2.IMREAD_COLOR)  # applies EXIF orientation
    if image is None:
        raise ValueError(f'Could not read image: {path}')
    return (clean_photo(image) if clean else image,)


def prepare_pages(input_path, clean=True):
    """Return the exact BGR page images that OCR runs on (and that layout must scale/draw on)."""
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f'Input form was not found: {path}')
    return list(_prepare_pages_cached(str(path.resolve()), path.stat().st_mtime, clean))


def read_form(image_path, clean=True):
    """Run OCR on an image or PDF; return [{'text', 'box', 'score', 'page'}] (page is 1-based).

    Boxes are [left, top, right, bottom] in pixels of the page image from prepare_pages().
    """
    ocr = get_ocr()
    items = []
    for page_number, page in enumerate(prepare_pages(image_path, clean), start=1):
        for result in ocr.predict(page):
            texts = result.get('rec_texts', [])
            scores = result.get('rec_scores', [])
            boxes = result.get('rec_boxes', [])
            if not (len(texts) == len(scores) == len(boxes)):
                raise ValueError(
                    f'OCR returned mismatched text, score, and box data on page {page_number}.')
            for text, score, box in zip(texts, scores, boxes):
                if not str(text).strip():
                    continue
                items.append({
                    'text': str(text).strip(),
                    'box': [int(value) for value in box],
                    'score': float(score),
                    'page': page_number,
                })

    if not items:
        raise ValueError(f'OCR did not recognize any text in {image_path}.')
    return items


def main():
    parser = argparse.ArgumentParser(description='Extract OCR text from a form image or PDF.')
    parser.add_argument('input')
    parser.add_argument('--output', default='ocr_output.json')
    parser.add_argument('--no-clean', action='store_true', help='skip photo cleaning')
    parser.add_argument('--save-pages', help='folder to save the cleaned page images into')
    args = parser.parse_args()

    items = read_form(args.input, clean=not args.no_clean)
    with open(args.output, 'w', encoding='utf-8') as output_file:
        json.dump(items, output_file, indent=2, ensure_ascii=False)
    if args.save_pages:
        Path(args.save_pages).mkdir(parents=True, exist_ok=True)
        for number, page in enumerate(prepare_pages(args.input, not args.no_clean), start=1):
            cv2.imwrite(str(Path(args.save_pages) / f'page_{number}.png'), page)
    print(f'{len(items)} text items read from {args.input} across '
          f'{max(item["page"] for item in items)} page(s)')


if __name__ == '__main__':
    main()
