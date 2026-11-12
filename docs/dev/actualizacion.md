# Actualizar y mantener LOT Bot

## Publicar una versión nueva (Windows y Mac, actualización automática)

1. Sube `__version__` en `lot_bot/__init__.py` (y `version` en `pyproject.toml`).
2. Pasa los cambios a la rama `estable`.
3. Crea la etiqueta con las novedades que verá el cliente:
   `git tag -a v1.1.0 -m "• Qué ha cambiado" && git push origin v1.1.0`
4. GitHub Actions (`publicar-version.yml`):
   - compila el instalador de Windows (Inno Setup) y la app de Mac (chip Apple e Intel);
   - los PRUEBA como el cliente: instalar sin permisos de administrador,
     autoprueba, actualizar encima, desinstalar (los datos se quedan) y, en
     Mac, sustituir la app desde el .dmg;
   - firma si hay certificados (Authenticode / Developer ID + notarización);
   - publica la versión en GitHub y la registra en la web.
5. En `/admin/versiones` decides a cuántos llega (despliegue gradual), si es
   obligatoria o si la retiras.

Variables necesarias: `RELEASE_API_TOKEN` (Vercel y GitHub Secrets, el mismo),
`GITHUB_RELEASES_REPO` y `GITHUB_RELEASES_TOKEN` (Vercel). Ver `web/README.md`.

## Cómo se actualiza el cliente

**Programa instalado** (`lot_bot/core/release_updater.py`):

1. Al abrir y cada pocas horas, LOT Bot pregunta a la web con su licencia
   (solo las licencias activas reciben versiones).
2. Si hay una nueva, sale la franja «Hay una versión nueva» → «Actualizar».
3. Descarga el instalador y comprueba su tamaño y su huella SHA-256 contra un
   pase **firmado** por el servidor (Ed25519, la misma clave que las
   licencias). Si no cuadra, no instala nada.
4. Windows: ejecuta el instalador en modo silencioso; cierra LOT Bot, lo
   sustituye y lo vuelve a abrir. Mac: un guion espera a que LOT Bot se
   cierre, monta el .dmg, comprueba la firma de la app, sustituye
   «LOT Bot.app» y la abre.
5. Nunca se actualiza con una cola publicando.

**Copia del código fuente** (desarrollo, clientes antiguos): sigue el
actualizador por git (`lot_bot/core/updater.py`), rama `estable`.

**Sus datos no están en la carpeta del programa**, sino en `%LOCALAPPDATA%\LOT Bot`
(Windows) o `~/Library/Application Support/LOT Bot` (Mac). Instalar, actualizar
o desinstalar no los toca.

## Cambios en la base de datos

El esquema se crea con `create_all()`, que **añade tablas nuevas pero no modifica las
existentes**. Para cambios en tablas con datos ya en producción:

### Cambios compatibles (columna nueva opcional)

SQLite acepta `ALTER TABLE ... ADD COLUMN`. Añade la columna al modelo y una migración
puntual en el arranque.

### Cambios incompatibles

`alembic` ya está en las dependencias. Para empezar a usarlo:

```bash
.venv/bin/alembic init migrations
# configurar sqlalchemy.url y target_metadata = lot_bot.database.models.Base.metadata
.venv/bin/alembic revision --autogenerate -m "descripcion"
.venv/bin/alembic upgrade head
```

Haz que el arranque ejecute `upgrade head` antes de abrir la ventana, y **copia la base
de datos antes de migrar**.

## Actualizar dependencias

```bash
.venv/bin/pip list --outdated
.venv/bin/pip install --upgrade <paquete>
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Cuidado especial con **PySide6**: los saltos de versión mayor cambian APIs. Está fijada
a una versión concreta en `requirements.txt` a propósito.

## Añadir una herramienta nueva a la IA

1. Escribe el manejador en el módulo correspondiente de `lot_bot/ai/tools/`.
2. Declara el `Tool` con su esquema JSON, su categoría y, si escribe,
   `requires_confirmation=True` y la `capability` que necesita.
3. Añádelo a la lista del módulo (se registra solo en `build_registry()`).
4. Escribe una prueba: que pida confirmación y que no ejecute nada sin ella.

Con `requires_confirmation=True` el manejador **debe** devolver `confirm_first(...)`
cuando `context.confirmed` es `False`. El registro lo comprueba de todos modos.

## Añadir una operación de Wallapop

1. Añade el valor al enum `Capability`.
2. Añade el método abstracto a `WallapopService`.
3. Impleméntalo en `MockWallapopService` (datos simulados coherentes).
4. Impleméntalo en `ConnectWallapopService` usando `self._call(...)`.
5. Documenta la nueva entrada en `config/endpoint_map.example.yaml`.
6. Pruebas: que el mock funcione y que sin endpoint declarado se responda
   `NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS`.

## Añadir una pantalla

1. Crea la vista en `lot_bot/ui/views/` heredando de `BaseView`.
2. Impleméntale `build()` y `refresh()`.
3. Expórtala en `lot_bot/ui/views/__init__.py`.
4. Añádela a `NAVIGATION` en `lot_bot/ui/main_window.py`.
5. La prueba de humo la recorrerá automáticamente.

## Copias de seguridad

Lo que conviene respaldar del cliente:

```
%LOCALAPPDATA%\LOT Bot\lot_bot.db      catálogo, cuentas, historial
%LOCALAPPDATA%\LOT Bot\images\         fotografías importadas
%LOCALAPPDATA%\LOT Bot\config\         clave maestra (si no está en el llavero)
```

Sin la clave maestra, los tokens no se pueden descifrar y hay que volver a conectar
las cuentas (el catálogo y el historial se conservan igualmente).

## Mantenimiento periódico

* El historial se puede purgar con `AuditService.purge_older_than(días)`.
* Los logs rotan solos (5 ficheros de 2 MB).
* Las imágenes importadas no se borran solas: se guardan por hash, así que no se
  duplican.
