import json
import sys
from dataclasses import dataclass, field

import anthropic

from src import config, escalation, prompts, tools
from src.directory import ClinicDirectory
from src.escalation import HandoffEvent, ReasonCode
from src.session import ConversationSession


@dataclass
class AgentResponse:
    reply_text: str
    escalated: bool
    handoff: HandoffEvent | None
    tool_trace: list[dict] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        client,
        directory: ClinicDirectory,
        model: str = config.MODEL_ID,
        max_tokens: int = config.MAX_TOKENS,
        effort: str = config.EFFORT,
        max_tool_iterations: int = config.MAX_TOOL_ITERATIONS,
    ):
        self.client = client
        self.directory = directory
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.max_tool_iterations = max_tool_iterations
        # Not every model accepts output_config.effort (e.g. Haiku 4.5, Sonnet
        # 4.5); rather than hardcoding a model allowlist, just try once and
        # remember for the rest of this Agent's life if the API rejects it.
        self._effort_supported = True

    def _create_message(self, system: str, tool_defs: list[dict], messages: list[dict]):
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=tool_defs,
            messages=messages,
        )
        if self._effort_supported and self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        try:
            return self.client.messages.create(**kwargs)
        except anthropic.BadRequestError as e:
            if self._effort_supported and "effort" in str(e).lower():
                self._effort_supported = False
                kwargs.pop("output_config", None)
                return self.client.messages.create(**kwargs)
            raise

    def run_turn(self, session: ConversationSession, user_text: str) -> AgentResponse:
        session.history.append({"role": "user", "content": user_text})

        system = prompts.build_system_prompt(session.channel)
        tool_defs = tools.build_tool_definitions(self.directory)

        tool_trace: list[dict] = []
        escalated = False
        handoff: HandoffEvent | None = None
        response = None

        for _ in range(self.max_tool_iterations):
            response = self._create_message(system, tool_defs, session.history)
            session.history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for block in tool_use_blocks:
                result, event = tools.dispatch_tool(block.name, block.input, self.directory, session)
                tool_trace.append({"name": block.name, "input": block.input, "result": result})
                if event is not None:
                    escalated = True
                    handoff = event
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            session.history.append({"role": "user", "content": tool_results})
        else:
            # Loop-safety net: Claude kept calling tools without ever finishing.
            if handoff is None:
                handoff = escalation.create_handoff(
                    session,
                    reason_code=ReasonCode.UNRESOLVED_AFTER_ATTEMPT.value,
                    summary="Agent could not resolve the request within the tool-call budget.",
                )
                escalated = True
            reply_text = (
                "I'm sorry, I'm having trouble with this request - let me connect "
                "you with a colleague who can help."
            )
            session.trim_history(config.MAX_HISTORY_MESSAGES)
            return AgentResponse(
                reply_text=reply_text, escalated=escalated, handoff=handoff, tool_trace=tool_trace
            )

        if response.stop_reason == "refusal":
            # The model declined to answer at all (safety classifier) - this
            # can't be resolved by retrying, so hand off rather than show the
            # patient a blank reply.
            if handoff is None:
                stop_details = getattr(response, "stop_details", None)
                category = getattr(stop_details, "category", None) if stop_details else None
                handoff = escalation.create_handoff(
                    session,
                    reason_code=ReasonCode.OUT_OF_SCOPE.value,
                    summary=f"Claude declined to answer directly (refusal category: {category}).",
                )
                escalated = True
            reply_text = (
                "I'm sorry, I'm not able to help with that directly - let me connect "
                "you with a colleague who can."
            )
        else:
            reply_text = "".join(b.text for b in response.content if b.type == "text").strip()
            if not reply_text:
                # Defensive fallback: never show the patient a blank message,
                # even if this exact cause hasn't been seen before.
                block_types = [b.type for b in response.content]
                print(
                    f"[agent] warning: empty reply text (stop_reason={response.stop_reason!r}, "
                    f"content block types={block_types!r})",
                    file=sys.stderr,
                )
                reply_text = (
                    "Sorry, could you say that again? I didn't catch a clear answer to give you."
                )

        session.trim_history(config.MAX_HISTORY_MESSAGES)
        return AgentResponse(reply_text=reply_text, escalated=escalated, handoff=handoff, tool_trace=tool_trace)
