"""Leer precios en euros tal y como los muestra Wallapop (formato español).

«1.250 €» son mil doscientos cincuenta euros (punto de miles), «11,44 €» son
once con cuarenta y cuatro (coma decimal). Antes, «1.250» se leía como 1,25:
el precio de los anuncios y la comprobación tras cambiar un precio salían mal.
"""

from __future__ import annotations

import re

#: Precio seguido de «€» dentro de un texto. Los miles se separan con punto o
#: espacio (nunca con un salto de línea: serían dos números distintos).
PRICE_RE = re.compile(
    r"(\d{1,3}(?:[. \u202f]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)[ \u202f]*€"
)
#: Un número con posibles separadores (para el valor de un campo de precio).
_NUMBER_RE = re.compile(r"\d[\d., \u202f]*\d|\d")
_GROUPED_DOT = re.compile(r"\d{1,3}(?:\.\d{3})+")
_GROUPED_COMMA = re.compile(r"\d{1,3}(?:,\d{3})+")


def parse_amount(raw: str) -> float | None:
    """«1.250» → 1250, «1.250,50» → 1250.5, «11,44» → 11.44, «11.44» → 11.44."""
    text = re.sub(r"[\s\u202f]", "", raw or "")
    if not text:
        return None
    if "." in text and "," in text:
        # El último separador es el decimal; el otro, el de miles.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        if _GROUPED_DOT.fullmatch(text):
            text = text.replace(".", "")
    elif "," in text:
        text = text.replace(",", "") if _GROUPED_COMMA.fullmatch(text) else text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def prices_in(text: str) -> list[float]:
    """Todos los precios «… €» que aparecen en un texto."""
    flat = (text or "").replace("\xa0", " ")
    values = (parse_amount(m.group(1)) for m in PRICE_RE.finditer(flat))
    return [v for v in values if v is not None]


def first_price(text: str) -> float | None:
    """El primer precio «… €» de un texto (None si no hay ninguno)."""
    found = prices_in(text)
    return found[0] if found else None


def number_in(text: str) -> float | None:
    """El primer número de un texto, con sus separadores («1.250,00» → 1250)."""
    match = _NUMBER_RE.search((text or "").replace("\xa0", " "))
    return parse_amount(match.group(0)) if match else None
