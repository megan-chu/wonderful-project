from src import config
from src.data_loader import load_records
from src.directory import ClinicDirectory, DAY_CATEGORIES, TIME_BUCKETS, parse_availability


def test_same_county_fallback_when_no_exact_city_match(directory):
    # Verified against the raw data: Dermatology + German has zero doctors in
    # Turda but 2 in Cluj-Napoca, which is in the same county (Cluj). The
    # national candidate pool (pre-ranking) still includes every location -
    # location is a ranking preference, not a filter - so only the *ranking*
    # of the top results is expected to favor the same-county doctors.
    raw = load_records(config.DATA_PATH)
    expected_national_count = len(
        [r for r in raw if r["speciality"] == "Dermatology" and "German" in r["languages"]]
    )

    result = directory.recommend_doctors(
        speciality="Dermatology",
        language="German",
        location_preference="Turda",
        limit=2,
    )

    assert result["language_supported"] is True
    assert result["total_candidates_before_ranking"] == expected_national_count == 102
    assert len(result["doctors"]) == 2
    assert all(d["location"] == "Cluj-Napoca" for d in result["doctors"])
    assert all(d["match"]["location"] == "same_county" for d in result["doctors"])


def test_exact_city_match_outranks_same_county(directory):
    # Verified against the raw data: Cardiology + English has exactly one
    # doctor in Turda and one in Cluj-Napoca (same county); the rest of the
    # national pool has no location advantage and should rank below both.
    raw = load_records(config.DATA_PATH)
    expected_national_count = len(
        [r for r in raw if r["speciality"] == "Cardiology" and "English" in r["languages"]]
    )

    result = directory.recommend_doctors(
        speciality="Cardiology",
        language="English",
        location_preference="Turda",
        limit=5,
    )

    assert result["total_candidates_before_ranking"] == expected_national_count == 103
    doctors = result["doctors"]
    assert doctors[0]["location"] == "Turda"
    assert doctors[0]["match"]["location"] == "exact"
    assert doctors[1]["location"] == "Cluj-Napoca"
    assert doctors[1]["match"]["location"] == "same_county"
    assert all(d["match"]["location"] == "other" for d in doctors[2:])


def test_unsupported_language_falls_back_instead_of_dead_end(directory):
    result = directory.recommend_doctors(speciality="Pediatrics", language="Ukrainian", limit=5)

    assert result["language_supported"] is False
    assert result["total_candidates_before_ranking"] > 0
    assert len(result["doctors"]) > 0


def _minimal_doctor(**overrides) -> dict:
    base = {
        "first_name": "A",
        "last_name": "B",
        "clinic_name": "Test Clinic",
        "location": "Testville",
        "speciality": "Oncology",
        "address": "1 Test St",
        "phone": "+40-000-000-000",
        "email": "a.b@test.ro",
        "postal_code": "000000",
        "county": "Test County",
        "years_experience": 5,
        "education": "Test University",
        "languages": ["Romanian"],
        "availability": "Mon-Fri 09:00-17:00",
        "rating": 4.0,
    }
    base.update(overrides)
    return base


def test_no_candidates_for_a_supported_language_returns_suggestions_not_a_crash():
    # In the real 7029-record dataset every (speciality, supported language)
    # combination happens to have at least one doctor, so this branch is
    # exercised here against a small synthetic directory instead: "English"
    # is a supported language overall (spoken by the Cardiology doctor) but
    # no Oncology doctor speaks it.
    directory = ClinicDirectory(
        [
            _minimal_doctor(speciality="Oncology", languages=["Romanian"]),
            _minimal_doctor(speciality="Cardiology", languages=["English"]),
        ]
    )

    result = directory.recommend_doctors(speciality="Oncology", language="English", limit=5)

    assert result["language_supported"] is True
    assert result["total_candidates_before_ranking"] == 0
    assert result["doctors"] == []
    assert result["suggestions"]["languages_available_for_this_speciality"] == ["Romanian"]


def test_unsupported_language_skips_filter_rather_than_returning_zero(directory):
    # A language absent from the whole dataset (not just this speciality)
    # is the "unsupported" path, distinct from the zero-candidate path above:
    # the filter is skipped rather than producing a dead end.
    result = directory.recommend_doctors(speciality="Oncology", language="Klingon", limit=5)

    assert result["language_supported"] is False
    assert result["total_candidates_before_ranking"] > 0
    assert len(result["doctors"]) > 0


def test_time_of_day_and_days_scoring_matches_parsed_availability(directory):
    result = directory.recommend_doctors(
        speciality="Family Medicine", time_of_day="morning", days="weekend", limit=200
    )

    matched = [d for d in result["doctors"] if d["match"]["time"] is True]
    assert matched, "expected at least one doctor available weekend mornings"
    for d in matched:
        days, start, end = parse_availability(d["availability"])
        assert days & DAY_CATEGORIES["weekend"]
        bucket_start, bucket_end = TIME_BUCKETS["morning"]
        assert start < bucket_end and end > bucket_start
