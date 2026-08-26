# Maria Care Multilingual AI Agent

A multilingual patient assistant for Maria Care, reachable over simulated **voice** and **WhatsApp**
channels, backed by Claude tool-use over the real doctor/clinic directory in `data/healthcare_data.json`
(7,029 doctors across 42 Romanian clinics).

The agent identifies the patient's language, answers direct lookup questions (locations, availability,
specialities), collects non-identifying preferences (symptom/reason for visit, preferred location, preferred
time) to proactively **recommend** a matching doctor with full booking details, and **escalates to a human**
for anything it shouldn't handle itself - most importantly, any question about a specific patient (ward,
admission, records), since no such data exists in this system.

See [PLAN.md](PLAN.md) for the full design rationale: data constraints, the recommendation/ranking logic,
and the escalation policy.

## Setup

```powershell
pip install -r requirements.txt
```

Set an Anthropic API key (or use `ant auth login` if you have the Anthropic CLI):

```powershell
$env:ANTHROPIC_API_KEY = "your-api-key"
```

## Run

```powershell
python cli.py voice      # simulated phone call - type what the caller says
python cli.py whatsapp   # simulated WhatsApp chat
python cli.py demo       # scripted multilingual + escalation demo transcript
```

Type to the agent in **any language** - it detects the language and replies in kind. Try a symptom-led
conversation to see the full flow, e.g. on WhatsApp:

```
Patient: hey, i've had knee pain for like 2 weeks now, not going away, can you recommend a specialist?
Agent:   sorry to hear that! an orthopedist should be able to help. where are you based, and
         morning or afternoon work better for you?
Patient: Targu Mures, weekday mornings only
Agent:   I'd recommend Dr. Ana Barbu, orthopedist at Clinica Targu Mures Care (Strada Unirii 103,
         Targu Mures). She speaks Romanian, English, and French, 9 yrs experience, available
         Mon-Fri 9am-5pm.
         Phone: +40-254-615-829 - Email: ana.barbu@clinica-targu-mures-care.ro
```

Both channels are text-in/text-out simulations - typed input stands in for an already-transcribed speech
utterance (voice) or an inbound chat message (WhatsApp). No Twilio/WhatsApp Cloud API account is needed; the
agent core is adapter-based so a real integration could be added later without changing it.

To use a different model for one run, pass `--model` instead of setting an env var:

```powershell
python cli.py whatsapp --model claude-haiku-4-5
```

## Tests

```powershell
pytest
```

The full suite runs without an API key - it exercises the directory/recommendation logic directly against
the real data and mocks the Anthropic client for the agent orchestration tests. Only `python cli.py demo`
(and interactive use) needs a real key.

## Project layout

```
cli.py                    entrypoint - python cli.py {voice|whatsapp|demo} [--model ID]
src/
  config.py                env-var-driven settings (model, tokens, effort, iteration/history caps)
  data_loader.py            loads + normalizes healthcare_data.json
  directory.py               ClinicDirectory: lookups, availability parsing, recommend_doctors ranking
  tools.py                   Claude tool schemas + dispatcher
  prompts.py                  system prompt: language ID, tone/empathy, recommendation flow, escalation policy
  session.py                   ConversationSession, PatientProfile, SessionStore
  escalation.py                 HandoffEvent, ReasonCode, human-handoff logging
  agent.py                       manual tool-use loop, model-compatibility fallback, AgentResponse
  channels/
    voice_sim.py                  simulated phone-call CLI
    whatsapp_sim.py                simulated WhatsApp CLI
scripts/demo_transcript.py    scripted multilingual + escalation demo
tests/                         pytest suite (no API key required)
data/healthcare_data.json      the doctor/clinic directory (not modified by this project)
```

## Configuration

Environment variables (all optional, see `src/config.py`) - `--model` on the CLI overrides
`MARIA_CARE_MODEL`/the default for a single run:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | Anthropic credentials |
| `MARIA_CARE_MODEL` | `claude-sonnet-5` | Model used for the agent |
| `MARIA_CARE_MAX_TOKENS` | `2048` | Max output tokens per turn |
| `MARIA_CARE_EFFORT` | `low` | Reasoning effort (a directory-lookup task, not deep reasoning) - ignored automatically on models that don't support it (e.g. Haiku 4.5) |
| `MARIA_CARE_MAX_TOOL_ITERATIONS` | `4` | Tool-call budget per turn before forced escalation |
| `MARIA_CARE_MAX_HISTORY_MESSAGES` | `20` | Conversation history cap per session |

**Choosing a model:** `claude-sonnet-5` (the default) balances cost and instruction-following quality for
this showcase. `claude-haiku-4-5` is cheaper and lower-latency but more prone to skipping instructions in a
prompt this detailed (e.g. dropping empathy, giving incomplete info for an alternative doctor) - useful for
budget-constrained testing, less ideal for a polished demo. `claude-opus-5` is the most capable but priciest.
