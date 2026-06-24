"""
Fetches FIFA World Cup 2026 fixtures from ESPN API v2 and writes them to
trivia/data/<stage>.json.

Usage:
    python manage.py fetch_fixtures                 # Round of 32 (default)
    python manage.py fetch_fixtures --stage round-of-16
    python manage.py fetch_fixtures --stage all
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from trivia.espn import LEAGUE_CODE, LEAGUE_NAME, STAGE_DATE_RANGES, STAGE_LABELS, fetch_stage_matches


class Command(BaseCommand):
    help = "Fetch FIFA World Cup 2026 fixtures from ESPN API v2"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stage",
            default="round-of-32",
            choices=[*STAGE_DATE_RANGES.keys(), "all"],
            help="Knockout stage to fetch (default: round-of-32)",
        )
        parser.add_argument(
            "--out-dir",
            default=None,
            help="Output directory (default: trivia/data/)",
        )

    def handle(self, *args, **options):
        out_dir = (
            Path(options["out_dir"])
            if options["out_dir"]
            else Path(__file__).resolve().parents[2] / "data"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        stages = list(STAGE_DATE_RANGES.keys()) if options["stage"] == "all" else [options["stage"]]

        for stage_key in stages:
            self.stdout.write(f"Fetching {stage_key}...")
            matches = fetch_stage_matches(stage_key)
            payload = {
                "leagueCode": LEAGUE_CODE,
                "leagueName": LEAGUE_NAME,
                "stage": STAGE_LABELS.get(stage_key, stage_key),
                "fetchedAt": datetime.now(tz=timezone.utc).isoformat(),
                "count": len(matches),
                "matches": matches,
            }
            out_path = out_dir / f"{stage_key}.json"
            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            self.stdout.write(self.style.SUCCESS(f"  -> {out_path} ({len(matches)} matches)"))
