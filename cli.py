import argparse

import anthropic

from src import config
from src.agent import Agent
from src.channels import voice_sim, whatsapp_sim
from src.directory import build_directory
from src.session import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Maria Care multilingual patient assistant (simulated voice + WhatsApp channels)."
    )
    parser.add_argument("channel", choices=["voice", "whatsapp", "demo"])
    parser.add_argument(
        "--model",
        default=config.MODEL_ID,
        help=f"Anthropic model id to use (default: {config.MODEL_ID}, or $MARIA_CARE_MODEL if set).",
    )
    args = parser.parse_args()

    directory = build_directory()
    client = anthropic.Anthropic()
    agent = Agent(client=client, directory=directory, model=args.model)

    if args.channel == "demo":
        from scripts.demo_transcript import run_demo

        run_demo(agent)
        return

    store = SessionStore()
    if args.channel == "voice":
        voice_sim.run(agent, store)
    else:
        whatsapp_sim.run(agent, store)


if __name__ == "__main__":
    main()
