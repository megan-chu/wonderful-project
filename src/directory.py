import difflib
import unicodedata
from collections import defaultdict
from datetime import time
from functools import lru_cache
from pathlib import Path

from src.data_loader import load_records

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_CATEGORIES = {
    "weekday": frozenset({"Mon", "Tue", "Wed", "Thu", "Fri"}),
    "weekend": frozenset({"Sat", "Sun"}),
}
TIME_BUCKETS = {
    "morning": (time(0, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(23, 59)),
}


def _normalize(value: str) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.strip().lower()


def _parse_days(day_range: str) -> frozenset[str]:
    start, end = day_range.split("-")
    start_idx, end_idx = WEEKDAYS.index(start), WEEKDAYS.index(end)
    if start_idx <= end_idx:
        return frozenset(WEEKDAYS[start_idx : end_idx + 1])
    return frozenset(WEEKDAYS[start_idx:] + WEEKDAYS[: end_idx + 1])


@lru_cache(maxsize=None)
def parse_availability(availability: str) -> tuple[frozenset[str], time, time]:
    day_part, hour_part = availability.split(" ")
    start_str, end_str = hour_part.split("-")
    start_h, start_m = (int(x) for x in start_str.split(":"))
    end_h, end_m = (int(x) for x in end_str.split(":"))
    return _parse_days(day_part), time(start_h, start_m), time(end_h, end_m)


def _ranges_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and a_end > b_start


def _doctor_summary(record: dict, ref: str) -> dict:
    return {
        "ref": ref,
        "first_name": record["first_name"],
        "last_name": record["last_name"],
        "speciality": record["speciality"],
        "clinic_name": record["clinic_name"],
        "location": record["location"],
        "languages": record["languages"],
        "availability": record["availability"],
        "rating": record["rating"],
        "years_experience": record["years_experience"],
        # Each doctor is their own booking contact - there is no separate
        # clinic-wide phone/email in this data (see get_location_overview's
        # note), so this is the number/address to book *with this doctor*.
        "phone": record["phone"],
        "email": record["email"],
    }


def _doctor_detail(record: dict, ref: str) -> dict:
    detail = _doctor_summary(record, ref)
    detail.update(
        {
            "address": record["address"],
            "county": record["county"],
            "postal_code": record["postal_code"],
            "education": record["education"],
        }
    )
    return detail


class ClinicDirectory:
    """Immutable, in-memory query layer over the Maria Care doctor directory."""

    def __init__(self, records: list[dict]):
        self._records = records

        self.locations = sorted({r["location"] for r in records})
        self.specialities = sorted({r["speciality"] for r in records})
        self.languages = sorted({lang for r in records for lang in r["languages"]})

        self._location_lookup = {_normalize(loc): loc for loc in self.locations}
        self._speciality_lookup = {_normalize(s): s for s in self.specialities}
        self._language_lookup = {_normalize(lang): lang for lang in self.languages}

        self._county_by_location: dict[str, str] = {}
        self._locations_by_county: dict[str, set[str]] = defaultdict(set)
        for r in records:
            self._county_by_location[r["location"]] = r["county"]
            self._locations_by_county[r["county"]].add(r["location"])

        self._doctor_ref_index: dict[str, dict] = {}
        self._doctor_refs: list[str] = []
        used_refs: dict[str, int] = defaultdict(int)
        for r in records:
            base_ref = f"{r['first_name']} {r['last_name']}, {r['clinic_name']}"
            ref = base_ref
            if used_refs[base_ref]:
                ref = f"{base_ref} ({r['county']}, #{used_refs[base_ref] + 1})"
            used_refs[base_ref] += 1
            self._doctor_ref_index[_normalize(ref)] = (r, ref)
            self._doctor_refs.append(ref)

    # -- canonicalization helpers -------------------------------------------------

    def _canonical_location(self, location: str | None) -> str | None:
        if not location:
            return None
        return self._location_lookup.get(_normalize(location))

    def _canonical_speciality(self, speciality: str | None) -> str | None:
        if not speciality:
            return None
        return self._speciality_lookup.get(_normalize(speciality))

    def _canonical_language(self, language: str | None) -> str | None:
        if not language:
            return None
        return self._language_lookup.get(_normalize(language))

    def suggest_location(self, text: str, n: int = 3) -> list[str]:
        return difflib.get_close_matches(text, self.locations, n=n, cutoff=0.5)

    def suggest_speciality(self, text: str, n: int = 3) -> list[str]:
        return difflib.get_close_matches(text, self.specialities, n=n, cutoff=0.5)

    def county_of(self, location: str) -> str | None:
        canonical = self._canonical_location(location)
        return self._county_by_location.get(canonical) if canonical else None

    def is_language_supported(self, language: str) -> bool:
        return self._canonical_language(language) is not None

    def list_locations(self) -> list[str]:
        return list(self.locations)

    def list_specialities(self) -> list[str]:
        return list(self.specialities)

    # -- lookups --------------------------------------------------------------

    def find_doctors(
        self,
        location: str | None = None,
        speciality: str | None = None,
        language: str | None = None,
        name_query: str | None = None,
        min_years_experience: int | None = None,
        min_rating: float | None = None,
        limit: int = 10,
    ) -> dict:
        suggestions: dict[str, list[str]] = {}

        canonical_location = None
        if location:
            canonical_location = self._canonical_location(location)
            if not canonical_location:
                suggestions["location"] = self.suggest_location(location)

        canonical_speciality = None
        if speciality:
            canonical_speciality = self._canonical_speciality(speciality)
            if not canonical_speciality:
                suggestions["speciality"] = self.suggest_speciality(speciality)

        canonical_language = None
        if language:
            canonical_language = self._canonical_language(language)

        if suggestions:
            return {"doctors": [], "total_matches": 0, "suggestions": suggestions}

        normalized_name_query = _normalize(name_query) if name_query else None

        matches = []
        for r in self._records:
            if canonical_location and r["location"] != canonical_location:
                continue
            if canonical_speciality and r["speciality"] != canonical_speciality:
                continue
            if canonical_language and canonical_language not in r["languages"]:
                continue
            if min_years_experience and r["years_experience"] < min_years_experience:
                continue
            if min_rating and r["rating"] < min_rating:
                continue
            if normalized_name_query:
                full_name = _normalize(f"{r['first_name']} {r['last_name']}")
                if normalized_name_query not in full_name:
                    continue
            matches.append(r)

        matches.sort(key=lambda r: -r["rating"])
        total_matches = len(matches)
        page = matches[:limit]
        doctors = [
            _doctor_summary(r, f"{r['first_name']} {r['last_name']}, {r['clinic_name']}")
            for r in page
        ]
        result = {"doctors": doctors, "total_matches": total_matches}
        if total_matches == 0:
            result["suggestions"] = {}
        return result

    def get_doctor(self, ref: str) -> dict:
        normalized = _normalize(ref)
        hit = self._doctor_ref_index.get(normalized)
        if hit:
            record, canonical_ref = hit
            return _doctor_detail(record, canonical_ref)

        close = difflib.get_close_matches(ref, self._doctor_refs, n=3, cutoff=0.4)
        return {"error": f"No doctor found matching '{ref}'.", "suggestions": close}

    def get_location_overview(self, location: str) -> dict:
        canonical = self._canonical_location(location)
        if not canonical:
            return {
                "error": f"'{location}' is not a recognized Maria Care location.",
                "suggestions": self.suggest_location(location),
            }

        doctors_here = [r for r in self._records if r["location"] == canonical]
        specialities = sorted({r["speciality"] for r in doctors_here})
        languages = sorted({lang for r in doctors_here for lang in r["languages"]})
        availability_patterns = sorted({r["availability"] for r in doctors_here})

        return {
            "location": canonical,
            "county": self._county_by_location[canonical],
            "doctor_count": len(doctors_here),
            "specialities": specialities,
            "languages": languages,
            "availability_patterns": availability_patterns,
            "note": (
                "Each doctor at this location has their own office address, phone "
                "number, and availability - there is no single clinic-wide address "
                "or availability. Ask which doctor or speciality the patient needs "
                "for an exact address and schedule."
            ),
        }

    # -- recommendation ---------------------------------------------------------

    def recommend_doctors(
        self,
        speciality: str | None = None,
        language: str | None = None,
        location_preference: str | None = None,
        time_of_day: str | None = None,
        days: str | None = None,
        limit: int = 5,
    ) -> dict:
        canonical_speciality = self._canonical_speciality(speciality) if speciality else None
        if speciality and not canonical_speciality:
            return {
                "doctors": [],
                "total_candidates_before_ranking": 0,
                "language_supported": True,
                "suggestions": {"speciality": self.suggest_speciality(speciality)},
            }

        canonical_location = (
            self._canonical_location(location_preference) if location_preference else None
        )

        language_supported = True
        canonical_language = None
        if language:
            canonical_language = self._canonical_language(language)
            language_supported = canonical_language is not None

        candidates = [
            r
            for r in self._records
            if not canonical_speciality or r["speciality"] == canonical_speciality
        ]

        if canonical_language:
            candidates = [r for r in candidates if canonical_language in r["languages"]]

        total_candidates_before_ranking = len(candidates)

        if total_candidates_before_ranking == 0:
            fallback_pool = [
                r
                for r in self._records
                if not canonical_speciality or r["speciality"] == canonical_speciality
            ]
            available_languages = sorted({lang for r in fallback_pool for lang in r["languages"]})
            return {
                "doctors": [],
                "total_candidates_before_ranking": 0,
                "language_supported": language_supported,
                "suggestions": {"languages_available_for_this_speciality": available_languages},
            }

        preferred_county = self.county_of(canonical_location) if canonical_location else None
        target_days = DAY_CATEGORIES.get(days) if days in ("weekday", "weekend") else None
        target_bucket = TIME_BUCKETS.get(time_of_day) if time_of_day in ("morning", "afternoon") else None

        scored = []
        for r in candidates:
            if canonical_location and r["location"] == canonical_location:
                location_match = "exact"
                location_score = 2
            elif preferred_county and r["county"] == preferred_county:
                location_match = "same_county"
                location_score = 1
            else:
                location_match = "unspecified" if not canonical_location else "other"
                location_score = 0

            time_match = None
            time_score = 0
            if target_days is not None or target_bucket is not None:
                doc_days, doc_start, doc_end = parse_availability(r["availability"])
                day_ok = target_days is None or bool(doc_days & target_days)
                time_ok = target_bucket is None or _ranges_overlap(
                    doc_start, doc_end, target_bucket[0], target_bucket[1]
                )
                time_match = day_ok and time_ok
                time_score = 1 if time_match else 0

            scored.append((location_score, time_score, r["rating"], r, location_match, time_match))

        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

        doctors = []
        for location_score, time_score, rating, r, location_match, time_match in scored[:limit]:
            summary = _doctor_summary(r, f"{r['first_name']} {r['last_name']}, {r['clinic_name']}")
            summary["match"] = {"location": location_match, "time": time_match}
            doctors.append(summary)

        return {
            "doctors": doctors,
            "total_candidates_before_ranking": total_candidates_before_ranking,
            "language_supported": language_supported,
        }


def build_directory(path: Path | None = None) -> ClinicDirectory:
    from src import config

    records = load_records(path or config.DATA_PATH)
    return ClinicDirectory(records)
