"""
ESPN public API v2 — FIFA World Cup 2026 data pipeline.

Endpoint:
  https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD
"""

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

LEAGUE_CODE = "fifa.world"
LEAGUE_NAME = "FIFA World Cup"
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

STAGE_DATE_RANGES: dict[str, list[str]] = {
    "group-stage": ["20260625", "20260626", "20260627"],
    "round-of-32": [
        "20260628",
        "20260629",
        "20260630",
        "20260701",
        "20260702",
        "20260703",
    ],
    "round-of-16": ["20260704", "20260705", "20260706", "20260707"],
    "quarterfinals": ["20260709", "20260710", "20260711"],
    "semifinals": ["20260714", "20260715"],
    "third-place": ["20260718"],
    "final": ["20260719"],
}

STAGE_LABELS: dict[str, str] = {
    "group-stage": "Group Stage",
    "round-of-32": "Round of 32",
    "round-of-16": "Round of 16",
    "quarterfinals": "Quarterfinals",
    "quarter-finals": "Quarterfinals",
    "semifinals": "Semifinals",
    "semi-finals": "Semifinals",
    "final": "Final",
}

NAME_OVERRIDES: dict[str, str] = {
    "Czechia": "Czech Republic",
    "Curacao": "Curaçao",
}


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def _str(v: object) -> str | None:
    return v if isinstance(v, str) else None


def _num(v: object) -> float | None:
    return v if isinstance(v, (int, float)) else None


def _rec(v: object) -> dict | None:
    return v if isinstance(v, dict) else None


def _arr(v: object) -> list:
    return v if isinstance(v, list) else []


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------
def _normalize_status(raw: str) -> str:
    return raw.replace("STATUS_", "").replace("_", " ").lower()


def _is_paused(detail: str) -> bool:
    t = detail.upper()
    return any(tok in t for tok in ("HT", "FT", "AET", "PEN"))


def _is_tbd_team(team: dict) -> bool:
    """Teams not yet determined have abbreviations starting with a digit (e.g. '2A', '1C', '3RD')."""
    return bool(re.match(r"^\d", team.get("abbreviation", "")))


def _in_penalties(status: str, detail: str, hs, aws) -> bool:
    if hs is not None or aws is not None:
        return True
    t = f"{status} {detail}".upper()
    return bool(re.search(r"\bPEN(S|ALT(?:Y|IES)?)?\b", t)) or "PENAL" in t


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def _parse_clock(display: str, period: int) -> int:
    m = re.match(r"^(\d+)'(?:\+(\d+)')?$", display)
    if m:
        return (int(m.group(1) or 0) + int(m.group(2) or 0)) * 60
    return 0 if period <= 1 else 45 * 60


def _fmt_minute(period: int) -> str:
    return f"{period}H" if period > 0 else "Live"


# ---------------------------------------------------------------------------
# Team parser
# ---------------------------------------------------------------------------
def _parse_team(competitor: dict) -> dict:
    team = _rec(competitor.get("team")) or {}
    logos = _arr(team.get("logos"))
    logo = (
        _str(team.get("logo"))
        or next(
            (
                _str(l.get("href"))
                for l in logos
                if isinstance(l, dict) and "default" in _arr(l.get("rel"))
            ),
            None,
        )
        or (
            _str(logos[0].get("href")) if logos and isinstance(logos[0], dict) else None
        )
        or ""
    )
    raw = (
        _str(team.get("displayName"))
        or _str(team.get("shortDisplayName"))
        or _str(competitor.get("displayName"))
        or ""
    )
    score_raw = competitor.get("score")
    score = (
        int(score_raw)
        if isinstance(score_raw, (int, float))
        or (isinstance(score_raw, str) and score_raw.isdigit())
        else 0
    )
    shootout_raw = competitor.get("shootoutScore")
    shootout: int | None = None
    if shootout_raw is not None:
        try:
            shootout = int(shootout_raw)
        except (TypeError, ValueError):
            pass

    result = {
        "id": _str(competitor.get("id")) or _str(team.get("id")) or "",
        "name": NAME_OVERRIDES.get(raw, raw),
        "abbreviation": _str(team.get("abbreviation")) or "",
        "score": score,
        "logo": logo,
        "_homeAway": _str(competitor.get("homeAway")),
    }
    if shootout is not None:
        result["shootoutScore"] = shootout
    return result


# ---------------------------------------------------------------------------
# Match parser
# ---------------------------------------------------------------------------
def _parse_match(event: dict, clock_ts: int) -> dict | None:
    comp = next(iter(_arr(event.get("competitions"))), None)
    if not isinstance(comp, dict):
        return None

    competitors = [c for c in _arr(comp.get("competitors")) if isinstance(c, dict)]
    if len(competitors) < 2:
        return None

    status = _rec(comp.get("status")) or _rec(event.get("status")) or {}
    st = _rec(status.get("type")) or {}

    state = _str(st.get("state")) or ""
    status_name = _normalize_status(
        _str(st.get("name")) or _str(st.get("description")) or "unknown"
    )
    display_clock = _str(status.get("displayClock")) or ""
    detail = _str(st.get("shortDetail")) or _str(st.get("detail")) or ""
    period = int(_num(status.get("period")) or 0)
    clock_secs = _parse_clock(display_clock, period)

    teams = [_parse_team(c) for c in competitors]
    home = next((t for t in teams if t.get("_homeAway") == "home"), teams[0])
    away = next((t for t in teams if t is not home), None)

    if not home or not away:
        return None

    penalties = _in_penalties(
        status_name, detail, home.get("shootoutScore"), away.get("shootoutScore")
    )

    season_slug = _str((_rec(event.get("season")) or {}).get("slug")) or ""
    stage = STAGE_LABELS.get(season_slug, season_slug)

    notes = _arr(comp.get("notes"))
    bracket_note = (
        next(
            (
                _str(n.get("headline"))
                for n in notes
                if isinstance(n, dict) and n.get("headline")
            ),
            None,
        )
        or _str(event.get("shortName"))
        or ""
    )

    venue = _rec(comp.get("venue")) or {}
    addr = _rec(venue.get("address")) or {}

    def _strip(t: dict) -> dict:
        return {k: v for k, v in t.items() if k != "_homeAway"}

    return {
        "id": _str(event.get("id")) or f"{LEAGUE_CODE}-{home['id']}-{away['id']}",
        "leagueCode": LEAGUE_CODE,
        "leagueName": LEAGUE_NAME,
        "date": _str(event.get("date")) or "",
        "stage": stage,
        "status": status_name,
        "state": state,
        "minute": display_clock or _fmt_minute(period),
        "detail": detail,
        "clockSeconds": clock_secs,
        "clockUpdatedAt": clock_ts,
        "clockRunning": state == "in" and not _is_paused(detail) and not penalties,
        "inPenalties": penalties,
        "venue": {
            "name": _str(venue.get("fullName")) or "",
            "city": _str(addr.get("city")) or "",
            "country": _str(addr.get("country")) or "",
        },
        "bracketNote": bracket_note,
        "teamsConfirmed": not (_is_tbd_team(home) or _is_tbd_team(away)),
        "home": _strip(home),
        "away": _strip(away),
    }


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _fetch_date(date: str, stage_key: str, clock_ts: int) -> list[dict]:
    url = f"{ESPN_API_BASE}/{LEAGUE_CODE}/scoreboard?dates={date}&lang=en&region=us"
    data = _fetch_json(url)
    matches = []
    for event in _arr(data.get("events")):
        if not isinstance(event, dict):
            continue
        slug = (_rec(event.get("season")) or {}).get("slug", "")
        if slug != stage_key:
            continue
        m = _parse_match(event, clock_ts)
        if m:
            matches.append(m)
    return matches


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch_match_by_id(match_id: str) -> dict | None:
    """Search all stages for a match with the given ID."""
    for stage_key in STAGE_DATE_RANGES:
        try:
            for m in fetch_stage_matches(stage_key):
                if m["id"] == match_id:
                    return m
        except Exception:
            pass
    return None


def fetch_stage_matches(stage_key: str) -> list[dict]:
    """Fetch all matches for a given knockout stage from the ESPN API."""
    dates = STAGE_DATE_RANGES.get(stage_key, [])
    clock_ts = int(time.time() * 1000)
    seen: set[str] = set()
    all_matches: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(len(dates), 6)) as pool:
        futures = {pool.submit(_fetch_date, d, stage_key, clock_ts): d for d in dates}
        for fut in as_completed(futures):
            try:
                for m in fut.result():
                    if m["id"] not in seen:
                        seen.add(m["id"])
                        all_matches.append(m)
            except Exception:
                pass

    all_matches.sort(key=lambda m: m["date"])
    return all_matches


_ESPN_API_V2 = "https://site.api.espn.com/apis/v2/sports/soccer"


def fetch_group_map() -> dict[str, str]:
    """Return {team_id: group_name} from the ESPN standings endpoint."""
    url = f"{_ESPN_API_V2}/{LEAGUE_CODE}/standings?lang=en&region=us"
    try:
        data = _fetch_json(url)
    except Exception:
        return {}
    result: dict[str, str] = {}
    for group in _arr(data.get("children")):
        if not isinstance(group, dict):
            continue
        name = _str(group.get("name")) or _str(group.get("abbreviation")) or ""
        if not name:
            continue
        entries = _arr((_rec(group.get("standings")) or {}).get("entries"))
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            team = _rec(entry.get("team")) or {}
            tid = _str(team.get("id"))
            if tid:
                result[tid] = name
    return result
