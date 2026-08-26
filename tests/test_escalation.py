from src import escalation
from src.session import ConversationSession


def test_create_handoff_appends_to_session_and_fills_language_from_profile():
    session = ConversationSession(session_id="voice:+1", channel="voice")
    session.patient_profile.language = "Hungarian"

    event = escalation.create_handoff(
        session, reason_code="phi_or_patient_specific", summary="Asked about a relative's ward."
    )

    assert session.handoffs == [event]
    assert event.language == "Hungarian"
    assert event.channel == "voice"
    assert event.session_id == session.session_id
    assert event.ticket_id.startswith("H-")


def test_create_handoff_explicit_language_overrides_profile():
    session = ConversationSession(session_id="whatsapp:+2", channel="whatsapp")
    session.patient_profile.language = "Romanian"

    event = escalation.create_handoff(
        session,
        reason_code="language_not_supported",
        summary="Patient speaks Polish, no doctor available.",
        patient_language="Polish",
    )

    assert event.language == "Polish"
    assert event.reason_code == "language_not_supported"


def test_ticket_ids_are_unique_across_calls():
    session = ConversationSession(session_id="voice:+3", channel="voice")
    e1 = escalation.create_handoff(session, "out_of_scope", "test 1")
    e2 = escalation.create_handoff(session, "out_of_scope", "test 2")
    assert e1.ticket_id != e2.ticket_id


def test_valid_reason_codes_cover_all_enum_members():
    assert escalation.VALID_REASON_CODES == {
        "phi_or_patient_specific",
        "explicit_human_request",
        "out_of_scope",
        "unresolved_after_attempt",
        "language_not_supported",
        "safety_concern",
    }
