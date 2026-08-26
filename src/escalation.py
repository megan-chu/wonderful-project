import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from src.session import ConversationSession

_ticket_counter = itertools.count(1)


class ReasonCode(str, Enum):
    PHI_OR_PATIENT_SPECIFIC = "phi_or_patient_specific"
    EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
    OUT_OF_SCOPE = "out_of_scope"
    UNRESOLVED_AFTER_ATTEMPT = "unresolved_after_attempt"
    LANGUAGE_NOT_SUPPORTED = "language_not_supported"
    SAFETY_CONCERN = "safety_concern"


VALID_REASON_CODES = {code.value for code in ReasonCode}


@dataclass
class HandoffEvent:
    ticket_id: str
    reason_code: str
    summary: str
    language: str | None
    channel: str
    session_id: str
    timestamp: str


def create_handoff(
    session: ConversationSession,
    reason_code: str,
    summary: str,
    patient_language: str | None = None,
) -> HandoffEvent:
    language = patient_language or session.patient_profile.language
    event = HandoffEvent(
        ticket_id=f"H-{next(_ticket_counter):03d}",
        reason_code=reason_code,
        summary=summary,
        language=language,
        channel=session.channel,
        session_id=session.session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    session.handoffs.append(event)
    return event
