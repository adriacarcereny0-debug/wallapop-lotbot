# Demo clicable de LOT Bot

Genera una demo web del programa real (en MODO DEMO, sin tocar Wallapop) donde
se puede pulsar todo: pantallas, pestañas, botones, desplegables y campos.

```
PYTHONPATH=. QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 \
  .venv/bin/python tools/demo_clicable/capturar_clic.py /tmp/demo_capturas
.venv/bin/python tools/demo_clicable/build.py /tmp/demo_capturas /tmp/demo_web
```

- `/tmp/demo_web/index.html` + `img/`: para publicar como página.
- `/tmp/demo_web/LOT_Bot_demo.html`: un solo archivo, se abre con doble clic.

Las ventanas del programa se fotografían y se cierran solas (como «Cancelar»):
nunca se confirma ni se envía nada.
