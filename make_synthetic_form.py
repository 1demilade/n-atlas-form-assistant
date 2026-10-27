"""Generate a synthetic blank form (PNG) plus ground truth (JSON) for testing generalisation.

Different wording, layout, image size and answer styles from any real sample, chosen by --seed.
Usage: python make_synthetic_form.py --out synthetic_form.png --seed 1 --width 1400 --height 1000
"""
import argparse
import json
import random

from PIL import Image, ImageDraw, ImageFont

# (label, expected type, answer style). Styles: line, box, yesno, choice:<a>|<b>|...
FIELD_POOL = [
    ('Patient name', 'text', 'line'),
    ('Email address', 'email', 'line'),
    ('Date of visit', 'date', 'box'),
    ('Mobile phone', 'phone', 'line'),
    ('Number of children', 'number', 'box'),
    ('Do you smoke?', 'yes_no', 'yesno'),
    ('Preferred contact', 'choice', 'choice:Email|SMS|Call'),
    ('Home address', 'text', 'line'),
    ('Employer', 'unknown', 'line'),
    ('Blood group', 'unknown', 'box'),
    ('Are you a student?', 'yes_no', 'yesno'),
    ('Age', 'number', 'box'),
    ('Marital status', 'choice', 'choice:Single|Married|Other'),
    ('Next of kin', 'unknown', 'line'),
    ('Telephone', 'phone', 'line'),
    ('Town', 'text', 'line'),
]
TITLES = ['CLINIC REGISTRATION', 'MEMBERSHIP APPLICATION', 'SURVEY SHEET', 'ENROLMENT FORM']


def load_font(size):
    for name in ('arial.ttf', 'DejaVuSans.ttf', 'calibri.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def make_form(width=1400, height=1000, seed=1, count=8):
    rng = random.Random(seed)
    fields = rng.sample(FIELD_POOL, min(count, len(FIELD_POOL)))
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    text_size = max(14, height // 45)
    font, title_font = load_font(text_size), load_font(int(text_size * 1.4))
    margin = width // 14
    title = rng.choice(TITLES)
    draw.text((margin, margin // 2), title, fill='black', font=title_font)
    draw.text((margin, margin // 2 + int(text_size * 2.2)),
              'Please complete all sections in block letters.', fill='black', font=font)

    columns = rng.choice([1, 2])
    column_width = (width - 2 * margin) // columns
    rows = (len(fields) + columns - 1) // columns
    top = margin // 2 + int(text_size * 5)
    row_height = min(int(text_size * 3.2), (height - top - margin // 2) // max(1, rows))
    colon = rng.choice([':', ''])
    truth = []
    for index, (label, kind, style) in enumerate(fields):
        column, row = index % columns, index // columns
        x = margin + column * column_width
        y = top + row * row_height
        text = label if label.endswith('?') else label + colon
        draw.text((x, y), text, fill='black', font=font)
        label_box = list(draw.textbbox((x, y), text, font=font))
        ax = label_box[2] + text_size
        right = x + column_width - text_size
        bottom = label_box[3] + text_size // 3
        if style == 'line':
            draw.line((ax, bottom, right, bottom), fill='black', width=2)
            answer = [ax, label_box[1] - text_size // 3, right, bottom]
        elif style == 'box':
            answer = [ax, label_box[1] - text_size // 2, min(right, ax + 12 * text_size),
                      label_box[3] + text_size // 2]
            draw.rectangle(answer, outline='black', width=2)
        else:
            options = ['Yes', 'No'] if style == 'yesno' else style.split(':', 1)[1].split('|')
            cx = ax
            boxes = []
            for option in options:
                box = [cx, label_box[1], cx + text_size, label_box[1] + text_size]
                draw.rectangle(box, outline='black', width=2)
                boxes.append(box)
                draw.text((cx + int(text_size * 1.4), label_box[1]), option, fill='black', font=font)
                cx += int(text_size * 1.4) + int(draw.textlength(option, font=font)) + text_size * 2
            answer = [boxes[0][0], min(b[1] for b in boxes), boxes[-1][2], max(b[3] for b in boxes)]
        truth.append({'label': label, 'type': kind, 'style': style,
                      'label_box': [int(v) for v in label_box], 'answer_box': [int(v) for v in answer]})
    return image, {'width': width, 'height': height, 'seed': seed, 'title': title, 'fields': truth}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='synthetic_form.png')
    parser.add_argument('--truth', help='ground-truth JSON path (default: OUT with .json)')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--width', type=int, default=1400)
    parser.add_argument('--height', type=int, default=1000)
    parser.add_argument('--count', type=int, default=8)
    args = parser.parse_args()
    image, truth = make_form(args.width, args.height, args.seed, args.count)
    image.save(args.out)
    truth_path = args.truth or args.out.rsplit('.', 1)[0] + '.json'
    with open(truth_path, 'w', encoding='utf-8') as file:
        json.dump(truth, file, indent=2)
    print(f"Saved {args.out} ({args.width}x{args.height}, {len(truth['fields'])} fields) and {truth_path}")


if __name__ == '__main__':
    main()
