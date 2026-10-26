"""Fixed America/New_York release stamp. Never derive a version at process startup."""

import datetime
import re

DISPLAY_VERSION = "26.1026.090155"
RELEASE_TIMEZONE = "America/New_York"


def canonical_timestamp(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}\.[0-9]{4}\.[0-9]{6}", value):
        raise ValueError("Release timestamp must be YY.MMDD.HHmmss with padded fields")
    year, monthday, clock = value.split(".")
    try:
        datetime.datetime(
            2000 + int(year),
            int(monthday[:2]),
            int(monthday[2:]),
            int(clock[:2]),
            int(clock[2:4]),
            int(clock[4:]),
        )
    except ValueError as error:
        raise ValueError("Release timestamp has an invalid local calendar/time field") from error
    return ".".join(str(int(part)) for part in (year, monthday, clock))


def canonical_identity(value: str) -> str:
    """Normalize numeric release components, including legacy app identities, for comparison."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("Expected a three-part numeric app/package identity")
    return ".".join(str(int(part)) for part in value.split("."))


def equivalent_versions(left: str, right: str) -> bool:
    return canonical_identity(left) == canonical_identity(right)


PACKAGE_VERSION = canonical_timestamp(DISPLAY_VERSION)
