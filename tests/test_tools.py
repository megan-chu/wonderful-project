from src import tools
from src.session import ConversationSession


def make_session() -> ConversationSession:
    return ConversationSession(session_id="test:1", channel="whatsapp")


def test_all_tool_definitions_are_well_formed(directory):
    defs = tools.build_tool_definitions(directory)
    names = [t["name"] for t in defs]

    assert len(names) == len(set(names)), "duplicate tool names"
    assert set(names) == {
        "list_locations",
        "list_specialities",
        "find_doctors",
        "get_doctor_details",
        "get_location_overview",
        "update_patient_profile",
        "recommend_doctors",
        "escalate_to_human",
    }
    for tool in defs:
        assert "description" in tool and tool["description"]
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_dispatch_list_locations_and_specialities(directory):
    session = make_session()
    result, event = tools.dispatch_tool("list_locations", {}, directory, session)
    assert event is None
    assert set(result["locations"]) == set(directory.list_locations())

    result, event = tools.dispatch_tool("list_specialities", {}, directory, session)
    assert set(result["specialities"]) == set(directory.list_specialities())


def test_dispatch_update_patient_profile_marks_language_support(directory):
    session = make_session()

    result, event = tools.dispatch_tool(
        "update_patient_profile", {"language": "Romanian"}, directory, session
    )
    assert event is None
    assert session.patient_profile.language == "Romanian"
    assert session.patient_profile.language_supported is True
    assert result["language_supported"] is True

    result, _ = tools.dispatch_tool(
        "update_patient_profile", {"language": "Klingon"}, directory, session
    )
    assert session.patient_profile.language_supported is False


def test_dispatch_update_patient_profile_stores_reason_for_visit(directory):
    session = make_session()

    result, event = tools.dispatch_tool(
        "update_patient_profile", {"reason_for_visit": "skin rash"}, directory, session
    )

    assert event is None
    assert session.patient_profile.reason_for_visit == "skin rash"
    assert result["reason_for_visit"] == "skin rash"
    # unrelated profile fields must be untouched by a partial update
    assert session.patient_profile.language is None


def test_dispatch_recommend_doctors_uses_stored_profile_as_default(directory):
    session = make_session()
    tools.dispatch_tool(
        "update_patient_profile",
        {"language": "German", "location_preference": "Turda"},
        directory,
        session,
    )

    result, event = tools.dispatch_tool(
        "recommend_doctors", {"speciality": "Dermatology", "limit": 2}, directory, session
    )

    assert event is None
    assert result["language_supported"] is True
    # No exact Turda match exists for Dermatology+German, so the top results
    # should be the same-county (Cluj-Napoca) fallback, picked up from the
    # profile defaults set by update_patient_profile above.
    assert all(d["match"]["location"] == "same_county" for d in result["doctors"])


def test_dispatch_escalate_to_human_creates_handoff_and_returns_event(directory):
    session = make_session()

    result, event = tools.dispatch_tool(
        "escalate_to_human",
        {"reason_code": "phi_or_patient_specific", "summary": "Patient asked about a relative's ward."},
        directory,
        session,
    )

    assert event is not None
    assert event.reason_code == "phi_or_patient_specific"
    assert result["ticket_id"] == event.ticket_id
    assert session.handoffs == [event]


def test_dispatch_get_doctor_details_error_path(directory):
    session = make_session()
    result, event = tools.dispatch_tool(
        "get_doctor_details", {"doctor_ref": "Nobody Here, Nowhere Clinic"}, directory, session
    )
    assert event is None
    assert "error" in result
