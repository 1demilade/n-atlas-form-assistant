from ocr import read_form


def test_read_form_returns_list():
    items = read_form('form.png')
    assert isinstance(items, list)
    assert items
    assert all(
        {'text', 'score', 'box', 'page'} <= set(item)
        for item in items
    )
    assert all(isinstance(item['box'], list) and len(item['box']) == 4 for item in items)
