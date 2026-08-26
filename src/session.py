from dataclasses import dataclass, field


@dataclass
class PatientProfile:
    """Non-identifying patient state collected during a conversation.

    Deliberately holds only language, scheduling preferences, and the
    patient's own stated reason for visiting - no name, ID, or date of birth
    is ever stored here, since none of it is needed to recommend a doctor
    from the directory. `reason_for_visit` is the patient's self-reported
    symptom/complaint, kept only to help pick a relevant speciality - the
    agent never turns it into a diagnosis or medical advice.
    """

    language: str | None = None
    language_supported: bool | None = None
    location_preference: str | None = None
    time_of_day: str | None = None  # "morning" | "afternoon" | "any"
    days: str | None = None  # "weekday" | "weekend" | "any"
    reason_for_visit: str | None = None

    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "language_supported": self.language_supported,
            "location_preference": self.location_preference,
            "time_of_day": self.time_of_day,
            "days": self.days,
            "reason_for_visit": self.reason_for_visit,
        }


@dataclass
class ConversationSession:
    session_id: str
    channel: str  # "voice" | "whatsapp"
    history: list = field(default_factory=list)
    patient_profile: PatientProfile = field(default_factory=PatientProfile)
    handoffs: list = field(default_factory=list)

    def trim_history(self, max_messages: int) -> None:
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]


class SessionStore:
    """Plain in-memory session store, alive only for the process lifetime."""

    def __init__(self):
        self._sessions: dict[tuple[str, str], ConversationSession] = {}

    def get_or_create(self, channel: str, external_id: str) -> ConversationSession:
        key = (channel, external_id)
        if key not in self._sessions:
            self._sessions[key] = ConversationSession(
                session_id=f"{channel}:{external_id}", channel=channel
            )
        return self._sessions[key]
