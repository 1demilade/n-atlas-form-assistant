"""Guess the kind of answer from the label words and nearby options. Generic keywords only."""
import re

ALLOWED_TYPES = ('text', 'number', 'date', 'yes_no', 'choice', 'email', 'phone', 'unknown')

YES_NO_WORDS = {'yes', 'no', 'y', 'n', 'true', 'false'}

# Checked in this order; the first matching rule wins.
KEYWORD_RULES = [
    ('email', r'\be-?mail\b'),
    ('phone', r'\b(phone|telephone|tel|mobile|gsm|cell(phone)?|whatsapp)\b'),
    ('date', r'\b(date|dob|d\.o\.b|birthday|dd\s*/\s*mm|mm\s*/\s*dd|yyyy)\b'),
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
