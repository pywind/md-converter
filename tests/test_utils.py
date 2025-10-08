from markdown_converter.utils import generate_run_id, normalize_newlines, slugify


def test_slugify_basic() -> None:
    assert slugify("Hello World!.pdf") == "Hello-World.pdf"


def test_normalize_newlines() -> None:
    text = "line1\r\nline2 \n"
    assert normalize_newlines(text) == "line1\nline2\n"


def test_generate_run_id_unique() -> None:
    first = generate_run_id("test")
    second = generate_run_id("test")
    assert first != second
    assert first.startswith("test-")
