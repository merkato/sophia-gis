"""Login i hasło do Sophii w menedżerze uwierzytelniania QGIS (Ustawienia → Opcje → Uwierzytelnianie).

To zaszyfrowana baza QGIS chroniona hasłem głównym. QGIS może zapamiętać hasło główne w systemowym
pęku kluczy (Windows: Menedżer poświadczeń), więc w praktyce nie trzeba go wpisywać. W QgsSettings
trzymamy tylko identyfikator wpisu (authcfg), nigdy hasło.
"""
from __future__ import annotations

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

KEY = "fia/authcfg"


def _result(res, cfg: QgsAuthMethodConfig) -> tuple[bool, QgsAuthMethodConfig]:
    # PyQGIS zwraca bool albo (bool, konfiguracja) — zależnie od wersji
    if isinstance(res, tuple):
        return bool(res[0]), (res[1] if len(res) > 1 and isinstance(res[1], QgsAuthMethodConfig) else cfg)
    return bool(res), cfg


def _manager():
    am = QgsApplication.authManager()
    return None if am is None or am.isDisabled() else am


def saved_id() -> str:
    return QgsSettings().value(KEY, "") or ""


def load() -> tuple[str, str] | None:
    """(login, hasło) z menedżera uwierzytelniania; może poprosić o hasło główne."""
    am, cid = _manager(), saved_id()
    if am is None or not cid or cid not in am.configIds():
        return None
    cfg = QgsAuthMethodConfig()
    ok, cfg = _result(am.loadAuthenticationConfig(cid, cfg, True), cfg)
    if not ok or not cfg.config("password"):
        return None
    return cfg.config("username"), cfg.config("password")


def save(url: str, login: str, password: str) -> bool:
    am = _manager()
    if am is None or not am.setMasterPassword(True):     # pyta o hasło główne (raz na sesję)
        return False
    cid = saved_id()
    cfg = QgsAuthMethodConfig("Basic")
    cfg.setName(f"Sophia – {url}")
    cfg.setUri(url)
    cfg.setConfig("username", login)
    cfg.setConfig("password", password)
    if cid and cid in am.configIds():
        cfg.setId(cid)
        ok, cfg = _result(am.updateAuthenticationConfig(cfg), cfg)
    else:
        ok, cfg = _result(am.storeAuthenticationConfig(cfg), cfg)
    if ok and cfg.id():
        QgsSettings().setValue(KEY, cfg.id())
    return ok


def forget() -> None:
    am, cid = _manager(), saved_id()
    if am is not None and cid and cid in am.configIds():
        am.removeAuthenticationConfig(cid)
    QgsSettings().remove(KEY)
