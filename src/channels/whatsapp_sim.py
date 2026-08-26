"""Simulated WhatsApp channel: a CLI standing in for the WhatsApp Cloud API webhook.

A future live integration would replace this module's input/output boundary
with inbound/outbound webhook payloads; the Agent core underneath is unchanged.
"""

from src.agent import Agent
from src.session import SessionStore


def run(agent: Agent, store: SessionStore) -> None:
    contact_id = input("Simulated WhatsApp contact (Enter for default): ").strip()
    contact_id = contact_id or "+40-700-111-222"
    session = store.get_or_create("whatsapp", contact_id)

    print("\n--- WhatsApp chat ---")
    print("Type a message, in any language. Type 'exit' to leave the chat.\n")

    while True:
        try:
            user_text = input("Patient: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n--- Chat closed ---")
            break

        if not user_text:
            continue
        if user_text.lower() in ("exit", "quit"):
            print("--- Chat closed ---")
            break

        response = agent.run_turn(session, user_text)
        print(f"Maria Care Bot: {response.reply_text}")
        if response.escalated and response.handoff:
            print(
                f"[System] Conversation flagged for a team member "
                f"(ticket #{response.handoff.ticket_id}, reason: {response.handoff.reason_code})."
            )
