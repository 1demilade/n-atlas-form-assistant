"""LayoutLM (FUNSD) token classification over OCR words -> question/answer/header entities."""
import re

import numpy as np

# ---- Config ----
MODEL_NAME = 'philschmid/layoutlm-funsd'
TOKENIZER_NAME = 'microsoft/layoutlm-base-uncased'
MAX_LENGTH = 512           # LayoutLM position limit
STRIDE = 128               # tokens shared between overlapping windows on long pages
ROW_TOLERANCE = 0.5        # boxes whose centres differ by < this * height are on one row
UNSURE_WORD = 0.6          # words below this probability join the previous entity on their line
LOCAL_FILES_ONLY = True    # never contact huggingface.co at run time; run download_models() once

_MODEL = None
_TOKENIZER = None
_DEVICE = None


def load_model():
    """Load model and tokenizer once; use GPU only if torch can see one."""
    global _MODEL, _TOKENIZER, _DEVICE
    if _MODEL is None:
        import torch
        from transformers import AutoTokenizer, LayoutLMForTokenClassification
        _DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
        _TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_NAME, local_files_only=LOCAL_FILES_ONLY)
        _MODEL = LayoutLMForTokenClassification.from_pretrained(
            MODEL_NAME, local_files_only=LOCAL_FILES_ONLY).to(_DEVICE).eval()
    return _MODEL, _TOKENIZER, _DEVICE


def download_models():
    """One-time download of the checkpoint and tokenizer into the Hugging Face cache."""
    from huggingface_hub import hf_hub_download
    for name in ('config.json', 'README.md', 'pytorch_model.bin'):
        hf_hub_download(MODEL_NAME, name)
    for name in ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'vocab.txt',
                 'special_tokens_map.json', 'README.md'):
        hf_hub_download(TOKENIZER_NAME, name)
    print('LayoutLM checkpoint and tokenizer are in the local cache.')


def split_label(label):
    """'B-QUESTION' -> ('B', 'question'); 'O' -> ('O', 'other'). Works for any BIO-style name."""
    match = re.match(r'^([BIES])-(.+)$', label)
    if match:
        return match.group(1), match.group(2).lower()
    return 'O', 'other' if label.upper() == 'O' else label.lower()


def reading_order(items):
    """Sort OCR items top-to-bottom, left-to-right, treating items on the same row together."""
    items = sorted(items, key=lambda item: (item['box'][1] + item['box'][3]) / 2)
    rows = []
    for item in items:
        centre = (item['box'][1] + item['box'][3]) / 2
        height = max(1, item['box'][3] - item['box'][1])
        if rows and abs(centre - rows[-1]['centre']) < ROW_TOLERANCE * min(height, rows[-1]['height']):
            rows[-1]['items'].append(item)
        else:
            rows.append({'centre': centre, 'height': height, 'items': [item]})
    return [item for row in rows for item in sorted(row['items'], key=lambda i: i['box'][0])]


def split_into_words(ocr_items):
    """Split each OCR line into words; give each word its share of the line box by characters.
    Items that already carry exact word boxes ('words', from a PDF text layer) use those."""
    words = []
    for line_index, item in enumerate(ocr_items):
        if item.get('words'):
            for word in item['words']:
                words.append({'text': word['text'], 'box': list(word['box']), 'line': line_index,
                              'score': item.get('score', 1.0)})
            continue
        text = item['text']
        x1, y1, x2, y2 = item['box']
        width = max(1, x2 - x1)
        for match in re.finditer(r'\S+', text):
            left = x1 + width * match.start() / max(1, len(text))
            right = x1 + width * match.end() / max(1, len(text))
            words.append({
                'text': match.group(),
                'box': [int(round(left)), y1, int(round(right)), y2],
                'line': line_index,
                'score': item.get('score', 1.0),
            })
    return words


def normalize_box(box, width, height):
    """Pixels -> LayoutLM's 0..1000 grid, using the real size of the OCR'd image."""
    def clamp(value):
        return max(0, min(1000, int(value)))
    return [clamp(1000 * box[0] / width), clamp(1000 * box[1] / height),
            clamp(1000 * box[2] / width), clamp(1000 * box[3] / height)]


def check_boxes_fit(ocr_items, width, height, page):
    """Fail loudly if OCR boxes come from a different-size image than the one we scale with."""
    max_x = max(item['box'][2] for item in ocr_items)
    max_y = max(item['box'][3] for item in ocr_items)
    if max_x > width * 1.02 or max_y > height * 1.02:
        raise ValueError(
            f'OCR boxes on page {page} reach ({max_x}, {max_y}) but the page image is '
            f'{width}x{height}. The OCR output and the image do not match.')


def classify_words(words, width, height):
    """Return per-word label probabilities, averaging over overlapping 512-token windows."""
    import torch
    model, tokenizer, device = load_model()
    num_labels = model.config.num_labels
    if not words:
        return np.zeros((0, num_labels))

    encoding = tokenizer(
        [word['text'] for word in words],
        is_split_into_words=True,
        truncation=True,
        max_length=MAX_LENGTH,
        stride=STRIDE,
        return_overflowing_tokens=True,
        padding='max_length',
        return_tensors='pt',
    )
    word_boxes = [normalize_box(word['box'], width, height) for word in words]
    sums = np.zeros((len(words), num_labels))
    counts = np.zeros(len(words))

    for window in range(encoding['input_ids'].shape[0]):
        word_ids = encoding.word_ids(window)
        bbox = []
        for token_index, word_id in enumerate(word_ids):
            if word_id is not None:
                bbox.append(word_boxes[word_id])
            elif encoding['input_ids'][window, token_index].item() == tokenizer.sep_token_id:
                bbox.append([1000, 1000, 1000, 1000])
            else:  # [CLS] and [PAD]
                bbox.append([0, 0, 0, 0])
        with torch.no_grad():
            logits = model(
                input_ids=encoding['input_ids'][window:window + 1].to(device),
                attention_mask=encoding['attention_mask'][window:window + 1].to(device),
                token_type_ids=encoding['token_type_ids'][window:window + 1].to(device),
                bbox=torch.tensor([bbox], device=device),
            ).logits[0]
        probabilities = torch.softmax(logits, dim=-1).cpu().numpy()
        previous = None
        for token_index, word_id in enumerate(word_ids):
            # Use the first sub-token of each word (standard for token classification).
            if word_id is not None and word_id != previous:
                sums[word_id] += probabilities[token_index]
                counts[word_id] += 1
            previous = word_id

    missing = np.where(counts == 0)[0]
    if len(missing):
        raise RuntimeError(f'{len(missing)} words were not covered by any LayoutLM window.')
    return sums / counts[:, None]


def group_entities(words, probabilities, id2label, page):
    """Join consecutive words on the same OCR line with the same entity type into one entity."""
    entities = []
    for word, probs in zip(words, probabilities):
        label_id = int(np.argmax(probs))
        tag, kind = split_label(id2label[label_id])
        current = entities[-1] if entities else None
        # An unsure word continues the entity before it on the same line.
        if current and current['line'] == word['line'] and probs[label_id] < UNSURE_WORD:
            tag, kind = 'I', current['kind']
        if (current and current['kind'] == kind and current['line'] == word['line']
                and tag != 'B'):
            current['words'].append(word)
            current['probs'].append(float(probs[label_id]))
        else:
            entities.append({'kind': kind, 'line': word['line'], 'words': [word],
                             'probs': [float(probs[label_id])]})
    result = []
    for entity in entities:
        boxes = [word['box'] for word in entity['words']]
        result.append({
            'kind': entity['kind'],
            'text': ' '.join(word['text'] for word in entity['words']),
            'box': [min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes)],
            'page': page,
            'confidence': float(np.mean(entity['probs'])),
        })
    return result


def extract_entities(ocr_items, pages):
    """Run LayoutLM on every page. pages = list of the images that were OCR'd (numpy HxWxC)."""
    model, _, _ = load_model()
    id2label = {int(key): value for key, value in model.config.id2label.items()}
    entities = []
    for page_number, image in enumerate(pages, start=1):
        page_items = [item for item in ocr_items if item.get('page', 1) == page_number]
        if not page_items:
            continue
        height, width = image.shape[:2]
        check_boxes_fit(page_items, width, height, page_number)
        page_items = reading_order(page_items)
        words = split_into_words(page_items)
        probabilities = classify_words(words, width, height)
        entities.extend(group_entities(words, probabilities, id2label, page_number))
    return entities
