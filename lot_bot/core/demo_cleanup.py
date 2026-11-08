"""Al conectar la primera cuenta REAL de Wallapop se borra todo lo de prueba.

Lo que se borra (solo lo que es de demostración):
  - las cuentas DEMO, con sus anuncios, mensajes y estadísticas;
  - las colas de publicación de prueba;
  - las imágenes de prueba que generó el modo DEMO;
  - los productos de ejemplo que crea el modo DEMO (si no se han cambiado);
  - el historial de lo que hicieron las cuentas DEMO;
  - el registro de «fotos ya publicadas» en cuentas DEMO (así esas fotos se
    pueden publicar de verdad).

Lo que NUNCA se toca: el anuncio principal, tus fotos, tus productos, tu
configuración y todo lo de las cuentas reales.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

if TYPE_CHECKING:  # pragma: no cover
    from lot_bot.bootstrap import Application

logger = logging.getLogger(__name__)

#: Productos de ejemplo que crea `seed_demo_catalog` (nombre, descripción).
DEMO_PRODUCT_DESCRIPTION = "Canapé abatible con gran capacidad de almacenaje."
DEMO_PRODUCT_NAMES = {
    "Canapé abatible 90x190 Gris",
    "Canapé abatible 135x190 Blanco",
    "Canapé abatible 150x190 Roble",
}


def has_demo_data(app: Application) -> bool:
    return any(a.is_demo for a in app.accounts.list_accounts(include_demo=True))


def purge_demo_data(app: Application) -> dict[str, int]:
    """Borra todo lo de prueba. Devuelve cuánto se ha borrado de cada cosa."""
    from lot_bot.database.models import AuditLog, Product, PublishJob

    demo_refs = [a.internal_ref for a in app.accounts.list_accounts(include_demo=True) if a.is_demo]
    counts = {"cuentas": 0, "colas": 0, "imagenes": 0, "productos": 0, "historial": 0}
    if not demo_refs:
        return counts

    # Fotos «ya publicadas» solo en cuentas de prueba: vuelven a estar libres.
    queue = app.publish_queue
    used = queue.used_photos()
    cleaned: dict[str, Any] = {}
    for key, entry in used.items():
        accounts = [r for r in entry.get("cuentas", []) if r not in demo_refs]
        if accounts:
            cleaned[key] = {**entry, "cuentas": accounts}
    if cleaned != used:
        queue._save_used(cleaned)

    with app.db.session_scope() as session:
        jobs = session.scalars(select(PublishJob).where(PublishJob.is_demo.is_(True))).all()
        for job in jobs:
            session.delete(job)
        counts["colas"] = len(jobs)
        counts["historial"] = session.execute(
            delete(AuditLog).where(AuditLog.account_ref.in_(demo_refs))
        ).rowcount or 0
        products = session.scalars(
            select(Product).where(
                Product.name.in_(DEMO_PRODUCT_NAMES),
                Product.description == DEMO_PRODUCT_DESCRIPTION,
            )
        ).all()
        for product in products:
            session.delete(product)
        counts["productos"] = len(products)

    for ref in demo_refs:
        if app.accounts.remove_account(ref):
            counts["cuentas"] += 1

    generation = getattr(app, "image_generation", None)
    if generation is not None:
        try:
            from lot_bot.images.generation.demo import DemoImageGenerator

            demo_images = [
                i["id"]
                for i in generation.history(10_000)
                if i["proveedor"] == DemoImageGenerator.name or i["cuenta"] in demo_refs
            ]
            if demo_images:
                counts["imagenes"] = generation.delete_images(demo_images)
        except Exception:  # las imágenes de prueba no deben impedir lo demás
            logger.warning("No se han podido borrar las imágenes de prueba", exc_info=True)

    app.audit.record_success(
        "Datos de prueba borrados al conectar la primera cuenta real",
        detail=", ".join(f"{v} {k}" for k, v in counts.items() if v) or "nada",
    )
    logger.info("Datos de prueba borrados: %s", counts)
    return counts


def on_account_connected(app: Application, internal_ref: str) -> dict[str, int] | None:
    """Aviso de «cuenta conectada»: si es una cuenta REAL y aún hay datos de
    prueba, se borran todos."""
    info = app.accounts.get_account(internal_ref)
    if info is None or info.is_demo or app.demo_mode or not has_demo_data(app):
        return None
    return purge_demo_data(app)
