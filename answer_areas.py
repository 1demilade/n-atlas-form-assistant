"""Find where the answer goes for each label: LayoutLM answers, table cells, underlines,
checkboxes, or empty space. All sizes are relative to the page or to the text height."""
import cv2
import numpy as np

LINE_ABOVE_GAP = 0.6   # a label printed under its line sits at most this far below it (text heights)


def median_text_height(items):
    heights = [item['box'][3] - item['box'][1] for item in items]
    return float(np.median(heights)) if heights else 20.0


def _overlap(a1, a2, b1, b2):
    return max(0, min(a2, b2) - max(a1, b1))


def _contains_text(box, items, ignore=(), min_share=0.3):
    """True if any OCR item (other than `ignore`) covers at least min_share of its area in box."""
    for item in items:
        if any(item is other for other in ignore):
            continue
        x1, y1, x2, y2 = item['box']
        area = max(1, (x2 - x1) * (y2 - y1))
        inter = _overlap(box[0], box[2], x1, x2) * _overlap(box[1], box[3], y1, y2)
        if inter / area >= min_share:
            return True
    return False


def _inside_letters(box, items):
    """True if box sits inside an OCR text box and is much shorter than that text (a letter part)."""
    height = box[3] - box[1]
    for item in items:
        x1, y1, x2, y2 = item['box']
        if x1 <= box[0] and box[2] <= x2 and y1 <= box[1] and box[3] <= y2 and height < 0.8 * (y2 - y1):
            return True
    return False


def detect_regions(image, text_height, items=()):
    """Detect horizontal lines, table cells, write-in boxes and checkboxes on one page image.
    items = OCR items on this page (used to reject parts of letters that look like boxes)."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
                                   max(15, int(text_height) | 1), 15)
    height, width = gray.shape
    min_line = max(int(3 * text_height), width // 40)

    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (min_line, 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_line)))
    # Close small gaps so dotted/broken lines still count.
    horizontal = cv2.dilate(horizontal, np.ones((3, 3), np.uint8))
    vertical = cv2.dilate(vertical, np.ones((3, 3), np.uint8))

    lines = []
    for contour in cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(contour)
        if h <= max(6, text_height * 0.4):
            lines.append([x, y, x + w, y + h])

    # Cells = white regions fully enclosed by the line grid.
    grid = cv2.bitwise_or(horizontal, vertical)
    cells = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_not(grid), connectivity=4)
    for index in range(1, count):
        x, y, w, h, _ = stats[index]
        touches_edge = x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1
        if touches_edge or h < 0.8 * text_height or w < 1.5 * text_height:
            continue
        if w * h > 0.5 * width * height:
            continue
        cells.append([int(x), int(y), int(x + w), int(y + h)])

    # Checkboxes = small, roughly square closed outlines about the size of a letter.
    # Boxes = wider empty rectangles (write-in boxes) that are not part of a table grid.
    checkboxes, boxes = [], []
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (w >= 3 * text_height and 0.8 * text_height <= h <= 6 * text_height
                and cv2.contourArea(contour) >= 0.85 * w * h):
            inner = binary[y + h // 5: y + 4 * h // 5, x + w // 20: x + 19 * w // 20]
            if inner.size and inner.mean() / 255 < 0.05:
                boxes.append([x, y, x + w, y + h])
            continue
        if not (0.6 * text_height <= w <= 2.0 * text_height and 0.8 <= w / max(1, h) <= 1.25):
            continue
        approx = cv2.approxPolyDP(contour, 0.08 * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        inside = binary[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4]
        # A box has four straight inked sides; letters like o, e, B, D, P do not.
        band = max(2, min(w, h) // 8)
        sides = [binary[y:y + band, x:x + w].max(axis=0), binary[y + h - band:y + h, x:x + w].max(axis=0),
                 binary[y:y + h, x:x + band].max(axis=1), binary[y:y + h, x + w - band:x + w].max(axis=1)]
        if not all(side.size and (side > 0).mean() >= 0.85 for side in sides):
            continue
        if inside.size and inside.mean() / 255 < 0.25 and not _inside_letters([x, y, x + w, y + h], items):
            checkboxes.append([x, y, x + w, y + h])
    return {'lines': lines, 'cells': cells, 'checkboxes': _dedupe(checkboxes),
            'boxes': _dedupe(boxes)}


def _dedupe(boxes):
    kept = []
    for box in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        if not any(_overlap(box[0], box[2], k[0], k[2]) and _overlap(box[1], box[3], k[1], k[3])
                   for k in kept):
            kept.append(box)
    return kept


def _same_row(a, b, share=0.5):
    return _overlap(a[1], a[3], b[1], b[3]) >= share * min(a[3] - a[1], b[3] - b[1])


def _cell_of(box, cells):
    """Smallest cell that contains the centre of box."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    inside = [c for c in cells if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
    return min(inside, key=lambda c: (c[2] - c[0]) * (c[3] - c[1])) if inside else None


def next_to_checkbox(box, checkboxes, text_height):
    """True if text starts at (OCR boxes often swallow it) or just right of a checkbox."""
    return any(_same_row(box, c, 0.3) and c[0] - text_height * 0.5 <= box[0] <= c[2] + 1.5 * text_height
               for c in checkboxes)


def nearby_checkboxes(label_box, regions, items, text_height, right_limit):
    """Checkboxes on the label's row, between the label and the next label/limit."""
    return [c for c in regions['checkboxes']
            if c[0] >= label_box[2] - text_height and c[2] <= right_limit
            and _same_row(label_box, c, 0.3)]


def find_answer_box(label_box, page_items, regions, page_size, text_height,
                    answer_entities=(), label_items=(), right_limit=None):
    """Return (answer_box or None, method). label_items = OCR items that form the label."""
    width, height = page_size
    gap = text_height * 0.3
    text_right = max((item['box'][2] for item in page_items), default=width)
    right_edge = min(width - 1, right_limit if right_limit is not None else text_right)

    # 0. A group of checkboxes on the label's row is the answer (LayoutLM tends to mark one option).
    boxes = nearby_checkboxes(label_box, regions, page_items, text_height, right_edge + text_height)
    if len(boxes) >= 2:
        return [min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes)], 'checkboxes'

    # 1. LayoutLM answer on the same row to the right, or right below the label.
    for answer in answer_entities:
        box = answer['box']
        right = (_same_row(label_box, box) and label_box[2] - gap <= box[0] < right_edge
                 and box[0] - label_box[2] <= 6 * text_height)
        below = (0 <= box[1] - label_box[3] <= 1.5 * text_height
                 and _overlap(label_box[0], label_box[2], box[0], box[2]) > 0)
        if right or below:
            return box, 'layoutlm_answer'

    # 2. Table cell: the empty cell to the right of the label's cell, or the empty part of its own.
    own = _cell_of(label_box, regions['cells'])
    if own is not None:
        neighbours = [c for c in regions['cells']
                      if c is not own and abs(c[0] - own[2]) <= 2 * gap + 6 and _same_row(label_box, c, 0.5)]
        for cell in sorted(neighbours, key=lambda c: c[0]):
            if not _contains_text(cell, page_items):
                return cell, 'table_cell'
        free = [label_box[2] + gap, own[1], own[2], own[3]]
        if free[2] - free[0] >= 3 * text_height and not _contains_text(free, page_items, label_items):
            return [int(v) for v in free], 'own_cell'

    # 3a. Empty write-in box on the label's row, starting close to the label.
    for box in sorted(regions.get('boxes', []), key=lambda b: b[0]):
        if (_same_row(label_box, box, 0.5) and box[0] < right_edge
                and label_box[2] - text_height <= box[0] <= label_box[2] + 3 * text_height
                and not _contains_text(box, page_items, label_items)):
            return box, 'box'

    # 3b. Underline starting near the label's bottom, to its right.
    for line in sorted(regions['lines'], key=lambda l: l[0]):
        y = (line[1] + line[3]) / 2
        if (label_box[1] <= y <= label_box[3] + text_height
                and label_box[2] - 2 * text_height <= line[0] <= label_box[2] + 3 * text_height
                and line[0] < right_edge
                and line[2] - line[0] >= 2 * text_height):
            box = [max(line[0], label_box[2]), int(y - 1.2 * text_height), line[2], int(y)]
            if not _contains_text(box, page_items, label_items):
                return box, 'underline'

    # 3c. Label printed above its input: an underline or write-in box just below the label,
    #     starting near the label's left edge, with no text in between. Not inside table cells,
    #     where the line below a label is the cell border.
    if own is None:
        below = [(b[1], b, 'box_below') for b in regions.get('boxes', [])]
        below += [((l[1] + l[3]) / 2, l, 'underline_below') for l in regions['lines']]
        for y, shape, kind in sorted(below, key=lambda entry: entry[0]):
            if not (label_box[3] <= y <= label_box[3] + 2.5 * text_height):
                continue
            if not (abs(shape[0] - label_box[0]) <= 2 * text_height
                    and shape[2] - shape[0] >= 2 * text_height and shape[0] < right_edge):
                continue
            box = (list(shape) if kind == 'box_below'
                   else [shape[0], int(max(label_box[3], y - 1.2 * text_height)), shape[2], int(y)])
            gap = [box[0], label_box[3], box[2], box[3]]
            if not _contains_text(gap, page_items, label_items):
                return [int(v) for v in box], kind

    # 4. Checkboxes on the label's row.
    boxes = nearby_checkboxes(label_box, regions, page_items, text_height, right_edge + text_height)
    if boxes:
        return [min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes)], 'checkboxes'

    # 4b. Label printed under its line ('Signature', 'Date' below a signing line): a line right
    #     above the label that spans it, with no other text under it and nothing written on it.
    for line in sorted(regions['lines'], key=lambda l: -l[1]):
        y = (line[1] + line[3]) / 2
        if not (0 <= label_box[1] - y <= LINE_ABOVE_GAP * text_height):
            continue
        if not (line[0] <= label_box[0] + text_height and line[2] >= label_box[2] - text_height
                and line[2] - line[0] >= 3 * text_height):
            continue
        others_under = [item for item in page_items  # (label items may be copies: compare boxes)
                        if not _contains_text(label_box, [item], min_share=0.5)
                        and _same_row(label_box, item['box'], 0.3)
                        and _overlap(line[0], line[2], item['box'][0], item['box'][2]) > 0]
        box = [line[0], int(y - 1.2 * text_height), line[2], int(y)]
        if not others_under and not _contains_text(box, page_items, label_items):
            return box, 'line_above'

    # 5. Empty space to the right on the same row (up to the next text).
    row_text = [item for item in page_items if not any(item is l for l in label_items)
                and _same_row(label_box, item['box'], 0.3) and item['box'][0] > label_box[2]]
    stop = min([item['box'][0] for item in row_text] + [right_edge])
    if stop - label_box[2] >= 4 * text_height:
        return [int(label_box[2] + gap), label_box[1], int(stop - gap), label_box[3]], 'empty_right'

    # 6. Empty space below the label (up to the next text below).
    below_text = [item for item in page_items if item['box'][1] >= label_box[3]
                  and _overlap(label_box[0], right_edge, item['box'][0], item['box'][2]) > 0]
    stop = min([item['box'][1] for item in below_text] + [height - 1])
    if stop - label_box[3] >= 1.2 * text_height:
        bottom = min(stop - gap, label_box[3] + 3 * text_height)
        return [label_box[0], int(label_box[3] + gap), int(right_edge), int(bottom)], 'empty_below'
    return None, 'none'
