"""
ESPN API pública v2 — pipeline de datos FIFA World Cup 2026.

Endpoint principal:
  https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={id}&lang=es
"""

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

LEAGUE_CODE = "fifa.world"
LEAGUE_NAME = "FIFA World Cup"
ESPN_EVENT_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event_id}&lang=es&region=es"

KNOWN_MATCH_IDS: list[str] = [
    # Fase de grupos
    "760468", "760469", "760470", "760471",
    "760472", "760473", "760474", "760475",
    "760476", "760477", "760478", "760479",
    "760480", "760481", "760482", "760483",
    "760484", "760485",
    # Dieciseisavos de final
    "760486", "760487", "760488", "760489",
    "760490", "760491", "760492", "760493",
    "760494", "760495", "760496", "760497",
    "760498", "760499", "760500", "760501",
    # Octavos de final
    "760502", "760503", "760504", "760505",
    "760506", "760507", "760508", "760509",
    # Cuartos de final
    "760510", "760511", "760512", "760513",
    # Semifinales
    "760514", "760515",
    # Final
    "760517",
]

SEASON_TYPE_LABELS: dict[int, str] = {
    13802: "Fase de Grupos",
    13801: "Dieciseisavos de Final",
    13800: "Octavos de Final",
    13799: "Cuartos de Final",
    13798: "Semifinales",
    13803: "Final",
}

NAME_OVERRIDES: dict[str, str] = {
    "Chequia": "República Checa",
    "Curacao": "Curaçao",
    "República Democrática del Congo": "Congo",
}


# ---------------------------------------------------------------------------
# Helpers primitivos
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
# Helpers de estado
# ---------------------------------------------------------------------------
def _normalize_status(raw: str) -> str:
    return raw.replace("STATUS_", "").replace("_", " ").lower()


def _is_paused(detail: str) -> bool:
    t = detail.upper()
    return any(tok in t for tok in ("HT", "FT", "AET", "PEN"))


def _is_tbd_team(team: dict) -> bool:
    return bool(re.match(r"^\d", team.get("abbreviation", "")))


def _in_penalties(status: str, detail: str, hs, aws) -> bool:
    if hs is not None or aws is not None:
        return True
    t = f"{status} {detail}".upper()
    return bool(re.search(r"\bPEN(S|ALT(?:Y|IES)?)?\b", t)) or "PENAL" in t


# ---------------------------------------------------------------------------
# Helpers de reloj
# ---------------------------------------------------------------------------
def _parse_clock(display: str, period: int) -> int:
    m = re.match(r"^(\d+)'(?:\+(\d+)')?$", display)
    if m:
        return (int(m.group(1) or 0) + int(m.group(2) or 0)) * 60
    return 0 if period <= 1 else 45 * 60


def _fmt_minute(period: int) -> str:
    return f"{period}T" if period > 0 else "En vivo"


# ---------------------------------------------------------------------------
# Parser de equipo
# ---------------------------------------------------------------------------
def _parse_team(competitor: dict) -> dict:
    team = _rec(competitor.get("team")) or {}
    logos = _arr(team.get("logos"))
    logo = (
        _str(team.get("logo"))
        or next(
            (
                _str(logo_entry.get("href"))
                for logo_entry in logos
                if isinstance(logo_entry, dict) and "default" in _arr(logo_entry.get("rel"))
            ),
            None,
        )
        or (_str(logos[0].get("href")) if logos and isinstance(logos[0], dict) else None)
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
# Parser de partido
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
        _str(st.get("name")) or _str(st.get("description")) or "desconocido"
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

    season_type = (_rec(event.get("season")) or {}).get("type")
    stage = SEASON_TYPE_LABELS.get(season_type, "")

    notes = _arr(comp.get("notes"))
    bracket_note = (
        next(
            (_str(n.get("headline")) for n in notes if isinstance(n, dict) and n.get("headline")),
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


def _fetch_event(event_id: str, clock_ts: int) -> tuple[str, dict | None]:
    url = ESPN_EVENT_URL.format(league=LEAGUE_CODE, event_id=event_id)
    try:
        data = _fetch_json(url)
        header = _rec(data.get("header")) or {}
        competitions = _arr(header.get("competitions"))
        if not competitions or not isinstance(competitions[0], dict):
            return event_id, None
        comp = competitions[0]
        event = {
            "id": str(event_id),
            "date": _str(comp.get("date")) or _str(header.get("date")) or "",
            "shortName": _str(header.get("shortName")) or "",
            "season": _rec(header.get("season")) or {},
            "competitions": [comp],
            "status": _rec(comp.get("status")) or {},
        }
        return event_id, _parse_match(event, clock_ts)
    except Exception:
        return event_id, None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def fetch_event_by_id(event_id: str) -> dict | None:
    """Obtiene un partido directamente por su ID de ESPN."""
    _, match = _fetch_event(event_id, int(time.time() * 1000))
    return match


def fetch_all_known_matches() -> dict[str, dict]:
    """Obtiene en paralelo todos los partidos conocidos. Retorna {match_id: match_data}."""
    clock_ts = int(time.time() * 1000)
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_event, eid, clock_ts): eid for eid in KNOWN_MATCH_IDS}
        for fut in as_completed(futures):
            try:
                eid, match = fut.result()
                if match:
                    results[eid] = match
            except Exception:
                pass

    return results


_ESPN_API_V2 = "https://site.api.espn.com/apis/v2/sports/soccer"


def fetch_group_map() -> dict[str, str]:
    """Retorna {team_id: nombre_grupo} desde el endpoint de posiciones de ESPN."""
    url = f"{_ESPN_API_V2}/{LEAGUE_CODE}/standings?lang=es&region=es"
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
