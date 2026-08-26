from src import escalation
from src.directory import ClinicDirectory
from src.escalation import HandoffEvent
from src.session import ConversationSession

TIME_OF_DAY_VALUES = ["morning", "afternoon", "any"]
DAYS_VALUES = ["weekday", "weekend", "any"]


def build_tool_definitions(directory: ClinicDirectory) -> list[dict]:
    location_enum = directory.list_locations()
    speciality_enum = directory.list_specialities()
    reason_code_enum = sorted(escalation.VALID_REASON_CODES)

    return [
        {
            "name": "list_locations",
            "description": "List every Maria Care city/clinic location.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "list_specialities",
            "description": "List every medical speciality available across Maria Care.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "find_doctors",
            "description": (
                "Directly look up doctors matching filters, e.g. 'which cardiologists "
                "are in Cluj-Napoca' or 'which doctors speak German'. Use this for "
                "direct lookup questions. Use recommend_doctors instead when the "
                "patient wants you to actively suggest/match them with a doctor. "
                "Each result already includes phone/email so you can give booking "
                "contact info without a separate get_doctor_details call."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "enum": location_enum},
                    "speciality": {"type": "string", "enum": speciality_enum},
                    "language": {"type": "string", "description": "A language name, e.g. 'German'."},
                    "name_query": {"type": "string", "description": "Partial or full doctor name."},
                    "min_years_experience": {"type": "integer"},
                    "min_rating": {"type": "number"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
        {
            "name": "get_doctor_details",
            "description": "Get full details (address, county, education - plus everything in the summary) for one specific doctor.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "doctor_ref": {
                        "type": "string",
                        "description": "The doctor's ref string, e.g. 'Ionut Dumitrescu, Clinica Cluj-Napoca Care', as returned by find_doctors/recommend_doctors.",
                    }
                },
                "required": ["doctor_ref"],
            },
        },
        {
            "name": "get_location_overview",
            "description": (
                "Get an honest summary for a Maria Care location: how many doctors, "
                "which specialities/languages are available, and the range of "
                "availability patterns - use this for generic 'where is clinic X' / "
                "'what's your availability' questions. Each doctor has their own "
                "address/phone/availability; this tool does not fabricate one single "
                "clinic-wide answer."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"location": {"type": "string", "enum": location_enum}},
                "required": ["location"],
            },
        },
        {
            "name": "update_patient_profile",
            "description": (
                "Record the patient's identified language and/or their non-identifying "
                "scheduling preferences (location, time of day, days) and stated reason "
                "for visiting (symptom/complaint, used only to help pick a speciality - "
                "never to diagnose). Call this as soon as you can identify the patient's "
                "language, and whenever they state a location, availability/time "
                "preference, or symptom/reason for visiting. Never use this to store a "
                "name, date of birth, or any identifying detail."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "description": "The patient's language, e.g. 'Romanian', 'Ukrainian'.",
                    },
                    "location_preference": {
                        "type": "string",
                        "description": "The patient's preferred city/clinic location.",
                    },
                    "time_of_day": {"type": "string", "enum": TIME_OF_DAY_VALUES},
                    "days": {"type": "string", "enum": DAYS_VALUES},
                    "reason_for_visit": {
                        "type": "string",
                        "description": (
                            "The patient's own words for their symptom/complaint, e.g. "
                            "'skin rash', 'chest pain' - used only to help you choose a "
                            "relevant speciality, never to diagnose."
                        ),
                    },
                },
                "required": [],
            },
        },
        {
            "name": "recommend_doctors",
            "description": (
                "Proactively match/recommend a doctor for the patient, ranked by "
                "their collected language + location + time preferences. Choose "
                "'speciality' yourself from list_specialities based on the patient's "
                "stated reason for visiting (their symptom/complaint) - this tool does "
                "not map symptoms to specialities for you. Language is a hard "
                "requirement when it is one of Maria Care's supported languages; "
                "location and time are ranking preferences, not strict filters, so "
                "this never returns a dead end when candidates exist."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "speciality": {"type": "string", "enum": speciality_enum},
                    "language": {
                        "type": "string",
                        "description": "Defaults to the patient's profile language if omitted.",
                    },
                    "location_preference": {
                        "type": "string",
                        "description": "Defaults to the patient's profile location preference if omitted.",
                    },
                    "time_of_day": {"type": "string", "enum": TIME_OF_DAY_VALUES},
                    "days": {"type": "string", "enum": DAYS_VALUES},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": [],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand the conversation off to a human. Always use this for any "
                "patient-specific/PHI question (ward, bed, admission, records, "
                "billing), for an explicit request to speak to a person, for "
                "out-of-scope topics (medical advice/diagnosis/emergencies), when "
                "nothing else has resolved the request, or when the patient's "
                "language isn't supported and they decline a best-effort alternative."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "reason_code": {"type": "string", "enum": reason_code_enum},
                    "summary": {
                        "type": "string",
                        "description": "One sentence for the human agent describing what the patient needs.",
                    },
                    "patient_language": {
                        "type": "string",
                        "description": "Defaults to the patient's profile language if omitted.",
                    },
                },
                "required": ["reason_code", "summary"],
            },
        },
    ]


def dispatch_tool(
    name: str,
    tool_input: dict,
    directory: ClinicDirectory,
    session: ConversationSession,
) -> tuple[dict, HandoffEvent | None]:
    if name == "list_locations":
        return {"locations": directory.list_locations()}, None

    if name == "list_specialities":
        return {"specialities": directory.list_specialities()}, None

    if name == "find_doctors":
        return directory.find_doctors(**tool_input), None

    if name == "get_doctor_details":
        return directory.get_doctor(tool_input["doctor_ref"]), None

    if name == "get_location_overview":
        return directory.get_location_overview(tool_input["location"]), None

    if name == "update_patient_profile":
        profile = session.patient_profile
        language = tool_input.get("language")
        if language:
            profile.language = language
            profile.language_supported = directory.is_language_supported(language)
        if tool_input.get("location_preference"):
            profile.location_preference = tool_input["location_preference"]
        if tool_input.get("time_of_day"):
            profile.time_of_day = tool_input["time_of_day"]
        if tool_input.get("days"):
            profile.days = tool_input["days"]
        if tool_input.get("reason_for_visit"):
            profile.reason_for_visit = tool_input["reason_for_visit"]
        return profile.as_dict(), None

    if name == "recommend_doctors":
        profile = session.patient_profile
        result = directory.recommend_doctors(
            speciality=tool_input.get("speciality"),
            language=tool_input.get("language") or profile.language,
            location_preference=tool_input.get("location_preference") or profile.location_preference,
            time_of_day=tool_input.get("time_of_day") or profile.time_of_day,
            days=tool_input.get("days") or profile.days,
            limit=tool_input.get("limit", 5),
        )
        return result, None

    if name == "escalate_to_human":
        event = escalation.create_handoff(
            session,
            reason_code=tool_input["reason_code"],
            summary=tool_input["summary"],
            patient_language=tool_input.get("patient_language"),
        )
        return {"status": "escalated", "ticket_id": event.ticket_id}, event

    return {"error": f"Unknown tool '{name}'."}, None
