"""Al conectar la primera cuenta REAL se borra todo lo de prueba, y «no
repetir fotos ya publicadas» es la opción de serie."""

from __future__ import annotations

from typing import Any

from lot_bot.database.models import PublishJob, Setting
from lot_bot.publishing.listings import ListingFilter
from lot_bot.wallapop.auth.base import AuthCredential, AuthKind, AuthMethod, AuthOutcome


class LoginDePrueba(AuthMethod):
    """Como si la persona iniciara sesión en Wallapop en su navegador."""

    kind = AuthKind.BROWSER_SESSION

    def requirements(self):
        return []

    def authenticate(self, account_ref: str, **context: Any) -> AuthOutcome:
        return AuthOutcome(
            True, AuthCredential(kind=AuthKind.BROWSER_SESSION, metadata={"account_ref": account_ref})
        )


def _con_datos_de_prueba(app, monkeypatch, tmp_path):
    from PIL import Image

    from lot_bot.wallapop.browser.driver import PlaywrightLauncher

    refs = [a.internal_ref for a in app.accounts.list_accounts()]
    app.listings.sync_all(refs)
    app.publish_queue.enqueue_master(None, refs[:2], copies=2, start=False)
    foto = tmp_path / "mia.jpg"
    Image.new("RGB", (900, 700), (120, 110, 100)).save(foto)
    app.master_ads.add_images(None, [{"path": str(foto), "file_format": "JPEG", "width": 900, "height": 700}])
    app.publish_queue.mark_photo_used("solo-demo", refs[0])
    app.publish_queue.mark_photo_used("tambien-real", refs[0])
    monkeypatch.setattr(PlaywrightLauncher, "available", lambda self: (True, ""))
    app.set_integration_mode("navegador")
    return refs


def test_la_primera_cuenta_real_borra_todo_lo_de_prueba(app, monkeypatch, tmp_path):
    demo = _con_datos_de_prueba(app, monkeypatch, tmp_path)
    assert app.listings.search(ListingFilter(limit=500))
    fotos_antes = len(app.master_ads.get(None).images)
    real = app.accounts.add_account("Mi tienda")
    app.publish_queue.mark_photo_used("tambien-real", real.internal_ref)

    app.accounts.connect(real.internal_ref, method=LoginDePrueba())

    cuentas = app.accounts.list_accounts()
    assert [a.alias for a in cuentas] == ["Mi tienda"]  # las DEMO ya no están
    assert all(v.account_ref == real.internal_ref for v in app.listings.search(ListingFilter(limit=500)))
    with app.db.session_scope() as session:
        assert session.query(PublishJob).filter(PublishJob.is_demo.is_(True)).count() == 0
    usadas = app.publish_queue.used_photos()
    assert "solo-demo" not in usadas  # esa foto vuelve a estar libre
    assert usadas["tambien-real"]["cuentas"] == [real.internal_ref]
    assert len(app.master_ads.get(None).images) == fotos_antes  # tus fotos no se tocan
    assert any("Datos de prueba borrados" in e.action for e in app.audit.recent(limit=20))
    assert all(ref not in [a.internal_ref for a in cuentas] for ref in demo)


def test_en_modo_demo_no_se_borra_nada(app):
    antes = [a.internal_ref for a in app.accounts.list_accounts()]
    app.accounts.connect(antes[0])  # reconectar una cuenta DEMO
    assert [a.internal_ref for a in app.accounts.list_accounts()] == antes


def test_conectar_otra_cuenta_real_despues_no_borra_nada(app, monkeypatch, tmp_path):
    _con_datos_de_prueba(app, monkeypatch, tmp_path)
    primera = app.accounts.add_account("Mi tienda")
    app.accounts.connect(primera.internal_ref, method=LoginDePrueba())
    segunda = app.accounts.add_account("Tienda Norte")
    app.accounts.connect(segunda.internal_ref, method=LoginDePrueba())
    assert [a.alias for a in app.accounts.list_accounts()] == ["Mi tienda", "Tienda Norte"]


# ---------------------------------------------------------------------------
# No repetir fotos: la opción de serie
# ---------------------------------------------------------------------------
def test_no_repetir_fotos_viene_activado(app):
    assert app.publish_queue.settings()["rotate_photos"] is True


def test_una_configuracion_antigua_pasa_a_no_repetir(app):
    with app.db.session_scope() as session:  # guardada antes del cambio
        session.merge(Setting(key="publicacion", value={"rotate_photos": False}))
    assert app.publish_queue.settings()["rotate_photos"] is True


def test_si_lo_apagas_a_proposito_se_respeta(app):
    app.publish_queue.save_settings(rotate_photos=False)
    assert app.publish_queue.settings()["rotate_photos"] is False


def test_sin_fotos_propias_se_publica_igual(app):
    """En DEMO (solo fotos de ejemplo) no hay nada que rotar: no se para."""
    queue = app.publish_queue
    refs = [a.internal_ref for a in app.accounts.list_accounts()][:1]
    job = queue.enqueue_master(None, refs, copies=2)
    queue.run_until_idle()
    progreso = queue.progress(job)
    assert progreso.published == 2 and progreso.status == "completed"
