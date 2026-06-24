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

COUNTRY_ES = {
    "United States": "Estados Unidos",
    "Germany": "Alemania",
    "England": "Inglaterra",
    "France": "Francia",
    "Netherlands": "Países Bajos",
    "Brazil": "Brasil",
    "Mexico": "México",
    "Japan": "Japón",
    "South Korea": "Corea del Sur",
    "Saudi Arabia": "Arabia Saudita",
    "Morocco": "Marruecos",
    "Canada": "Canadá",
    "Croatia": "Croacia",
    "Denmark": "Dinamarca",
    "Poland": "Polonia",
    "Czech Republic": "República Checa",
    "Switzerland": "Suiza",
    "New Zealand": "Nueva Zelanda",
    "Peru": "Perú",
    "Trinidad and Tobago": "Trinidad y Tobago",
    "Iran": "Irán",
    "United Arab Emirates": "Emiratos Árabes Unidos",
    "Qatar": "Catar",
    "South Africa": "Sudáfrica",
    "Egypt": "Egipto",
    "Tunisia": "Túnez",
    "Algeria": "Argelia",
    "Cameroon": "Camerún",
    "Ivory Coast": "Costa de Marfil",
    "Romania": "Rumanía",
    "Hungary": "Hungría",
    "Slovakia": "Eslovaquia",
    "Scotland": "Escocia",
    "Wales": "Gales",
    "Northern Ireland": "Irlanda del Norte",
    "Ireland": "Irlanda",
    "Ukraine": "Ucrania",
    "Russia": "Rusia",
    "Turkey": "Turquía",
    "Türkiye": "Turquía",
    "Congo DR": "R.D. del Congo",
    "Cape Verde": "Cabo Verde",
    "Haiti": "Haití",
    "Iraq": "Irak",
    "Jordan": "Jordania",
    "Uzbekistan": "Uzbekistán",
    "Austria": "Austria",
    "Greece": "Grecia",
    "Iceland": "Islandia",
    "Finland": "Finlandia",
    "Norway": "Noruega",
    "Sweden": "Suecia",
    "Belgium": "Bélgica",
    "Italy": "Italia",
    "Panama": "Panamá",
    "Kenya": "Kenia",
    "Thailand": "Tailandia",
    "Philippines": "Filipinas",
    "Malaysia": "Malasia",
    "Singapore": "Singapur",
    "Bosnia-Herzegovina": "Bosnia y Herzegovina",
    "North Macedonia": "Macedonia del Norte",
    "Costa Rica": "Costa Rica",
    "Honduras": "Honduras",
    "El Salvador": "El Salvador",
    "Guatemala": "Guatemala",
    "Venezuela": "Venezuela",
    "Colombia": "Colombia",
    "Ecuador": "Ecuador",
    "Uruguay": "Uruguay",
    "Paraguay": "Paraguay",
    "Chile": "Chile",
    "Bolivia": "Bolivia",
    "Argentina": "Argentina",
    "Portugal": "Portugal",
    "Spain": "España",
    "Serbia": "Serbia",
    "Nigeria": "Nigeria",
    "Ghana": "Ghana",
    "Senegal": "Senegal",
    "Jamaica": "Jamaica",
    "Australia": "Australia",
    "China": "China",
    "Curaçao": "Curaçao",
}


@register.filter
def get_match(matches, match_id):
    return matches.get(str(match_id))


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
def translate_country(name):
    return COUNTRY_ES.get(name, name)


@register.filter
def has_prediction(predictions, match_id):
    if not predictions:
        return False
    return str(match_id) in predictions
