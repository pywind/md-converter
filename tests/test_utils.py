from core.markdown_converter.utils import (
    generate_run_id,
    normalize_newlines,
    slugify,
)


def test_generate_run_id_unique():
    first = generate_run_id()
    second = generate_run_id()
    assert first != second
    assert first.startswith("run-")


def test_slugify_preserves_safe_characters():
    assert slugify("Hello World!") == "Hello-World"


def test_normalize_newlines_appends_trailing_newline():
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc\n"
