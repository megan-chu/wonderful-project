from src import config
from src.data_loader import load_records
from src.directory import ClinicDirectory


def test_loads_all_records(directory):
    raw = load_records(config.DATA_PATH)
    assert len(raw) == len(directory._records) == 7029


def test_find_doctors_filters_by_speciality(directory):
    raw = load_records(config.DATA_PATH)
    expected = [r for r in raw if r["speciality"] == "Psychiatry"]

    result = directory.find_doctors(speciality="Psychiatry", limit=len(expected))

    assert result["total_matches"] == len(expected)
    assert all(d["speciality"] == "Psychiatry" for d in result["doctors"])


def test_find_doctors_filters_by_location_and_language(directory):
    raw = load_records(config.DATA_PATH)
    expected = [
        r for r in raw if r["location"] == "Cluj-Napoca" and "German" in r["languages"]
    ]

    result = directory.find_doctors(location="Cluj-Napoca", language="German", limit=1000)

    assert result["total_matches"] == len(expected)
    assert all("German" in d["languages"] for d in result["doctors"])
    assert all(d["location"] == "Cluj-Napoca" for d in result["doctors"])


def test_location_matching_is_diacritic_and_case_insensitive(directory):
    exact = directory.find_doctors(location="Cluj-Napoca", limit=1)
    variant = directory.find_doctors(location="cluj-napoca", limit=1)
    assert exact["total_matches"] == variant["total_matches"]
    assert exact["total_matches"] > 0


def test_unknown_location_returns_suggestions_not_a_crash(directory):
    result = directory.find_doctors(location="Cluj-Napocaaaa", limit=5)
    assert result["total_matches"] == 0
    assert "location" in result["suggestions"]
    assert len(result["suggestions"]["location"]) > 0


def test_get_location_overview_counts_match_manual_count(directory):
    raw = load_records(config.DATA_PATH)
    expected_count = len([r for r in raw if r["location"] == "Cluj-Napoca"])

    overview = directory.get_location_overview("Cluj-Napoca")

    assert overview["doctor_count"] == expected_count == 173


def test_get_location_overview_notes_per_doctor_variance(directory):
    overview = directory.get_location_overview("Cluj-Napoca")
    assert "note" in overview
    assert len(overview["availability_patterns"]) > 1


def test_get_doctor_exact_and_fuzzy(directory):
    result = directory.find_doctors(location="Cluj-Napoca", limit=1)
    ref = result["doctors"][0]["ref"]

    exact = directory.get_doctor(ref)
    assert "error" not in exact
    assert "address" in exact and "phone" in exact

    unknown = directory.get_doctor("Nonexistent Person, Nowhere Clinic")
    assert "error" in unknown


def test_find_doctors_summary_includes_booking_contact_and_experience(directory):
    raw = load_records(config.DATA_PATH)
    expected = next(r for r in raw if r["location"] == "Cluj-Napoca")

    result = directory.find_doctors(location="Cluj-Napoca", limit=len(raw))
    by_ref = {d["ref"]: d for d in result["doctors"]}
    summary = by_ref[f"{expected['first_name']} {expected['last_name']}, {expected['clinic_name']}"]

    # Summaries (not just get_doctor_details) must carry phone/email so the
    # agent can give booking contact info without a second tool call.
    assert summary["phone"] == expected["phone"]
    assert summary["email"] == expected["email"]
    assert summary["years_experience"] == expected["years_experience"]


def test_directory_summary_counts():
    directory = ClinicDirectory(load_records(config.DATA_PATH))
    assert len(directory.locations) == 42
    assert len(directory.specialities) == 20
    assert len(directory.languages) == 7
