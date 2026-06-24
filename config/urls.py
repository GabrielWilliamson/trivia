from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from trivia.views import GroupsView, GroupView, PredictionView, StandingsView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", StandingsView.as_view()),
    path("prediction/<str:match_id>", PredictionView.as_view()),
    path("grupos/", GroupsView.as_view(), name="groups"),
    path("grupos/<str:key>/", GroupView.as_view(), name="group"),
]
