"""Actualizar LOT Bot con un clic desde GitHub.

Los clientes tienen LOT Bot como copia del repositorio de GitHub (son
colaboradores). Cuando hay cambios nuevos en la rama que siguen:

  1. LOT Bot lo detecta solo (`check`) y enseña qué ha cambiado;
  2. el cliente pulsa «Actualizar» (`apply`): se descargan los cambios, se
     instalan los componentes nuevos si hacen falta y LOT Bot se reinicia;
  3. si algo va mal, «Volver a la versión anterior» (`rollback`).

Los datos del cliente (cuentas, anuncios, fotos, configuración) viven fuera
del programa, en su carpeta de datos: actualizar no los toca. Nunca se
borran cambios hechos a mano en el programa: si los hay, se guardan aparte
(`git stash`) antes de actualizar.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Rama que se sigue si la copia del cliente no tiene una rama de GitHub asociada.
DEFAULT_BRANCH = "main"
#: Canal de versiones para clientes: si existe esta rama en GitHub, se sigue
#: ella (solo llega a los clientes lo que se publica ahí a propósito). Si no
#: existe, se sigue la rama de la copia del cliente.
CHANNEL_BRANCH = "estable"
#: Cada cuánto se mira si hay una versión nueva (con LOT Bot abierto).
CHECK_EVERY_HOURS = 6


@dataclass(slots=True)
class UpdateInfo:
    available: bool
    behind: int = 0
    changes: list[str] = field(default_factory=list)
    branch: str = ""
    latest: str = ""
    requirements_changed: bool = False
    message: str = ""


@dataclass(slots=True)
class UpdateResult:
    ok: bool
    message: str
    previous: str = ""
    current: str = ""
    requirements_installed: bool = False


def find_git() -> str | None:
    """git del sistema, o el de Git para Windows / GitHub Desktop."""
    found = shutil.which("git")
    if found:
        return found
    if sys.platform.startswith("win"):
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "cmd" / "git.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
        ]
        desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "GitHubDesktop"
        if desktop.is_dir():
            candidates += sorted(desktop.glob("app-*/resources/app/git/cmd/git.exe"), reverse=True)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


class Updater:
    def __init__(
        self,
        repo_dir: Path,
        state_file: Path,
        *,
        git: str | None = None,
        python: str | None = None,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.state_file = Path(state_file)
        self.git = git if git is not None else find_git()
        self.python = python or sys.executable
        self._run = run

    # ------------------------------------------------------------------
    @property
    def supported(self) -> bool:
        """Solo se actualiza así una copia del repositorio con git disponible."""
        return bool(self.git) and (self.repo_dir / ".git").exists()

    def unsupported_reason(self) -> str:
        if not (self.repo_dir / ".git").exists():
            return "Esta instalación no es una copia de GitHub: se actualiza a mano."
        return "No se encuentra git en este ordenador (instala Git para Windows o GitHub Desktop)."

    def _git(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return self._run(
            [self.git, *args],
            cwd=self.repo_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **kwargs,
        )

    def _out(self, *args: str, timeout: float = 120) -> str:
        result = self._git(*args, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "git ha fallado").strip()[:500])
        return result.stdout.strip()

    def tracked_branch(self) -> tuple[str, str]:
        """(remoto, rama) de donde llegan las versiones: el canal «estable» si
        existe en GitHub; si no, la rama que sigue esta copia (u origin/main)."""
        channel = self._git("ls-remote", "--exit-code", "--heads", "origin", CHANNEL_BRANCH, timeout=60)
        if channel.returncode == 0 and channel.stdout.strip():
            return "origin", CHANNEL_BRANCH
        result = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if result.returncode == 0 and "/" in result.stdout.strip():
            remote, branch = result.stdout.strip().split("/", 1)
            return remote, branch
        return "origin", DEFAULT_BRANCH

    def current_version(self) -> str:
        from lot_bot import __version__

        if not self.supported:
            return __version__
        try:
            commit, when = self._out("log", "-1", "--format=%h|%cd", "--date=format:%d/%m/%Y").split("|")
            return f"{__version__} · {commit} ({when})"
        except Exception:
            return __version__

    # ------------------------------------------------------------------
    def check(self) -> UpdateInfo:
        """Mira en GitHub si hay cambios nuevos (no cambia nada)."""
        if not self.supported:
            return UpdateInfo(False, message=self.unsupported_reason())
        remote, branch = self.tracked_branch()
        fetched = self._git("fetch", "--quiet", remote, branch, timeout=180)
        if fetched.returncode != 0:
            detail = (fetched.stderr or "").strip().splitlines()[-1:] or [""]
            return UpdateInfo(
                False, branch=branch,
                message="No se ha podido consultar GitHub (¿hay internet y acceso al repositorio?). "
                + detail[0][:200],
            )
        ref = f"{remote}/{branch}"
        behind = int(self._out("rev-list", "--count", f"HEAD..{ref}") or 0)
        if behind == 0:
            return UpdateInfo(False, branch=branch, message="LOT Bot está al día.")
        changes = [
            line for line in self._out("log", "--format=%s", "-n", "30", f"HEAD..{ref}").splitlines() if line
        ]
        changed_files = self._out("diff", "--name-only", f"HEAD...{ref}").splitlines()
        return UpdateInfo(
            True,
            behind=behind,
            changes=changes,
            branch=branch,
            latest=self._out("rev-parse", "--short", ref),
            requirements_changed="requirements.txt" in changed_files,
            message=f"Hay {behind} {'cambio nuevo' if behind == 1 else 'cambios nuevos'}.",
        )

    def apply(self) -> UpdateResult:
        """Descarga e instala los cambios. Hay que reiniciar LOT Bot después."""
        if not self.supported:
            return UpdateResult(False, self.unsupported_reason())
        info = self.check()
        if not info.available:
            return UpdateResult(False, info.message)
        remote, branch = "origin", info.branch
        if branch != CHANNEL_BRANCH:
            remote, branch = self.tracked_branch()
        previous = self._out("rev-parse", "HEAD")
        # Cambios hechos a mano en el programa: se guardan aparte, nunca se borran.
        if self._out("status", "--porcelain", "--untracked-files=no"):
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._out("stash", "push", "-m", f"LOT Bot: cambios locales antes de actualizar ({stamp})")
            logger.info("Había cambios locales en el programa: guardados con git stash.")
        merged = self._git("merge", "--ff-only", f"{remote}/{branch}")
        if merged.returncode != 0:
            return UpdateResult(
                False,
                "No se ha podido actualizar porque esta copia tiene cambios propios que no están en "
                "GitHub. Contacta con soporte.",
                previous=previous,
            )
        current = self._out("rev-parse", "HEAD")
        self._save_state({"anterior": previous, "actual": current, "fecha": datetime.now().isoformat()})
        installed = False
        if info.requirements_changed and (self.repo_dir / "requirements.txt").is_file():
            pip = self._run(
                [self.python, "-m", "pip", "install", "--quiet", "-r", str(self.repo_dir / "requirements.txt")],
                cwd=self.repo_dir, capture_output=True, text=True, timeout=1800, check=False,
            )
            if pip.returncode != 0:
                logger.warning("pip install tras actualizar: %s", (pip.stderr or "")[-500:])
            installed = pip.returncode == 0
        logger.info("LOT Bot actualizado de %s a %s.", previous[:8], current[:8])
        return UpdateResult(
            True,
            f"LOT Bot se ha actualizado ({info.behind} {'cambio' if info.behind == 1 else 'cambios'}).",
            previous=previous,
            current=current,
            requirements_installed=installed,
        )

    # ------------------------------------------------------------------
    def previous_version(self) -> str | None:
        return self._load_state().get("anterior")

    def rollback(self) -> UpdateResult:
        """Vuelve a la versión de antes de la última actualización."""
        previous = self.previous_version()
        if not self.supported or not previous:
            return UpdateResult(False, "No hay ninguna actualización anterior a la que volver.")
        current = self._out("rev-parse", "HEAD")
        if self._out("status", "--porcelain", "--untracked-files=no"):
            self._out("stash", "push", "-m", "LOT Bot: cambios locales antes de volver atrás")
        self._out("reset", "--hard", previous)
        self._save_state({"anterior": None, "deshecha": current, "fecha": datetime.now().isoformat()})
        return UpdateResult(True, "Has vuelto a la versión anterior.", previous=current, current=previous)

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, data: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def restart_lot_bot() -> None:
    """Abre LOT Bot de nuevo (la versión recién descargada) y cierra este."""
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, *sys.argv], close_fds=True, **kwargs)
