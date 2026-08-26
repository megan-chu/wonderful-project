from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx2

from src.agent import Agent
from src.session import ConversationSession


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(tool_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(stop_reason: str, content: list) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def refusal_response(category: str | None = "frontier_llm") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="refusal",
        content=[],
        stop_details=SimpleNamespace(type="refusal", category=category, explanation=None),
    )


def make_agent(directory, responses) -> Agent:
    client = MagicMock()
    client.messages.create.side_effect = responses
    return Agent(client=client, directory=directory, max_tool_iterations=4)


def effort_unsupported_error() -> anthropic.BadRequestError:
    http_response = httpx2.Response(
        400,
        json={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "This model does not support the effort parameter.",
            },
        },
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    return anthropic.BadRequestError(
        "This model does not support the effort parameter.",
        response=http_response,
        body=http_response.json(),
    )


def test_happy_path_tool_call_then_final_answer(directory):
    responses = [
        response(
            "tool_use",
            [tool_use_block("t1", "find_doctors", {"speciality": "Cardiology", "limit": 5})],
        ),
        response("end_turn", [text_block("Here are our cardiologists.")]),
    ]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="whatsapp:+1", channel="whatsapp")

    result = agent.run_turn(session, "Which cardiologists do you have?")

    assert result.reply_text == "Here are our cardiologists."
    assert result.escalated is False
    assert result.handoff is None
    assert result.tool_trace[0]["name"] == "find_doctors"
    assert result.tool_trace[0]["result"]["total_matches"] > 0
    # session history: user msg, assistant tool_use, user tool_result, assistant final
    assert len(session.history) == 4


def test_escalation_path_sets_flags_and_records_handoff(directory):
    responses = [
        response(
            "tool_use",
            [
                tool_use_block(
                    "t1",
                    "escalate_to_human",
                    {"reason_code": "phi_or_patient_specific", "summary": "Asked about a relative's ward."},
                )
            ],
        ),
        response("end_turn", [text_block("Connecting you with a colleague now.")]),
    ]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="voice:+1", channel="voice")

    result = agent.run_turn(session, "What ward is my father in?")

    assert result.escalated is True
    assert result.handoff is not None
    assert result.handoff.reason_code == "phi_or_patient_specific"
    assert session.handoffs == [result.handoff]


def test_update_patient_profile_persists_on_session(directory):
    responses = [
        response(
            "tool_use",
            [tool_use_block("t1", "update_patient_profile", {"language": "Romanian"})],
        ),
        response("end_turn", [text_block("Buna ziua! Cum va pot ajuta?")]),
    ]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="whatsapp:+2", channel="whatsapp")

    agent.run_turn(session, "Buna ziua")

    assert session.patient_profile.language == "Romanian"
    assert session.patient_profile.language_supported is True


def test_loop_safety_net_force_escalates_when_never_reaching_end_turn(directory):
    # Every response keeps calling a tool, never end_turn - the manual loop
    # must not run forever and must escalate instead.
    responses = [
        response("tool_use", [tool_use_block(f"t{i}", "list_locations", {})]) for i in range(4)
    ]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="voice:+3", channel="voice")

    result = agent.run_turn(session, "Some request the agent keeps looping on.")

    assert result.escalated is True
    assert result.handoff is not None
    assert result.handoff.reason_code == "unresolved_after_attempt"
    assert "colleague" in result.reply_text.lower()


def test_falls_back_and_stops_sending_effort_when_model_rejects_it(directory):
    # Some models (e.g. Haiku 4.5, Sonnet 4.5) reject output_config.effort
    # entirely - the agent should retry once without it, then stop sending
    # it on later calls/turns rather than failing every request forever.
    client = MagicMock()
    client.messages.create.side_effect = [
        effort_unsupported_error(),
        response("end_turn", [text_block("Bonjour, comment puis-je vous aider ?")]),
        response("end_turn", [text_block("Bien sur.")]),
    ]
    agent = Agent(client=client, directory=directory, max_tool_iterations=4)
    session = ConversationSession(session_id="whatsapp:+9", channel="whatsapp")

    first = agent.run_turn(session, "Bonjour")
    assert first.reply_text == "Bonjour, comment puis-je vous aider ?"
    assert agent._effort_supported is False

    second = agent.run_turn(session, "Autre question")
    assert second.reply_text == "Bien sur."

    calls = client.messages.create.call_args_list
    assert "output_config" in calls[0].kwargs  # first attempt still tried it
    assert "output_config" not in calls[1].kwargs  # retry dropped it
    assert "output_config" not in calls[2].kwargs  # next turn never re-adds it


def test_refusal_stop_reason_escalates_instead_of_showing_blank_reply(directory):
    responses = [refusal_response(category="frontier_llm")]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="voice:+5", channel="voice")

    result = agent.run_turn(session, "Some request the model refuses outright.")

    assert result.reply_text  # never blank
    assert result.escalated is True
    assert result.handoff is not None
    assert result.handoff.reason_code == "out_of_scope"
    assert "frontier_llm" in result.handoff.summary


def test_empty_text_content_falls_back_to_a_safe_message_not_blank(directory):
    # No text block at all in an end_turn response (e.g. only a thinking
    # block reached the client) - must never surface as an empty reply.
    responses = [response("end_turn", [SimpleNamespace(type="thinking", thinking="")])]
    agent = make_agent(directory, responses)
    session = ConversationSession(session_id="whatsapp:+6", channel="whatsapp")

    result = agent.run_turn(session, "Hello")

    assert result.reply_text
    assert result.escalated is False
