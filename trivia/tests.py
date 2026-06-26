"""
Tests de la app de trivia.

Ejecución:
    python manage.py test trivia
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from trivia.models import Prediction
from trivia.views import _score_prediction


# ---------------------------------------------------------------------------
# Utilidades compartidas entre tests
# ---------------------------------------------------------------------------

def _partido(match_id: str, *, state: str = "post", local: int = 1, visita: int = 0) -> dict:
    """Crea un partido simulado con el resultado indicado."""
    return {
        "id": match_id,
        "state": state,
        "teamsConfirmed": True,
        "home": {"id": "h", "name": "Local FC", "score": local, "abbreviation": "LOC", "logo": ""},
        "away": {"id": "a", "name": "Visita FC", "score": visita, "abbreviation": "VIS", "logo": ""},
        "date": "2026-06-28T18:00Z",
        "stage": "Round of 32",
        "status": "full time",
        "minute": "90'",
        "detail": "FT",
        "bracketNote": "",
        "inPenalties": False,
        "clockSeconds": 0,
        "clockUpdatedAt": 0,
        "clockRunning": False,
        "venue": {"name": "", "city": "", "country": ""},
    }


def _mock_espn(partidos_por_fase: dict | None = None):
    """
    Reemplaza fetch_stage_matches para que los tests nunca llamen a la API de ESPN.
    Devuelve los partidos indicados según la fase.
    """
    data = partidos_por_fase or {}
    return patch("trivia.views.fetch_stage_matches", side_effect=lambda fase: data.get(fase, []))


# ---------------------------------------------------------------------------
# Tests unitarios — función de puntuación
# ---------------------------------------------------------------------------

class TestPuntuacion(TestCase):
    """Verifica que la función _score_prediction asigne los puntos correctamente."""

    def test_marcador_exacto_da_5_puntos(self):
        self.assertEqual(_score_prediction(2, 1, 2, 1), 5)

    def test_empate_exacto_da_5_puntos(self):
        # Predijo 0-0 y terminó 0-0
        self.assertEqual(_score_prediction(0, 0, 0, 0), 5)

    def test_resultado_correcto_local_gana_da_2_puntos(self):
        # Predijo 3-0, terminó 1-0 — acertó el ganador
        self.assertEqual(_score_prediction(3, 0, 1, 0), 2)

    def test_resultado_correcto_visita_gana_da_2_puntos(self):
        # Predijo 0-2, terminó 0-1 — acertó el ganador
        self.assertEqual(_score_prediction(0, 2, 0, 1), 2)

    def test_resultado_correcto_empate_da_2_puntos(self):
        # Predijo 1-1, terminó 2-2 — acertó que sería empate
        self.assertEqual(_score_prediction(1, 1, 2, 2), 2)

    def test_predijo_local_termino_visita_da_0(self):
        self.assertEqual(_score_prediction(1, 0, 0, 1), 0)

    def test_predijo_local_termino_empate_da_0(self):
        self.assertEqual(_score_prediction(2, 0, 1, 1), 0)

    def test_predijo_empate_termino_local_da_0(self):
        self.assertEqual(_score_prediction(1, 1, 2, 0), 0)


# ---------------------------------------------------------------------------
# Tests de integración — tabla de posiciones y desempate
# ---------------------------------------------------------------------------

class TestTablaDePosiciones(TestCase):
    """
    Verifica el ranking del leaderboard y los criterios de desempate:
      1. Más puntos
      2. Más predicciones exactas
      3. Menor error acumulado de goles (quien estuvo más cerca del marcador real)
    """

    def setUp(self):
        # Cuatro jugadores de prueba
        self.alice = User.objects.create_user("alice", password="x")
        self.bob = User.objects.create_user("bob", password="x")
        self.carlos = User.objects.create_user("carlos", password="x")
        self.diana = User.objects.create_user("diana", password="x")
        self.client = Client()

    def _tabla(self, partidos_por_fase: dict) -> list[dict]:
        """Devuelve el leaderboard mockeando la API de ESPN."""
        with _mock_espn(partidos_por_fase):
            resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        return resp.context["leaderboard"]

    def _predecir(self, usuario, match_id, local, visita):
        Prediction.objects.create(
            user=usuario, match_id=match_id, home_score=local, away_score=visita
        )

    # ------------------------------------------------------------------
    # Ranking básico
    # ------------------------------------------------------------------

    def test_mas_puntos_ocupa_primer_lugar(self):
        """El jugador con más puntos aparece primero en la tabla."""
        partido = _partido("m1", local=2, visita=0)
        self._predecir(self.alice, "m1", 2, 0)  # exacto = 5 pts
        self._predecir(self.bob, "m1", 1, 0)    # resultado correcto = 2 pts

        tabla = self._tabla({"round-of-32": [partido]})
        nombres = [u["username"] for u in tabla]

        self.assertLess(nombres.index("alice"), nombres.index("bob"))
        self.assertEqual(tabla[0]["points"], 5)
        self.assertEqual(tabla[1]["points"], 2)

    def test_jugador_sin_predicciones_no_aparece_en_tabla(self):
        """Diana no hizo ninguna predicción y no debe aparecer en el leaderboard."""
        partido = _partido("m1", local=1, visita=0)
        self._predecir(self.alice, "m1", 1, 0)
        # diana no predice nada

        tabla = self._tabla({"round-of-32": [partido]})
        nombres = [u["username"] for u in tabla]

        self.assertIn("alice", nombres)
        self.assertNotIn("diana", nombres)

    def test_partido_en_curso_no_suma_puntos(self):
        """Un partido que aún está jugándose no debe contarse en el puntaje."""
        en_vivo = _partido("m1", state="in", local=1, visita=0)
        self._predecir(self.alice, "m1", 1, 0)

        tabla = self._tabla({"round-of-32": [en_vivo]})
        self.assertEqual(tabla[0]["points"], 0)

    def test_partidos_no_finalizados_no_cuentan(self):
        """Un partido pendiente (state=pre) no debe aparecer como finalizado."""
        pendiente = _partido("m1", state="pre")
        with _mock_espn({"round-of-32": [pendiente]}):
            resp = self.client.get("/")
        self.assertEqual(resp.context["finished_count"], 0)

    # ------------------------------------------------------------------
    # Escenarios de empate — probabilidad alta en el torneo
    # ------------------------------------------------------------------

    def test_empate_en_puntos_se_resuelve_por_mas_exactos(self):
        """
        Situación muy probable: dos jugadores terminan con los mismos puntos.

        Alice llega a 10 pts con 2 marcadores exactos (5+5).
        Bob llega a 10 pts con 5 resultados correctos (2+2+2+2+2).

        Ambos tienen 10 pts, pero Alice tiene más exactos → Alice gana el desempate.
        """
        # Cinco partidos que terminan 1-0 (victoria local)
        partidos = [_partido(f"m{i}", local=1, visita=0) for i in range(1, 6)]

        # Alice: exacta en m1 y m2, falla el resto (predice victoria visitante)
        self._predecir(self.alice, "m1", 1, 0)  # exacto +5
        self._predecir(self.alice, "m2", 1, 0)  # exacto +5
        self._predecir(self.alice, "m3", 0, 1)  # fallo (predijo visita gana) +0
        self._predecir(self.alice, "m4", 0, 1)  # fallo +0
        self._predecir(self.alice, "m5", 0, 1)  # fallo +0
        # Alice: 10 pts, exactos=2

        # Bob: acierta el resultado en los 5 partidos pero sin exacto
        for i in range(1, 6):
            self._predecir(self.bob, f"m{i}", 2, 0)  # resultado correcto +2 (no exacto)
        # Bob: 10 pts, exactos=0

        tabla = self._tabla({"round-of-32": partidos})

        self.assertEqual(tabla[0]["points"], 10)
        self.assertEqual(tabla[1]["points"], 10)
        # Alice gana por tener más exactos
        self.assertEqual(tabla[0]["username"], "alice")
        self.assertEqual(tabla[0]["exact"], 2)
        self.assertEqual(tabla[1]["username"], "bob")
        self.assertEqual(tabla[1]["exact"], 0)

    def test_empate_en_puntos_y_exactos_se_resuelve_por_error_de_goles(self):
        """
        Situación posible: dos jugadores con mismos puntos Y mismos exactos.

        Alice y Bob aciertan el resultado en 3 partidos (6 pts cada uno, sin exactos).
        Alice predijo marcadores más cercanos al real → menor error de goles → Alice gana.

        Partido 1 real: 3-1
          Alice predijo 2-1 → error = |2-3| + |1-1| = 1
          Bob   predijo 1-0 → error = |1-3| + |0-1| = 3

        Partido 2 real: 2-0
          Alice predijo 1-0 → error = |1-2| + |0-0| = 1
          Bob   predijo 3-0 → error = |3-2| + |0-0| = 1

        Partido 3 real: 4-2
          Alice predijo 3-2 → error = |3-4| + |2-2| = 1
          Bob   predijo 1-0 → error = |1-4| + |0-2| = 5

        Alice total: 6 pts, exactos=0, error=3
        Bob   total: 6 pts, exactos=0, error=9
        Alice gana el desempate por menor error de goles.
        """
        p1 = _partido("m1", local=3, visita=1)
        p2 = _partido("m2", local=2, visita=0)
        p3 = _partido("m3", local=4, visita=2)

        self._predecir(self.alice, "m1", 2, 1)  # resultado correcto, error=1
        self._predecir(self.alice, "m2", 1, 0)  # resultado correcto, error=1
        self._predecir(self.alice, "m3", 3, 2)  # resultado correcto, error=1

        self._predecir(self.bob, "m1", 1, 0)  # resultado correcto, error=3
        self._predecir(self.bob, "m2", 3, 0)  # resultado correcto, error=1
        self._predecir(self.bob, "m3", 1, 0)  # resultado correcto, error=5

        tabla = self._tabla({"round-of-32": [p1, p2, p3]})

        alice_stat = next(u for u in tabla if u["username"] == "alice")
        bob_stat = next(u for u in tabla if u["username"] == "bob")

        # Ambos tienen los mismos puntos y exactos
        self.assertEqual(alice_stat["points"], 6)
        self.assertEqual(bob_stat["points"], 6)
        self.assertEqual(alice_stat["exact"], 0)
        self.assertEqual(bob_stat["exact"], 0)

        # Alice tiene menor error acumulado → aparece primero
        self.assertEqual(alice_stat["goal_error"], 3)
        self.assertEqual(bob_stat["goal_error"], 9)
        self.assertLess(
            tabla.index(alice_stat),
            tabla.index(bob_stat),
        )

    def test_empate_triple_desempate_por_error_de_goles(self):
        """
        Tres jugadores con los mismos puntos y exactos.
        Se ordena por quien tuvo menor error de goles acumulado.

        Partido real: 3-2
          Alice predijo 3-2 → exacto = 5 pts, error = 0
          Bob   predijo 2-1 → resultado correcto = 2 pts, error = 2
          Carlos predijo 1-0 → resultado correcto = 2 pts, error = 4

        Partido 2 real: 1-0
          Alice predijo 0-1 → fallo = 0 pts, error = 2
          Bob   predijo 2-0 → resultado correcto = 2 pts, error = 1
          Carlos predijo 3-0 → resultado correcto = 2 pts, error = 2

        Alice:  5+0=5 pts, exactos=1, error=2
        Bob:    2+2=4 pts, exactos=0, error=3
        Carlos: 2+2=4 pts, exactos=0, error=6

        No hay empate real aquí (Alice tiene más puntos).
        Bob y Carlos tienen empate en puntos y exactos → Bob gana por error.
        """
        p1 = _partido("m1", local=3, visita=2)
        p2 = _partido("m2", local=1, visita=0)

        self._predecir(self.alice, "m1", 3, 2)   # exacto, error=0
        self._predecir(self.alice, "m2", 0, 1)   # fallo, error=2

        self._predecir(self.bob, "m1", 2, 1)     # resultado correcto, error=2
        self._predecir(self.bob, "m2", 2, 0)     # resultado correcto, error=1

        self._predecir(self.carlos, "m1", 1, 0)  # resultado correcto, error=4
        self._predecir(self.carlos, "m2", 3, 0)  # resultado correcto, error=2

        tabla = self._tabla({"round-of-32": [p1, p2]})
        nombres = [u["username"] for u in tabla]

        # Alice lidera por puntos
        self.assertEqual(nombres[0], "alice")
        # Bob y Carlos tienen empate en puntos y exactos; Bob gana por menos error
        self.assertEqual(nombres[1], "bob")
        self.assertEqual(nombres[2], "carlos")

    # ------------------------------------------------------------------
    # Casos especiales del torneo
    # ------------------------------------------------------------------

    def test_partido_en_penales_usa_marcador_del_tiempo_reglamentario(self):
        """
        Si el partido va a penales, el puntaje de los penales NO cuenta.
        Se usa el marcador al final del tiempo suplementario.

        Real: 1-1 (va a penales, 4-2 en la tanda).
        Alice predijo 1-1 → exacto = 5 pts (acertó el marcador reglamentario).
        Bob   predijo 0-0 → resultado correcto = 2 pts (acertó que sería empate).
        """
        partido = _partido("m_pen", local=1, visita=1)
        partido["inPenalties"] = True
        partido["home"]["shootoutScore"] = 4
        partido["away"]["shootoutScore"] = 2

        self._predecir(self.alice, "m_pen", 1, 1)  # exacto en tiempo reglamentario
        self._predecir(self.bob, "m_pen", 0, 0)    # empate correcto, no exacto

        tabla = self._tabla({"round-of-32": [partido]})
        stats = {u["username"]: u for u in tabla}

        self.assertEqual(stats["alice"]["points"], 5)
        self.assertEqual(stats["bob"]["points"], 2)

    def test_puntos_se_acumulan_entre_fases(self):
        """Los puntos de octavos, cuartos, semis y final se suman en el mismo total."""
        r32 = _partido("r32_1", local=2, visita=1)
        r16 = _partido("r16_1", local=0, visita=0)

        self._predecir(self.alice, "r32_1", 2, 1)  # exacto = 5
        self._predecir(self.alice, "r16_1", 0, 0)  # exacto = 5

        tabla = self._tabla({"round-of-32": [r32], "round-of-16": [r16]})
        alice_stat = next(u for u in tabla if u["username"] == "alice")

        self.assertEqual(alice_stat["points"], 10)
        self.assertEqual(alice_stat["exact"], 2)

    def test_prediccion_duplicada_no_permitida(self):
        """No se puede predecir dos veces el mismo partido (restricción de BD)."""
        from django.db import IntegrityError

        self._predecir(self.alice, "m1", 1, 0)
        with self.assertRaises(IntegrityError):
            self._predecir(self.alice, "m1", 2, 0)
