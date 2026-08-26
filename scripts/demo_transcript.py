"""Scripted multilingual demo proving the acceptance criteria end-to-end.

Requires ANTHROPIC_API_KEY. Run via `python cli.py demo`.
"""

from src.agent import Agent
from src.session import SessionStore

DEMO_SCRIPT = [
    # Direct lookup, answered in Romanian, then a same-session English follow-up
    # using conversation memory (no need to restate location/speciality).
    ("whatsapp", "+40-700-000-001", "Ce doctori de psihiatrie aveți în Cluj-Napoca?"),
    ("whatsapp", "+40-700-000-001", "does one of them speak English?"),
    # Generic "where/when" question, honestly aggregated across doctors (no
    # single fabricated clinic address/hours), answered in German.
    ("voice", "+49-170-000-002", "Wo befindet sich die Klinik in Iasi und wann hat sie geöffnet?"),
    # Recommendation flow: patient states the need, agent should elicit
    # location/time preference, then recommend a matching doctor.
    ("voice", "+49-170-000-002", "Can you recommend a dermatologist for me?"),
    ("voice", "+49-170-000-002", "I'm based in Timisoara and mornings work best for me."),
    # Unsupported-language fallback: Polish isn't one of Maria Care's 7
    # dataset languages, so recommend_doctors should report language_supported=false.
    ("whatsapp", "+48-600-000-003", "Szukam pediatry mówiącego po ukraińsku."),
    # PHI/patient-specific question - must escalate immediately, in Hungarian.
    ("voice", "+36-30-000-004", "Szeretném megtudni, melyik kórteremben van az édesapám."),
]


def run_demo(agent: Agent) -> None:
    store = SessionStore()
    for channel, external_id, message in DEMO_SCRIPT:
        session = store.get_or_create(channel, external_id)
        print(f"\n[{channel.upper()} {external_id}] Patient: {message}")
        response = agent.run_turn(session, message)
        print(f"[{channel.upper()} {external_id}] Agent: {response.reply_text}")
        if response.escalated and response.handoff:
            print(
                f">>> [ESCALATED - reason={response.handoff.reason_code}, "
                f"ticket={response.handoff.ticket_id}]"
            )


if __name__ == "__main__":
    import anthropic

    from src.directory import build_directory

    client = anthropic.Anthropic()
    directory = build_directory()
    run_demo(Agent(client=client, directory=directory))
