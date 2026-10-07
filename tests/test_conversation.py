import pytest

from app.conversation import (ConversationService, MalformedModelOutput, fallback_reply,
                              parse_model_output)
from app.llm.base import LLMUnavailable
from app.schemas import FieldUpdate
from app.state import apply_updates, new_state
from tests.conftest import ScriptedLLM, fixture


def run(session, text, *outputs, window=12):
    llm = ScriptedLLM(*outputs)
    return ConversationService(llm, window).handle_message(session, text), llm


def test_valid_turn_updates_state_and_uses_model_reply(session):
    result, _ = run(session, "I'm Jane Smith", fixture("valid_single"))
    assert session.state.data.full_name == "Jane Smith"
    assert result.reply == "Thanks Jane! What is your home address?"
    assert [m.role for m in session.messages] == ["user", "assistant"]


def test_multiple_fields_in_one_message(session):
    run(session, "I'm Jane Smith, no kids, my brother James Smith is executor", fixture("multi_field"))
    d = session.state.data
    assert (d.full_name, d.has_children, d.executor.name, d.executor.relationship) == ("Jane Smith", False, "James Smith", "brother")


def test_ambiguous_answer_stays_unconfirmed(session):
    run(session, "maybe worldwide?", fixture("ambiguous_worldwide"))
    assert session.state.status["covers_worldwide_assets"] == "unconfirmed"


def test_malformed_output_leaves_state_unchanged_and_degrades_gracefully(session):
    result, llm = run(session, "I'm Jane Smith", fixture("malformed_not_json"))
    assert session.state.data.full_name is None
    assert len(llm.requests) == 2  # one retry
    assert result.warnings and "rephrase" in result.reply


def test_malformed_then_valid_recovers_with_repair_hint(session):
    _, llm = run(session, "I'm Jane Smith", fixture("malformed_not_json"), fixture("valid_single"))
    assert session.state.data.full_name == "Jane Smith"
    assert llm.requests[0].repair_hint is None and "JSON" in llm.requests[1].repair_hint


def test_wrong_shape_is_malformed(session):
    result, _ = run(session, "hi", fixture("malformed_wrong_shape"))
    assert result.warnings and session.state.data.full_name is None


def test_fenced_json_is_accepted():
    assert parse_model_output(fixture("malformed_fenced_valid")).reply == "Hello there"


@pytest.mark.parametrize("raw", ["", "no braces", "{broken", "[]"])
def test_parse_rejects_garbage(raw):
    with pytest.raises(MalformedModelOutput):
        parse_model_output(raw)


def test_invalid_updates_rejected_and_reply_replaced_by_clarification(session):
    result, _ = run(session, "I'm Jane Smith", fixture("invalid_field_and_type"))
    assert session.state.data.full_name == "Jane Smith"
    assert session.state.data.has_children is None
    assert "couldn't record" in result.reply and "all saved" not in result.reply


def test_contradiction_is_not_applied_and_user_is_asked(session):
    session.state = apply_updates(new_state(), [FieldUpdate(field="has_children", value=False)], "no children").state
    result, _ = run(session, "my son is Tom", fixture("children_when_none"))
    assert session.state.data.children_names is None
    assert "no children" in result.reply


def test_invented_value_is_not_trusted(session):
    run(session, "hello", fixture("invented_name"))
    assert session.state.status["full_name"] == "unconfirmed"


def test_correction_replaces_previous_value(session):
    run(session, "I'm Jane Smith", fixture("valid_single"))
    run(session, "Actually my name is Jane Doe", fixture("correct_name"))
    assert session.state.data.full_name == "Jane Doe"


def test_empty_model_reply_falls_back_to_next_question(session):
    result, _ = run(session, "I'm Jane Smith", fixture("empty_reply"))
    assert result.reply == "What is your home address?"


def test_fallback_asks_for_confirmation_of_unconfirmed_values():
    s = apply_updates(new_state(), [FieldUpdate(field="full_name", value="Jane", confirmed=False)], "maybe Jane").state
    s = apply_updates(s, [FieldUpdate(field=f, value=v) for f, v in [
        ("home_address", "1 Road"), ("covers_worldwide_assets", True), ("has_children", False),
        ("executor.name", "Bob"), ("executor.relationship", "friend"), ("specific_gifts", []), ("additional_wishes", [])]],
        "1 Road True Bob friend").state
    assert fallback_reply(s).startswith("Just to confirm")


def test_history_is_windowed(session):
    for i in range(5):
        run(session, f"msg {i}", fixture("valid_single"))
    _, llm = run(session, "last", fixture("valid_single"), window=4)
    assert len(llm.requests[0].history) == 4


def test_provider_errors_propagate(session):
    with pytest.raises(LLMUnavailable):
        run(session, "hi", LLMUnavailable("down"))
    assert session.messages == []
