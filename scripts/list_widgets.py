"""List every AcroForm widget of PDFs with pypdf only (no project code): independent ground truth
for checking what layout.py finds on a fillable form.

Usage: .venv\\Scripts\\python.exe scripts\\list_widgets.py FORM.pdf [MORE.pdf ...]

Per PDF: pages and sizes, encryption, XFA, NeedAppearances, calculation order, widget count,
hierarchical and repeated names; then one line per widget (page, full name, type, /Ff, annotation
/F, rect in points, tooltip, flags, max length, options, on-states, format script, value), and the
read-only / hidden / push-button counts.
"""
import collections
import sys

from pypdf import PdfReader

FIELD_TYPES = {'/Tx': 'text', '/Btn': 'button', '/Ch': 'choice', '/Sig': 'signature'}
FLAG_NAMES = [(1, 'RO'), (2, 'Req'), (13, 'Multiline'), (14, 'Password'), (19, 'Edit'),
              (22, 'MultiSelect'), (23, 'DoNotSpell'), (25, 'Comb'), (26, 'RadiosInUnison')]


def inherited(node, key):
    """A field attribute, looked up the /Parent chain."""
    while node is not None:
        if key in node:
            return node[key]
        parent = node.get('/Parent')
        node = parent.get_object() if parent is not None else None
    return None


def full_name(node):
    parts = []
    while node is not None:
        if '/T' in node:
            parts.append(str(node['/T']))
        parent = node.get('/Parent')
        node = parent.get_object() if parent is not None else None
    return '.'.join(reversed(parts))


def widget_type(field_type, ff):
    kind = FIELD_TYPES.get(field_type, str(field_type))
    if kind == 'button':
        return 'pushbutton' if ff & (1 << 16) else 'radio' if ff & (1 << 15) else 'checkbox'
    if kind == 'choice':
        return 'combo' if ff & (1 << 17) else 'list'
    return kind


def options(field):
    raw = inherited(field, '/Opt')
    if raw is None:
        return None
    result = []
    for entry in raw.get_object():
        entry = entry.get_object()
        result.append(str(entry[1]) if isinstance(entry, list) and len(entry) == 2 else str(entry))
    return result


def format_script(field):
    actions = inherited(field, '/AA')
    if actions is None or '/F' not in actions.get_object():
        return None
    script = actions.get_object()['/F'].get_object().get('/JS')
    return str(script.get_object() if hasattr(script, 'get_object') else script)[:40] if script else None


def describe(path):
    reader = PdfReader(path)
    print('=' * 100)
    print(path)
    print('encrypted:', reader.is_encrypted, '| pages:', len(reader.pages))
    for number, page in enumerate(reader.pages, 1):
        print(f'  page {number}: mediabox {[round(float(v), 2) for v in page.mediabox]} '
              f'cropbox {[round(float(v), 2) for v in page.cropbox]} rotate {page.get("/Rotate", 0)}')
    acroform = reader.trailer['/Root'].get('/AcroForm')
    acroform = acroform.get_object() if acroform is not None else None
    print('AcroForm:', acroform is not None)
    if acroform is not None:
        order = [full_name(ref.get_object()) for ref in acroform.get('/CO', [])]
        print('  XFA:', '/XFA' in acroform, '| NeedAppearances:', acroform.get('/NeedAppearances'),
              '| top-level /Fields:', len(acroform.get('/Fields', [])), '| calculation order:', order)
    meta = reader.metadata or {}
    print('Producer:', meta.get('/Producer'), '| Creator:', meta.get('/Creator'))

    widgets = [(number, annot.get_object()) for number, page in enumerate(reader.pages, 1)
               for annot in page.get('/Annots') or [] if annot.get_object().get('/Subtype') == '/Widget']
    by_name = collections.OrderedDict()
    for number, widget in widgets:
        field = widget if '/T' in widget else widget['/Parent'].get_object()
        by_name.setdefault(full_name(field), []).append((number, widget, field))
    print('total widgets:', len(widgets), '| distinct field names:', len(by_name),
          '| hierarchical names:', [n for n in by_name if '.' in n],
          '| names with >1 widget:', {n: len(w) for n, w in by_name.items() if len(w) > 1})

    read_only = hidden = push = 0
    for number_in_list, (name, entries) in enumerate(by_name.items(), 1):
        for page_number, widget, field in entries:
            ff = int(inherited(field, '/Ff') or 0)
            kind = widget_type(inherited(field, '/FT'), ff)
            annot_flags = int(widget.get('/F', 0))
            push += kind == 'pushbutton'
            hidden += bool(annot_flags & 2 or annot_flags & 32)
            read_only += bool(ff & 1)
            states = None
            appearance = widget.get('/AP')
            if kind in ('checkbox', 'radio') and appearance is not None and '/N' in appearance.get_object():
                normal = appearance.get_object()['/N'].get_object()
                states = [k for k in normal.keys() if k != '/Off'] if hasattr(normal, 'keys') else None
            actions = inherited(field, '/AA')
            calculated = actions is not None and '/C' in actions.get_object()
            flags = [label for bit, label in FLAG_NAMES if ff & (1 << (bit - 1))]
            print(f'{number_in_list:>3} p{page_number} {name!r:<32} {kind:<10} Ff={ff:<7} F={annot_flags:<3} '
                  f'rect={[round(float(v), 1) for v in widget["/Rect"]]} TU={inherited(field, "/TU")!r} '
                  f'flags={flags} maxlen={inherited(field, "/MaxLen")} opts={options(field)} on={states} '
                  f'fmt={format_script(field)!r} calc={calculated} V={inherited(field, "/V")!r}')
    print('read-only:', read_only, '| hidden widgets (annotation flag Hidden/NoView):', hidden,
          '| push-button widgets:', push)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for pdf_path in sys.argv[1:]:
        describe(pdf_path)
