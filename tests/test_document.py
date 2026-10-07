from app.document import render_document
from app.schemas import FieldUpdate
from app.state import apply_updates, new_state


def build(*pairs, confirmed=True):
    ups = [FieldUpdate(field=f, value=v, confirmed=confirmed) for f, v in pairs]
    return apply_updates(new_state(), ups, " ".join(str(v) for _, v in pairs)).state


def test_empty_state_has_disclaimer_and_placeholders():
    doc = render_document(new_state())
    assert "FICTIONAL DOCUMENT - NOT LEGAL ADVICE" in doc
    assert "[NOT YET PROVIDED]" in doc and "incomplete" in doc


def test_complete_state_renders_all_sections():
    s = build(("full_name", "Jane Smith"), ("home_address", "1 Oak Road"), ("covers_worldwide_assets", True),
              ("has_children", False), ("executor.name", "James Smith"), ("executor.relationship", "brother"),
              ("specific_gifts", []), ("additional_wishes", []))
    doc = render_document(s)
    assert "I, Jane Smith, of 1 Oak Road" in doc
    assert "James Smith, my brother" in doc
    assert "I do not have any children." in doc and "complete and ready" in doc


def test_unconfirmed_values_are_never_shown_as_fact():
    doc = render_document(build(("full_name", "Jane Smith"), confirmed=False))
    assert "[TO CONFIRM: Jane Smith]" in doc


def test_skipped_and_lists_render():
    s = build(("home_address", None), ("has_children", True), ("children_names", ["Anna", "Ben"]))
    doc = render_document(s)
    assert "[NOT PROVIDED]" in doc and "1. Anna" in doc and "2. Ben" in doc
