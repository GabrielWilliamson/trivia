from django.contrib import admin
from django.urls import include, path

from trivia.views import (
    GroupsView,
    PredictionView,
    RegisterView,
    StandingsView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/register/", RegisterView.as_view(), name="register"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", StandingsView.as_view()),
    path("prediction/<str:match_id>", PredictionView.as_view()),
    path("groups/", GroupsView.as_view(), name="groups"),
]
