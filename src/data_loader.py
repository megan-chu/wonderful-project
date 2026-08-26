import json
from pathlib import Path

REQUIRED_FIELDS = (
    "first_name",
    "last_name",
    "clinic_name",
    "location",
    "speciality",
    "address",
    "phone",
    "email",
    "postal_code",
    "county",
    "years_experience",
    "education",
    "languages",
    "availability",
    "rating",
)


def load_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    records = []
    for entry in raw:
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            raise ValueError(f"Doctor record missing fields {missing}: {entry}")

        record = dict(entry)
        record["first_name"] = record["first_name"].strip()
        record["last_name"] = record["last_name"].strip()
        record["clinic_name"] = record["clinic_name"].strip()
        record["location"] = record["location"].strip()
        record["speciality"] = record["speciality"].strip()
        record["address"] = record["address"].strip()
        record["county"] = record["county"].strip()
        record["languages"] = [lang.strip() for lang in record["languages"]]
        record["availability"] = record["availability"].strip()
        record["years_experience"] = int(record["years_experience"])
        record["rating"] = float(record["rating"])
        records.append(record)

    return records
