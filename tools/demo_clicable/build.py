"""Monta la demo clicable de LOT Bot a partir de capturar_clic.py.

Uso: python build.py <carpeta de capturar_clic> <salida>
Crea en <salida>:
  - index.html + img/*.jpg      (para publicar como página)
  - LOT_Bot_demo.html           (un solo archivo, se abre con doble clic)
"""

import base64
import json
import sys
from pathlib import Path

from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
(out / "img").mkdir(parents=True, exist_ok=True)
meta = json.loads((src / "demo.json").read_text(encoding="utf-8"))


def sid(s: str) -> str:
    return s.replace("_", "-")


usadas: dict[str, str] = {}


def jpg(nombre: str) -> str:
    if nombre not in usadas:
        destino = out / "img" / Path(nombre).with_suffix(".jpg").name
        Image.open(src / "img" / nombre).convert("RGB").save(destino, quality=82, optimize=True)
        usadas[nombre] = destino.name
    return usadas[nombre]


estados = {}
for k, e in meta["estados"].items():
    zonas = []
    for z in e["zonas"]:
        z = dict(z)
        if z.get("a"):
            z["a"] = sid(z["a"])
        if z.get("imgs"):
            z["imgs"] = [jpg(i) for i in z["imgs"]]
        zonas.append({kk: (round(v, 5) if isinstance(v, float) else v) for kk, v in z.items()})
    estados[sid(k)] = {"img": jpg(e["img"]), "titulo": e["titulo"], "vista": e["vista"], "zonas": zonas}

TEXTOS = {
    "asistente": "Pídele las cosas con tus palabras: publicar anuncios, ver cómo van las cuentas, cambiar precios…",
    "cuentas": "Todas tus cuentas de Wallapop, cada una con su propio perfil del navegador. LOT Bot no guarda tus contraseñas.",
    "publicacion": "La cola publica los anuncios uno detrás de otro, a su ritmo, y sigue sola aunque Wallapop pida una verificación.",
    "anuncios": "Todos tus anuncios de todas las cuentas. Los de prueba (DEMO) se quitan al momento.",
    "estadisticas": "Visitas y favoritos de cada anuncio, y qué funciona mejor.",
    "imagenes": "Tus fotos, subidas desde el ordenador. Se guardan en LOT Bot y las usas en tus anuncios.",
    "principal": "Rellenas tu anuncio una sola vez y LOT Bot publica exactamente esto en todas las cuentas.",
    "configuracion": "Datos de tu negocio, plantillas, el asistente, Wallapop y el ritmo de publicación.",
    "panel": "Un resumen de cuentas, anuncios y actividad.",
    "productos": "Tu catálogo: medidas, colores y precios de cada producto.",
    "historial": "Todo lo que ha hecho el bot, con fecha, hora y resultado.",
    "logs": "Si algo falla, aquí ves qué ha pasado y por qué.",
}
datos = {
    "ancho": meta["ancho"], "alto": meta["alto"],
    "pantallas": meta["pantallas"],
    "textos": [TEXTOS.get(ic, "") for ic in meta["iconos"]],
    "estados": estados,
}

PAGINA = (Path(__file__).parent / "plantilla.html").read_text(encoding="utf-8")
pagina = PAGINA.replace("__DATOS__", json.dumps(datos, ensure_ascii=False, separators=(",", ":")))
(out / "index.html").write_text(pagina.replace("__RUTA__", "img/"), encoding="utf-8")

# Versión de un solo archivo: las imágenes van dentro.
incrustadas = {
    n: "data:image/jpeg;base64," + base64.b64encode((out / "img" / n).read_bytes()).decode()
    for n in set(usadas.values())
}
offline = pagina.replace("__RUTA__", "")
offline = offline.replace("const INCRUSTADAS = null;", "const INCRUSTADAS = " + json.dumps(incrustadas) + ";")
cabecera = (
    '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
)
fin_head = offline.index("</style>") + len("</style>")
offline = cabecera + offline[:fin_head] + "\n</head>\n<body>\n" + offline[fin_head:] + "\n</body>\n</html>\n"
(out / "LOT_Bot_demo.html").write_text(offline, encoding="utf-8")
total = sum((out / "img" / n).stat().st_size for n in set(usadas.values()))
print(len(estados), "estados ·", len(set(usadas.values())), "imágenes ·", round(total / 1e6, 1), "MB ·",
      "un archivo:", round(len(offline) / 1e6, 1), "MB")
