"""Powiadomienia e-mail dla wtyczek (np. zgłoszenie potrzeby wsparcia w lustracji).

Wysyłka przez serwer SMTP z ustawień (`.env`): domyślnie lekki Postfix z docker-compose (usługa `mail`, profil
„mail”, tylko wysyłka, podpis DKIM — docs/SERVER.md), albo dowolny serwer SMTP (np. konto pocztowe operatora).
Adresy — z kont użytkowników (Panel → Użytkownicy → e-mail); wtyczka wskazuje użytkowników w ustawieniach
(typ ustawienia „users”). Każda wysyłka trafia do dziennika `portal.mail_log`.

    from app.mail import send_mail, user_emails
    to = await user_emails([3, 7])                       # [(login, e-mail)] aktywnych kont z adresem
    await send_mail([e for _, e in to], "Temat", "Treść", plugin="wylaczenia")
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .config import get_settings
from .db import portal_conn

log = logging.getLogger("sophia.mail")


class MailError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def parse_user_ids(value) -> list[int]:
    """Wartość ustawienia typu „users”: „1,5,7” (albo lista) -> [1, 5, 7]."""
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").replace(";", ",").split(",")
    out = []
    for v in raw:
        try:
            n = int(str(v).strip())
        except ValueError:
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def _tokens(value) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").replace(";", ",").replace("\n", ",").split(",")
    return [str(t).strip() for t in raw if str(t).strip()]


async def recipients(value) -> list[tuple[str | None, str]]:
    """Odbiorcy z wartości ustawienia typu „users”: identyfikatory kont (adres z konta) i adresy e-mail wpisane
    wprost (konto z tym adresem, a gdy go nie ma — sam adres). Bez powtórzeń, w kolejności wpisów."""
    tokens = _tokens(value)
    ids = parse_user_ids([t for t in tokens if t.isdigit()])
    mails = [t for t in tokens if "@" in t]
    by_id, by_mail = {}, {}
    if ids or mails:
        async with portal_conn() as conn:
            rows = await (await conn.execute(
                """SELECT id, login, btrim(email) AS email FROM portal.users
                    WHERE is_active AND coalesce(btrim(email), '') <> ''
                      AND (id = ANY(%s) OR lower(btrim(email)) = ANY(%s))""",
                (ids, [m.lower() for m in mails]))).fetchall()
        by_id = {r["id"]: (r["login"], r["email"]) for r in rows}
        by_mail = {r["email"].lower(): (r["login"], r["email"]) for r in rows}
    out: list[tuple[str | None, str]] = []
    for t in tokens:
        hit = by_id.get(int(t)) if t.isdigit() else (by_mail.get(t.lower()) or (None, t)) if "@" in t else None
        if hit and hit[1].lower() not in {e.lower() for _, e in out}:
            out.append(hit)
    return out


async def user_emails(user_ids: list[int]) -> list[tuple[str, str]]:
    """(login, e-mail) aktywnych użytkowników z podanym adresem — w kolejności identyfikatorów."""
    if not user_ids:
        return []
    async with portal_conn() as conn:
        rows = await (await conn.execute(
            """SELECT id, login, email FROM portal.users
                WHERE id = ANY(%s) AND is_active AND coalesce(btrim(email), '') <> ''""", (user_ids,))).fetchall()
    by = {r["id"]: (r["login"], r["email"].strip()) for r in rows}
    return [by[i] for i in user_ids if i in by]


def _send_sync(msg: EmailMessage) -> None:
    s = get_settings()
    ctx = ssl.create_default_context()
    if s.smtp_ssl:
        smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30, context=ctx)
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
    try:
        if s.smtp_starttls and not s.smtp_ssl:
            smtp.starttls(context=ctx)
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:  # noqa: BLE001 — połączenie mogło już zostać zamknięte
            pass


def build_message(to: list[str], subject: str, text: str, html: str | None = None) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.smtp_from_name or "Sophia WebGIS", s.smtp_from))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(s.smtp_from or "sophia").split("@")[-1])
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


async def send_mail(to: list[str], subject: str, text: str, *, html: str | None = None, plugin: str | None = None) -> None:
    """Wysyła jedną wiadomość do listy adresów; błąd — MailError (zapisany w dzienniku)."""
    to = [t for t in dict.fromkeys(a.strip() for a in to) if t]
    if not to:
        raise MailError("Brak adresatów (użytkownicy bez adresu e-mail?)")
    if not configured():
        raise MailError("Wysyłka e-mail nie jest skonfigurowana (SMTP_HOST, SMTP_FROM w .env)")
    error = None
    try:
        await asyncio.to_thread(_send_sync, build_message(to, subject, text, html))
    except (OSError, smtplib.SMTPException) as e:
        error = f"{type(e).__name__}: {e}"
    async with portal_conn() as conn:
        await conn.execute("INSERT INTO portal.mail_log (plugin, recipients, subject, ok, error) VALUES (%s, %s, %s, %s, %s)",
                           (plugin, to, subject, error is None, error))
    if error:
        log.warning("e-mail nie wysłany (%s): %s", subject, error)
        raise MailError(error)
    log.info("e-mail wysłany: %s -> %s", subject, ", ".join(to))
