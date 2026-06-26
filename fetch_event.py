"""
Fetch a single ESPN event by ID and print the parsed match data.

Usage:
    python fetch_event.py 760489
    python fetch_event.py 760489 760490 760491
"""

import json
import sys
import time
import urllib.request

from trivia.espn import _fetch_json, _parse_match, LEAGUE_CODE, LEAGUE_NAME

ESPN_EVENT_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event_id}&lang=en&region=us"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?lang=en&region=us"


def fetch_event_by_id(event_id: str) -> dict | None:
    """Fetch a single event directly by its ESPN event ID."""
    # First try the summary endpoint — gives full event detail
    url = ESPN_EVENT_URL.format(league=LEAGUE_CODE, event_id=event_id)
    try:
        data = _fetch_json(url)
        # summary wraps the event under "header" → "competitions"
        header = data.get("header") or {}
        competitions = header.get("competitions") or []
        if competitions:
            # Reconstruct a minimal event dict that _parse_match expects
            comp = competitions[0]
            event = {
                "id": str(event_id),
                "date": comp.get("date") or header.get("date") or "",
                "shortName": header.get("shortName") or "",
                "season": header.get("season") or {},
                "competitions": [comp],
                "status": comp.get("status") or {},
            }
            clock_ts = int(time.time() * 1000)
            return _parse_match(event, clock_ts)
    except Exception as exc:
        print(f"[warn] summary endpoint failed for {event_id}: {exc}", file=sys.stderr)

    # Fallback: search the live scoreboard (works when match is today)
    try:
        data = _fetch_json(ESPN_SCOREBOARD_URL.format(league=LEAGUE_CODE))
        clock_ts = int(time.time() * 1000)
        for event in data.get("events") or []:
            if str(event.get("id")) == str(event_id):
                return _parse_match(event, clock_ts)
    except Exception as exc:
        print(f"[warn] scoreboard fallback failed for {event_id}: {exc}", file=sys.stderr)

    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python fetch_event.py <event_id> [event_id ...]")
        sys.exit(1)

    event_ids = sys.argv[1:]
    results = []

    for eid in event_ids:
        print(f"Fetching event {eid}...", file=sys.stderr)
        match = fetch_event_by_id(eid)
        if match:
            results.append(match)
            print(f"  OK: {match.get('home', {}).get('name')} vs {match.get('away', {}).get('name')} — {match.get('status')}", file=sys.stderr)
        else:
            print(f"  NOT FOUND: {eid}", file=sys.stderr)

    print(json.dumps(results if len(results) != 1 else results[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
