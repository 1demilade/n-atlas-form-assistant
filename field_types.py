"""Guess the kind of answer from the label words and nearby options. Generic keywords only."""
import re

ALLOWED_TYPES = ('text', 'number', 'date', 'yes_no', 'choice', 'email', 'phone', 'unknown')

YES_NO_WORDS = {'yes', 'no', 'y', 'n', 'true', 'false'}

# Checked in this order; the first matching rule wins.
KEYWORD_RULES = [
    ('email', r'\be-?mail\b'),
    ('phone', r'\b(phone|telephone|tel|mobile|gsm|cell(phone)?|whatsapp)\b'),
    ('date', r'\b(date|dob|d\.o\.b|birthday|dd\s*/\s*mm|mm\s*/\s*dd|yyyy)\b'),
    # 'Are you a ... (..., Other (Specify))', 'If yes, specify': the answer is text, not yes/no.
    ('text', r'\bspecify\b'),
    ('yes_no', r'^\s*(are|is|do|does|did|have|has|was|were|will|can)\s+(you|the|your|this|there)\b'
               r'|\(?\byes\s*/\s*no\b\)?'),
    ('choice', r'\b(select|choose|tick|check one|circle|which of)\b'),
    ('number', r'\b(number|no|num|amount|age|quantity|qty|total|price|cost|salary|income|'
               r'how many|count|zip|postcode|postal code|weight|height)\b'),
    ('text', r'(\b\w*names?\b|\b(address|street|city|town|village|state|country|county|region|'
             r'occupation|profession|job|title|nationality|description|describe|'
             r'nature|reason|purpose|comments?|remarks|explain)\b)'),
]


def guess_type(label, option_texts=(), checkbox_count=0):
    """Return one of ALLOWED_TYPES. Options next to the label beat label keywords."""
    options = {re.sub(r'[^a-z]', '', text.lower()) for text in option_texts}
    options.discard('')
    if options and options <= YES_NO_WORDS and len(options) >= 2:
        return 'yes_no'
    if checkbox_count >= 2 or len(options) >= 2:
        return 'choice'
    text = label.lower()
    for kind, pattern in KEYWORD_RULES:
        if re.search(pattern, text):
            return kind
    if checkbox_count == 1:
        return 'yes_no'
    return 'unknown'


# ---- Checking an answer against its type (used before writing it into a fillable PDF) ----
NUMBER = re.compile(r'^[+-]?(\d{1,3}(,\d{3})+|\d+)([.,]\d+)?%?$')
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')
PHONE = re.compile(r'^\+?[\d\s().\-/]+$')
PHONE_DIGITS = (7, 15)  # ITU E.164 allows at most 15 digits
DATE_FORMATS = ('%d/%m/%Y', '%m/%d/%Y', '%d/%m/%y', '%m/%d/%y', '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
                '%d.%m.%Y', '%Y/%m/%d', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y',
                '%B %d %Y', '%b %d %Y', '%d %B, %Y')


def check_value(field_type, value):
    """None if value fits field_type, else the reason it does not. text/unknown accept anything;
    choice and yes_no are checked against the field's options by the caller."""
    from datetime import datetime
    value = re.sub(r'\s+', ' ', str(value)).strip()
    if field_type == 'number' and not NUMBER.match(value):
        return f'{value!r} is not a number'
    if field_type == 'email' and not EMAIL.match(value):
        return f'{value!r} is not an email address'
    if field_type == 'phone':
        digits = len(re.sub(r'\D', '', value))
        if not PHONE.match(value) or not PHONE_DIGITS[0] <= digits <= PHONE_DIGITS[1]:
            return f'{value!r} is not a phone number'
    if field_type == 'date':
        for fmt in DATE_FORMATS:
            try:
                datetime.strptime(value, fmt)
                return None
            except ValueError:
                pass
        return f'{value!r} is not a date'
    return None
