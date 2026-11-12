"""Licencias de LOT Bot.

Cómo funciona (resumen):

* La persona escribe su clave (LOTB-XXXX-XXXX-XXXX) en la pantalla de
  activación. LOT Bot la manda al servidor de licencias junto con una huella
  ANÓNIMA del ordenador (un hash, nunca el identificador en claro).
* El servidor contesta con un «pase» firmado (Ed25519) que vale 72 h y nunca
  más allá de la caducidad de la licencia. LOT Bot comprueba la firma con la
  clave PÚBLICA que lleva dentro: nadie puede fabricar un pase sin la clave
  privada, que solo tiene el servidor.
* Cada 4-6 h LOT Bot renueva el pase en segundo plano. Sin conexión sigue
  funcionando mientras el último pase valga (hasta 3 días).
* Si la licencia caduca, se suspende o se revoca, LOT Bot no hace nada nuevo
  en Wallapop real: lo que se está publicando en ese momento termina y la
  cola se pausa. Los datos y la configuración no se tocan nunca.
* El modo DEMO es gratis y no necesita licencia.
"""

from lot_bot.licensing.manager import LicenseManager, LicenseState, LicenseStatus

__all__ = ["LicenseManager", "LicenseState", "LicenseStatus"]
