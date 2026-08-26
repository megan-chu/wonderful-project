"""Simulated phone-call channel: a CLI standing in for a real Twilio Voice call.

Typed input here stands in 1:1 for an already-transcribed speech utterance -
no real ASR/TTS is in scope. A future live integration would only need to
convert audio <-> text at this boundary; the Agent core underneath is unchanged.
"""

from src.agent import Agent
from src.session import SessionStore


def run(agent: Agent, store: SessionStore) -> None:
    caller_id = input("Simulated caller phone number (Enter for default): ").strip()
    caller_id = caller_id or "+40-700-000-000"
    session = store.get_or_create("voice", caller_id)

    print("\n--- Incoming call ---")
    print("Type what the caller says, in any language. Type 'hangup' to end the call.\n")

    while True:
        try:
            user_text = input("Caller: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n--- Call ended ---")
            break

        if not user_text:
            continue
        if user_text.lower() in ("hangup", "exit", "quit"):
            print("--- Call ended ---")
            break

        response = agent.run_turn(session, user_text)
        print(f"Agent: {response.reply_text}")
        if response.escalated and response.handoff:
            print(
                f">>> [CALL TRANSFERRED - reason={response.handoff.reason_code}, "
                f"ticket={response.handoff.ticket_id}]"
            )
