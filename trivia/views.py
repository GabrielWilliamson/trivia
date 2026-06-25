from datetime import datetime
from zoneinfo import ZoneInfo
from django import forms
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.generic import TemplateView, View
from django.views.generic.base import TemplateResponseMixin

from trivia.espn import fetch_stage_matches, fetch_match_by_id, fetch_group_map


class RegisterForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Ese usuario ya existe.")
        return username

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
        )


class RegisterView(View):
    def get(self, request):
        return render(request, "registration/register.html", {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
        return render(request, "registration/register.html", {"form": form})


DISPLAY_TZ = ZoneInfo("America/Guatemala")


STAGE_ORDER = [
    "group-stage",
    "round-of-32",
    "round-of-16",
    "quarterfinals",
    "semifinals",
    "third-place",
    "final",
]


def _score_prediction(
    pred_home: int, pred_away: int, real_home: int, real_away: int
) -> int:
    """
    5 pts — exact score
    2 pts — correct winner/draw
    0 pts — wrong
    """
    if pred_home == real_home and pred_away == real_away:
        return 5
    pred_diff = pred_home - pred_away
    real_diff = real_home - real_away
    pred_outcome = (pred_diff > 0) - (pred_diff < 0)
    real_outcome = (real_diff > 0) - (real_diff < 0)
    return 2 if pred_outcome == real_outcome else 0


class PredictionView(LoginRequiredMixin, TemplateResponseMixin, View):
    template_name = "prediction.html"

    def _get_match_or_404(self, match_id: str) -> dict:
        match = fetch_match_by_id(match_id)
        if match is None:
            raise Http404(f"Match {match_id} not found")
        return match

    def get(self, request, match_id: str):
        from trivia.models import Prediction

        match = self._get_match_or_404(match_id)
        existing = Prediction.objects.filter(
            match_id=match_id, user=request.user
        ).first()
        return self.render_to_response({"match": match, "existing": existing})

    def post(self, request, match_id: str):
        from trivia.models import Prediction

        match = self._get_match_or_404(match_id)

        existing = Prediction.objects.filter(
            match_id=match_id, user=request.user
        ).first()
        if existing:
            return self.render_to_response(
                {
                    "match": match,
                    "existing": existing,
                    "already_saved": True,
                }
            )

        if not match.get("teamsConfirmed", True):
            return self.render_to_response(
                {"match": match, "error": "Los equipos aún no están definidos."}
            )
        if match.get("state") == "post":
            return self.render_to_response(
                {"match": match, "error": "Este partido ya finalizó."}
            )
        if match.get("state") == "in":
            return self.render_to_response(
                {"match": match, "error": "Este partido ya está en juego."}
            )

        try:
            home_score = int(request.POST["home_score"])
            away_score = int(request.POST["away_score"])
        except (KeyError, ValueError):
            return self.render_to_response(
                {"match": match, "error": "Marcadores inválidos."}
            )

        Prediction.objects.create(
            match_id=match_id,
            user=request.user,
            home_score=home_score,
            away_score=away_score,
        )
        return redirect("/")


class StandingsView(TemplateView):
    template_name = "standings.html"

    def get_context_data(self, **kwargs):
        from trivia.models import Prediction

        ctx = super().get_context_data(**kwargs)

        all_matches: dict = {}
        finished_matches: dict = {}
        for stage in STAGE_ORDER:
            try:
                for m in fetch_stage_matches(stage):
                    all_matches[m["id"]] = m
                    if m.get("state") == "post":
                        finished_matches[m["id"]] = m
            except Exception:
                pass

        ctx["matches"] = all_matches
        if self.request.user.is_authenticated:
            ctx["predictions"] = set(
                Prediction.objects.filter(user=self.request.user).values_list("match_id", flat=True)
            )
        else:
            ctx["predictions"] = set()

        user_stats: dict[str, dict] = {}
        for pred in Prediction.objects.select_related("user").filter(
            user__isnull=False
        ):
            uname = pred.user.username
            if uname not in user_stats:
                user_stats[uname] = {
                    "username": uname,
                    "points": 0,
                    "exact": 0,
                    "result": 0,
                    "predicted": 0,
                    "scored": 0,
                }
            user_stats[uname]["predicted"] += 1
            match = finished_matches.get(pred.match_id)
            if match:
                real_home = match["home"]["score"]
                real_away = match["away"]["score"]
                pts = _score_prediction(
                    pred.home_score, pred.away_score, real_home, real_away
                )
                user_stats[uname]["points"] += pts
                user_stats[uname]["scored"] += 1
                if pts == 5:
                    user_stats[uname]["exact"] += 1
                elif pts == 2:
                    user_stats[uname]["result"] += 1

        ctx["leaderboard"] = sorted(
            user_stats.values(), key=lambda u: u["points"], reverse=True
        )
        ctx["finished_count"] = len(finished_matches)
        return ctx


def _fmt_match_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(DISPLAY_TZ)
        return f"{dt.day:02d}/{dt.month:02d} {dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        return ""


def _group_matches(matches: list, group_map: dict[str, str]) -> list[tuple[str, list]]:
    groups: dict[str, list] = {}
    for match in matches:
        home_id = (match.get("home") or {}).get("id", "")
        key = (
            group_map.get(home_id)
            or group_map.get((match.get("away") or {}).get("id", ""))
            or "Sin grupo"
        )
        groups.setdefault(key, []).append(match)
    return sorted(groups.items())


class GroupsView(LoginRequiredMixin, TemplateView):
    template_name = "groups.html"

    def get_context_data(self, **kwargs):
        from trivia.models import Prediction

        ctx = super().get_context_data(**kwargs)
        matches = fetch_stage_matches("group-stage")
        group_map = fetch_group_map()
        for match in matches:
            match["date_display"] = _fmt_match_date(match.get("date", ""))
        ctx["groups"] = _group_matches(matches, group_map)
        ctx["predicted_ids"] = set(
            Prediction.objects.filter(user=self.request.user).values_list(
                "match_id", flat=True
            )
        )
        return ctx
