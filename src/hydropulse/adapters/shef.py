from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PARSER_VERSION = "1.0.0"
MISSING = {"M", "MSG", "-9999", "-9999.0"}
ZONE_CODES = {
    "Z": ZoneInfo("UTC"),
    "E": ZoneInfo("America/New_York"),
    "C": ZoneInfo("America/Chicago"),
    "M": ZoneInfo("America/Denver"),
    "P": ZoneInfo("America/Los_Angeles"),
}


@dataclass(frozen=True)
class ShefValue:
    station: str
    parameter: str
    valid_at: datetime
    value: float | None
    created_at: datetime | None
    is_crest: bool = False


@dataclass(frozen=True)
class ParseError:
    line: str
    reason: str


def _date(token: str, zone: ZoneInfo, anchor: datetime | None = None) -> datetime:
    if len(token) == 8:
        return datetime.strptime(token, "%Y%m%d").replace(tzinfo=zone)
    if len(token) == 6 and anchor:
        candidate = datetime.strptime(str(anchor.year)[:2] + token, "%Y%m%d").replace(tzinfo=zone)
        if candidate - anchor > timedelta(days=180):
            candidate = candidate.replace(year=candidate.year - 100)
        return candidate
    raise ValueError(f"unsupported date {token}")


def parse(text: str) -> tuple[list[ShefValue], list[ParseError]]:
    """Strict, small SHEF parser for RFC .E/.ER and .A/.AR forecast-stage records."""
    values: list[ShefValue] = []
    errors: list[ParseError] = []
    continuation: tuple[str, datetime, ZoneInfo, str, datetime | None, int] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith((".E ", ".ER ")):
            parts = line.split()
            try:
                station, date_token, zone_code = parts[1:4]
                zone = ZONE_CODES[zone_code]
                base = _date(date_token, zone)
                body = " ".join(parts[4:])
                dh = re.search(r"/DH(\d{2})(\d{2})?", body)
                di = re.search(r"/DIH0?(\d+)", body)
                dc = re.search(r"/DC(\d{8})(\d{4})", body)
                param = next((p for p in re.split(r"[/\s]+", body) if p.startswith("HGIFF")), None)
                if not (dh and di and param):
                    raise ValueError("missing DH, DIH, or forecast-stage parameter")
                cursor = base.replace(hour=int(dh.group(1)), minute=int(dh.group(2) or 0))
                created = (
                    datetime.strptime("".join(dc.groups()), "%Y%m%d%H%M").replace(tzinfo=zone)
                    if dc
                    else None
                )
                data = body.split("/" + param, 1)[1]
                tokens = [
                    t.strip()
                    for t in data.split("/")
                    if t.strip() and not t.strip().startswith(("DC", "DH", "DI"))
                ]
                for token in tokens:
                    value = None if token.split()[0] in MISSING else float(token.split()[0])
                    values.append(ShefValue(station, param, cursor, value, created))
                    cursor += timedelta(hours=int(di.group(1)))
                continuation = (station, cursor, zone, param, created, int(di.group(1)))
            except (ValueError, IndexError, KeyError) as exc:
                errors.append(ParseError(raw_line, str(exc)))
        elif line.startswith(".E") and continuation:
            station, cursor, _, param, created, increment = continuation
            try:
                for token in [t.strip() for t in line.split("/", 1)[-1].split("/") if t.strip()]:
                    value = None if token in MISSING else float(token.split()[0])
                    values.append(ShefValue(station, param, cursor, value, created))
                    cursor += timedelta(hours=increment)
                continuation = (station, cursor, continuation[2], param, created, increment)
            except ValueError as exc:
                errors.append(ParseError(raw_line, str(exc)))
        elif line.startswith((".A ", ".AR ")):
            parts = line.split()
            try:
                station, date_token, zone_code = parts[1:4]
                zone = ZONE_CODES[zone_code]
                body = " ".join(parts[4:])
                param_match = re.search(r"/(HGIFF(?:ZZ|X)?)\s+([^/\s]+)", body)
                if not param_match:
                    raise ValueError("no supported forecast-stage value")
                dh = re.search(r"/DH(\d{2})(\d{2})?", body)
                base = _date(date_token, zone)
                valid = base.replace(
                    hour=int(dh.group(1)) if dh else 0, minute=int(dh.group(2) or 0) if dh else 0
                )
                token = param_match.group(2)
                value = None if token in MISSING else float(token)
                values.append(ShefValue(station, param_match.group(1), valid, value, None, True))
            except (ValueError, IndexError, KeyError) as exc:
                errors.append(ParseError(raw_line, str(exc)))
        elif line.startswith("."):
            errors.append(ParseError(raw_line, "unsupported SHEF construct"))
    return values, errors
