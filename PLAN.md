# Maria Care Multilingual AI Agent — Implementation Plan

## Context

Maria Care is a healthcare group across Eastern Europe, grown by acquiring clinics/hospitals, each with its own legacy processes. Patients are high-volume and multilingual, and today can only reach per-site phone reception or a general call center — a disconnected experience where they repeat themselves. The goal is a single AI agent "brain" reachable by **phone (voice)** and **WhatsApp**, that understands a patient's question in their own language, answers accurately from Maria Care's data, and escalates to a human when it can't resolve the request — matching the acceptance criteria's happy path.

We only have one data source: `data/healthcare_data.json`, a directory of **7,029 doctor records** across 42 clinics/cities in Romania (speciality, location, address, phone, email, languages spoken, availability, rating). Critically, **address/phone/availability are per-doctor, not per-clinic** — verified directly (e.g. the Cluj-Napoca clinic has 173 doctors, 169 distinct addresses, 173 distinct phone numbers, 5 different availability patterns). There is no ward/bed/admission/patient data. Two decisions follow directly from this and from the client's answers to clarifying questions:

- **No fabrication**: "opening hours for clinic X" or "clinic X's address" can't be answered as one fact — the agent aggregates/summarizes across that clinic's doctors and asks a clarifying question (which doctor/speciality) when an exact single answer is needed, rather than inventing a canonical clinic address/availability.
- **Ward/patient-specific questions always escalate to a human** — this data doesn't exist and won't be mocked (client's explicit choice), so any PHI/patient-identity question (e.g. "what ward is my father in") is treated as an automatic escalation trigger, not a lookup failure.

Per the client's other confirmed choices: **channels are simulated** (CLI-based voice-call and WhatsApp-chat simulators, no live Twilio/WhatsApp Cloud API accounts needed), and the LLM is **Anthropic Claude** (native multilingual understanding + generation, tool-use for querying the data — no separate translation service).

**Update (round 2):** the client asked for three additional capabilities, now folded into this plan: (1) the agent must explicitly identify the patient's native language from what they say/type, not just implicitly reply in-kind; (2) the agent must collect non-PII preferences — preferred clinic location and preferred availability — before recommending anyone; (3) the agent must actively **recommend** a doctor matched on language + location + time preference from `healthcare_data.json`, not just answer direct lookup questions. Since the dataset has no coordinates (only `location`/city and `county`) and only 7 languages are represented, the client confirmed: location "closeness" = exact city first, same `county` as a fallback (verified: 6 of 34 counties actually contain more than one city, so this fallback has real, non-fabricated value); a patient whose language isn't one of the 7 gets an alternative-language offer plus an escalation option, not an automatic dead end; and language is a hard requirement for a recommendation while location/time are ranking preferences (best-effort, never a dead end).

**Update (round 3):** two further refinements. (1) When presenting a doctor (recommended or looked up), the agent must always surface their name, speciality, years of experience, and availability, plus their phone/email so the patient can book — the doctor/clinic directory query layer now returns phone/email as part of the standard summary (not just the full-detail lookup), since making the agent chain a second tool call just to get a phone number added latency for no benefit. Note: the data has no separate clinic-wide phone/email — each doctor is their own booking contact — so this stays consistent with the round-1 "no fabrication" decision rather than inventing a shared clinic number. (2) Terminology: "opening hours/time" is replaced with "availability" throughout the agent's own language (system prompt, tool descriptions, this document), matching the dataset's actual field name; patients can still ask about "opening hours" in their own words and the agent understands that regardless.

## Architecture

One shared **Agent Core** (system prompt + Claude tool-use loop + escalation bookkeeping + session history) is reused by two thin channel adapters. Both adapters call the same `Agent.run_turn(session, text) -> AgentResponse`; only presentation differs (voice = short, no-markdown, spoken-style; WhatsApp = short bullets/emoji ok). This keeps the design open to a future real Twilio/WhatsApp integration (new adapters converting audio/webhooks ↔ text) without touching the core.

```
voice_sim CLI ─┐
whatsapp_sim CLI ─┼─→ Agent Core (prompts + tool loop) ─→ Claude Messages API (tool use)
demo script ───┘              │
                               ▼
                     ClinicDirectory (in-memory index over healthcare_data.json)
```

## Data Layer

Plain Python, no pandas — 7,029 dicts is trivially small; a linear scan with predicate checks is fast enough and simpler than a DataFrame for this exact/substring/enum filtering workload.

- `data_loader.py`: loads and normalizes the JSON once (type coercion, whitespace cleanup).
- `directory.py` — `ClinicDirectory` class, built once as an immutable in-memory singleton:
  - Precomputed unique sets: `locations` (42), `specialities` (20), `languages` (7) — used both for LLM tool-schema enums and typo/diacritic-tolerant suggestions (`difflib.get_close_matches`).
  - `find_doctors(location=, speciality=, language=, name_query=, min_rating=, limit=10)` → filtered summaries + total count (paged, so the LLM doesn't get 170 results dumped into context). Each summary includes name, speciality, location, languages, availability, rating, years of experience, **and phone/email** — so the agent can give booking contact info straight from a lookup or recommendation without a second tool call.
  - `get_doctor(ref)` → full record (summary fields plus address, county, postal code, education) by a normalized `"FirstName LastName, ClinicName"` composite key (no natural ID exists in the data).
  - `get_location_overview(location)` → doctor count, specialities/languages present, distinct availability patterns, and an explicit note that address/phone/availability vary by doctor — the honest answer to a generic "where/when" question. Note: each doctor is their own booking contact — the data has no separate clinic-wide phone/email, so "the clinic's number" in practice means the specific doctor's own number.
  - `list_locations()`, `list_specialities()`, `suggest_location()/suggest_speciality()` for enumeration and recovery from near-miss input.
  - All string matching is case- and diacritic-insensitive (Unicode NFKD strip), since patients won't type Romanian diacritics reliably.
  - `county_of(location)` and a precomputed `county -> [locations]` map, built once from the existing `county` field — used only for the "same county" fallback in recommendations (§ Doctor Recommendation Logic), no invented geography.
  - `_parse_availability(availability_str)` — a small cached parser (only 5 distinct strings exist in the whole dataset, so this is computed once and memoized) turning `"Tue-Sat 08:30-16:30"` into a structured `(days: set[str], start: time, end: time)`, reused by both `get_location_overview` and `recommend_doctors`.

## Language Identification

The agent must explicitly determine and track the patient's language, not just reply in-kind implicitly. Mechanism: a new tool `update_patient_profile` (below) includes a `language` field; the system prompt instructs Claude to call it as soon as it can confidently identify the patient's language from their first message (works identically for the WhatsApp text channel and the simulated voice channel, since simulated voice is already plain transcript text — no separate classifier model is needed, Claude's own understanding does the classification). The handler resolves whether that language is one of the dataset's 7 (`language_supported: bool`) and stores both on `session.patient_profile`, so it's available for `recommend_doctors` without re-detecting each turn, and is reused as the `patient_language` field if the conversation later escalates. If the patient switches language mid-conversation, the same tool call updates it.

## Preference Collection (Non-Identifying)

When (and only when) the patient's intent is to be matched with/recommended a doctor — as opposed to a direct lookup like "list cardiologists in Iasi" — the system prompt directs the agent to conversationally elicit, before recommending: the patient's **reason for visiting** (their own words for a symptom/complaint — used only to pick a speciality from `list_specialities`, never to diagnose or give medical advice; an emergency-sounding symptom escalates instead of being routed), and their preferred clinic location (city) and preferred availability (time-of-day: morning/afternoon/any, and/or day-type: weekday/weekend/any). The prompt explicitly forbids asking for name, date of birth, patient ID, or any other identifying detail for this purpose — none of what's collected here identifies the patient. If the patient declines a preference ("doesn't matter"), the corresponding field stays `None`/`"any"` and recommendation proceeds unfiltered on that axis. Everything is stored on `session.patient_profile` via the same `update_patient_profile` tool, so one small tool covers the whole profile rather than one tool per field.

## Doctor Recommendation Logic

New tool `recommend_doctors` in `directory.py`/`tools.py`, used whenever the agent should proactively suggest a doctor (as opposed to `find_doctors`, kept for direct filtered-listing questions):
- **Params**: `speciality` (enum, optional), `language` (enum, optional — normally filled from `session.patient_profile.language`), `location_preference` (enum, optional), `time_of_day` (enum: `morning`/`afternoon`/`any`), `days` (enum: `weekday`/`weekend`/`any`), `limit` (default 5).
- **Language — hard filter, with the confirmed fallback**: if `language` is one of the 7 dataset languages, only doctors speaking it are candidates. If it isn't (`language_supported=False` from the profile), the tool skips the language filter entirely, ranks on the remaining criteria, and returns `language_supported=False` in its response so the agent's reply follows the confirmed policy — offer the best-effort match, name it as speaking e.g. English/Romanian instead, and offer to escalate for interpreter support if that's not acceptable.
- **Location — ranked, not filtered**: score 2 for exact city match, 1 for a different city in the same `county` (via `county_of`/the county map), 0 otherwise. Never excludes candidates outright, per the confirmed "ranked not strict" decision.
- **Time — ranked, not filtered**: using the parsed availability tuples, score 1 if the doctor's working days intersect the requested `days` category and their hour range overlaps the requested `time_of_day` bucket (morning ≈ before 12:00, afternoon ≈ after 12:00), 0 otherwise.
- **Ranking**: hard-filter on language (if supported) → sort by `(location_score, time_score, rating)` descending → take top `limit`, but always include `total_candidates_before_ranking` and per-candidate score breakdown so the agent can explain *why* (e.g. "closest match speaking German is in Turda, same county as your preferred Cluj-Napoca, available weekday mornings").
- If zero candidates remain even after the language hard-filter (patient's language genuinely isn't spoken by anyone matching the speciality), the tool returns an empty result with `suggestions` (nearby specialities/locations) so the agent can offer alternatives before considering escalation.

## LLM Tool Surface

8 tools total, defined as plain JSON-schema dicts in `tools.py` with a dispatch table into `directory.py`/`session.py`:

| Tool | Purpose | Returns |
|---|---|---|
| `list_locations` / `list_specialities` | enumerate valid values | arrays |
| `find_doctors` | direct lookup: "which doctors treat X / speak Y / are in Z" | filtered list + total_matches (+ suggestions if empty) |
| `get_doctor_details` | full info on a previously-found doctor | full record or error+suggestions |
| `get_location_overview` | "where is clinic Y" / "what's your availability" | aggregated summary, honest about per-doctor variance |
| `update_patient_profile` | record identified language, stated reason for visiting, and/or scheduling preferences | `language` (free string, optional), `reason_for_visit` (free string, optional — symptom/complaint, used only to help pick a speciality), `location_preference` (free string, optional), `time_of_day` (enum, optional), `days` (enum, optional) → updates `session.patient_profile`, returns the current profile + `language_supported` |
| `recommend_doctors` | proactively match a doctor to the patient's profile (see § above) | ranked candidates + score breakdown, `language_supported` flag, `total_candidates_before_ranking`, suggestions if empty |
| `escalate_to_human` | the only way a turn escalates | `reason_code` enum (`phi_or_patient_specific`, `explicit_human_request`, `out_of_scope`, `unresolved_after_attempt`, `language_not_supported`, `safety_concern`), `summary`, `patient_language` (defaults from `session.patient_profile` if already known) → creates a `HandoffEvent`, sets `session.escalated=True` |

`location`/`speciality`/`time_of_day`/`days` params are JSON-schema **enums** of canonical English values — this pushes language-mapping (e.g. French "psychiatre" → `"Psychiatry"`, "le matin" → `"morning"`) to Claude's semantic understanding rather than a hand-built per-language keyword table.

## Escalation Logic

Escalation is judged by the LLM against explicit system-prompt policy (not brittle multilingual keyword matching):
1. **PHI/patient-identity questions** (ward, bed, admission, "my father is a patient", records, diagnosis, booking, billing) → always escalate, `phi_or_patient_specific`. System prompt states plainly the agent has zero patient/admission data and must never guess it.
2. Explicit human request, in any language.
3. Out-of-scope (medical advice/triage/emergencies) → `out_of_scope`.
4. No results + no viable suggestions after a clarifying attempt → offer/trigger `unresolved_after_attempt`.
5. Patient's language isn't one of the dataset's 7 and they decline the best-effort alternative-language recommendation → `language_not_supported` (distinct from `unresolved_after_attempt` so the human team can route it to an interpreter, per the confirmed fallback policy).
6. Code-enforced safety net: the manual tool-loop caps at ~4 iterations/turn; if exceeded, the orchestrator force-escalates rather than looping or returning nothing.

No hardcoded multilingual emergency-keyword list — explicitly out of scope; this is a directory Q&A agent, not clinical triage, and a partial keyword list would be false-confidence engineering.

Escalation is per-request, not conversation-ending: the session stays open afterward. Each adapter renders it distinctly (voice: a `>>> [CALL TRANSFERRED — reason=..., ticket=...]` banner after Claude's own spoken hand-off line; WhatsApp: a separate `[System]` bubble), and `escalation.py` logs a `HandoffEvent(ticket_id, reason_code, summary, language, channel, session_id, timestamp)`.

## Session State

`session.py`: `ConversationSession` (id, channel, full Anthropic-format message history including prior tool_use/tool_result blocks so Claude retains memory of e.g. previously found doctors for "does one of them speak English?"), `handoffs` list, and a new `patient_profile: PatientProfile` — a small dataclass (`language`, `language_supported`, `location_preference`, `time_of_day`, `days`), all optional, populated only via `update_patient_profile`. This is deliberately the *only* patient state kept — non-PII by construction (no name/ID/DOB field exists to collect), in-memory, cleared with the rest of the session at process end. `SessionStore` is a plain in-memory dict, process-lifetime only — no database. History capped (~20 messages) as a cheap guard against runaway context in a long interactive demo session.

## File Structure

```
wonderful-project/
├── data/healthcare_data.json          (existing, unchanged)
├── README.md                          (updated with setup/run instructions)
├── requirements.txt                   (anthropic, pytest)
├── cli.py                             # `python cli.py {voice|whatsapp|demo}`
├── src/
│   ├── config.py                      # ANTHROPIC_API_KEY, model id, max_tokens, iteration cap
│   ├── data_loader.py                 # load + normalize JSON
│   ├── directory.py                   # ClinicDirectory: queries + availability parsing + recommend_doctors
│   ├── tools.py                       # tool schemas + dispatcher, incl. update_patient_profile/recommend_doctors
│   ├── escalation.py                  # HandoffEvent, ReasonCode (incl. language_not_supported), handler
│   ├── session.py                     # ConversationSession, PatientProfile, SessionStore
│   ├── prompts.py                     # system prompt: language ID, non-PII preference collection, per-channel style
│   ├── agent.py                       # Agent: prompt composition, manual tool-use loop, AgentResponse
│   └── channels/
│       ├── voice_sim.py               # phone-call CLI simulator
│       └── whatsapp_sim.py            # WhatsApp-chat CLI simulator
├── scripts/
│   └── demo_transcript.py             # scripted multilingual + escalation demo (needs API key)
└── tests/
    ├── conftest.py                    # loads real 7,029-record directory once
    ├── test_directory.py              # filters, diacritics, counts vs. manual JSON checks
    ├── test_tools.py                  # schema validity + dispatcher correctness
    ├── test_escalation.py             # HandoffEvent creation, incl. language_not_supported
    ├── test_recommendation.py         # recommend_doctors scoring: exact city vs. same-county fallback,
    │                                     time-of-day/day overlap, unsupported-language best-effort path
    └── test_agent.py                  # tool-loop + escalation, Anthropic client mocked (no API key needed)
```

Manual `while stop_reason == "tool_use"` loop in `agent.py` (not the beta Tool Runner) — keeps the one external dependency (`anthropic` SDK) on its stable surface and the loop easy to read/test with mocks. No auth, database, or message queue — not needed for a static-directory Q&A agent.

## Verification

- `pytest` runs the full suite with **no API key required**: `test_directory.py` checks real counts/filters/diacritics against the actual JSON; `test_recommendation.py` checks `recommend_doctors` scoring against hand-picked known cases (e.g. a speciality/language combo where the only match is in a different city of the same county — assert it's still returned, ranked below an exact-city match if one exists); `test_agent.py` mocks `client.messages.create` to script tool-use round trips for the happy path, the recommendation path (`update_patient_profile` → `recommend_doctors`), and the escalation path, asserting session state (`patient_profile`, `escalated`) updates correctly each time.
- With `ANTHROPIC_API_KEY` set, run `python cli.py demo` (`scripts/demo_transcript.py`) for a live, human-readable end-to-end proof of the acceptance criteria, extended to cover the new flow: (1) a Romanian WhatsApp question answered correctly; (2) a multi-turn recommendation conversation — patient states a speciality in one language, agent identifies the language, asks for city and preferred time, then recommends a matching doctor with rationale; (3) the same flow where the patient's stated language isn't in the dataset — agent offers a best-effort alternative-language doctor and an escalation option; (4) a ward question triggering immediate escalation regardless of any profile already collected.
- Interactive use: `python cli.py voice` or `python cli.py whatsapp` for manual testing in any language, including the recommendation conversation end-to-end.
