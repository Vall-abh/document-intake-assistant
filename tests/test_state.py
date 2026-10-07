from app.schemas import FieldUpdate
from app.state import (apply_updates, is_complete, missing_fields, new_state, pending_field,
                       progress, unconfirmed_fields)


def up(field, value, confirmed=True):
    return FieldUpdate(field=field, value=value, confirmed=confirmed)


def apply(state, updates, msg):
    return apply_updates(state, updates, msg)


def test_valid_update_is_applied_and_confirmed():
    r = apply(new_state(), [up("full_name", "Jane Smith")], "I'm Jane Smith")
    assert r.state.data.full_name == "Jane Smith"
    assert r.state.status["full_name"] == "confirmed"


def test_input_state_is_not_mutated():
    s = new_state()
    apply(s, [up("full_name", "Jane Smith")], "Jane Smith")
    assert s.data.full_name is None


def test_unknown_field_and_wrong_type_rejected_individually():
    r = apply(new_state(), [up("colour", "blue"), up("has_children", "yes"), up("full_name", "Jane Smith")], "Jane Smith")
    assert r.state.data.full_name == "Jane Smith"
    assert r.state.data.has_children is None
    assert len(r.warnings) == 2 and len(r.clarifications) == 1


def test_value_not_in_user_message_is_downgraded_to_unconfirmed():
    r = apply(new_state(), [up("full_name", "Jane Smith")], "hello")
    assert r.state.status["full_name"] == "unconfirmed"


def test_hedged_update_is_unconfirmed_and_pending_confirmation():
    r = apply(new_state(), [up("covers_worldwide_assets", True, confirmed=False)], "maybe worldwide")
    assert unconfirmed_fields(r.state) == ["covers_worldwide_assets"]
    assert not is_complete(r.state)


def test_confirming_an_existing_value_is_allowed():
    s = apply(new_state(), [up("full_name", "Jane Smith", False)], "maybe Jane Smith").state
    r = apply(s, [up("full_name", "Jane Smith")], "yes")
    assert r.state.status["full_name"] == "confirmed"


def test_correction_overwrites():
    s = apply(new_state(), [up("full_name", "Jane Smith")], "Jane Smith").state
    r = apply(s, [up("full_name", "Jane Doe")], "actually it's Jane Doe")
    assert r.state.data.full_name == "Jane Doe"


def test_null_marks_field_skipped_not_missing():
    r = apply(new_state(), [up("home_address", None)], "I'd rather not say")
    assert r.state.status["home_address"] == "skipped"
    assert "home_address" not in missing_fields(r.state)


def test_empty_list_means_none_and_is_confirmed():
    r = apply(new_state(), [up("specific_gifts", [])], "none")
    assert r.state.data.specific_gifts == [] and r.state.status["specific_gifts"] == "confirmed"


def test_naming_children_implies_has_children():
    r = apply(new_state(), [up("children_names", ["Anna", "Ben"])], "Anna and Ben")
    assert r.state.data.has_children is True


def test_children_named_after_confirmed_no_children_is_a_conflict():
    s = apply(new_state(), [up("has_children", False)], "no children").state
    r = apply(s, [up("children_names", ["Tom"])], "Tom")
    assert r.state.data.children_names is None and r.clarifications


def test_confirmed_no_children_correction_clears_names():
    s = apply(new_state(), [up("children_names", ["Tom"])], "Tom").state
    r = apply(s, [up("has_children", False)], "actually I have no children")
    assert r.state.data.has_children is False and r.state.data.children_names is None


def test_children_names_required_only_if_has_children():
    s = apply(new_state(), [up("has_children", False)], "no").state
    assert "children_names" not in missing_fields(s)
    s = apply(new_state(), [up("has_children", True)], "yes").state
    assert "children_names" in missing_fields(s)


def test_pending_prefers_unconfirmed_so_ambiguity_is_resolved_immediately():
    s = apply(new_state(), [up("full_name", "Jane", False)], "maybe Jane").state
    assert pending_field(s) == "full_name"
    assert progress(s) == (0, 8)


def test_grounding_accepts_inserted_context_in_a_paraphrased_phrase():
    r = apply(new_state(), [up("specific_gifts", ["watch to Tom"])], "my watch to my son Tom")
    assert r.state.status["specific_gifts"] == "confirmed"


def test_grounding_still_rejects_a_completely_invented_name():
    r = apply(new_state(), [up("full_name", "Alice Smith")], "my watch to my son Tom")
    assert r.state.status["full_name"] == "unconfirmed"

def test_grounding_evidence_quote_must_be_in_user_text():
    r = apply(new_state(), [up("full_name", "Jane Smith")], "my name is Jane Smith")
    assert r.state.status["full_name"] == "confirmed"

def test_multiple_conflicts_are_all_reported_in_one_turn():
    from app.domain.state import WishesState
    from app.domain.updates import FieldUpdate as DomainUpdate, apply_updates as domain_apply
    s = domain_apply(WishesState(), [DomainUpdate(field="has_children", value=False)], "no children")[0]
    _, r = domain_apply(s, [DomainUpdate(field="children_names", value=["Tom"]), DomainUpdate(field="children_names", value=["Anna"])], "Tom and Anna")
    assert len(r.conflicts) == 2
