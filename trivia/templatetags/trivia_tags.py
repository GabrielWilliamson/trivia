from django import template

register = template.Library()


STAGE_ES = {
    "Round of 32": "Dieciseisavos de final",
    "Round of 16": "Octavos de Final",
    "Quarterfinals": "Cuartos de Final",
    "Semifinals": "Semifinales",
    "Third Place": "Tercer Lugar",
    "Final": "Final",
    "Group Stage": "Fase de Grupos",
}


@register.filter
def get_match(matches, match_id):
    if isinstance(matches, dict):
        return matches.get(str(match_id))
    return next(
        (
            m
            for m in matches
            if str(m.get("id") if isinstance(m, dict) else m.id) == str(match_id)
        ),
        None,
    )


@register.filter
def gt(value, arg):
    try:
        return int(value) > int(arg)
    except (TypeError, ValueError):
        return False


@register.filter
def translate_stage(stage):
    return STAGE_ES.get(stage, stage)


@register.filter
def has_prediction(predictions, match_id):
    if not predictions:
        return False
    return str(match_id) in predictions
