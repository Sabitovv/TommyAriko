import re


PHONE_RE = re.compile(r"^\+7\d{10}$")


def validate_full_name(value: str) -> bool:
    parts = [p for p in value.strip().split() if p]
    return len(parts) >= 2 and all(part.replace("-", "").isalpha() for part in parts)


def validate_phone(value: str) -> bool:
    return bool(PHONE_RE.match(value))


def validate_article(value: str) -> bool:
    return value.isdigit()
