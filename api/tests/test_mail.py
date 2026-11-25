"""Powiadomienia e-mail: odbiorcy z ustawienia, wiadomość, wysyłka przez SMTP (podstawiony serwer) i dziennik."""
import asyncio
import contextlib

import pytest

from app import mail
from app.config import get_settings


def test_parse_user_ids():
    assert mail.parse_user_ids("3, 7,x,3; 9") == [3, 7, 9]
    assert mail.parse_user_ids([1, "2"]) == [1, 2]
    assert mail.parse_user_ids(None) == []


@pytest.fixture
def smtp(monkeypatch):
    s = get_settings()
    for k, v in {"smtp_host": "mail", "smtp_port": 587, "smtp_from": "powiadomienia@webgis.example.pl",
                 "smtp_starttls": False, "smtp_ssl": False, "smtp_user": None}.items():
        monkeypatch.setattr(s, k, v)
    sent, logged = [], []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("mail", 587)

        def send_message(self, msg):
            sent.append(msg)

        def quit(self):
            pass

    class Conn:
        async def execute(self, q, params):
            logged.append(params)

    @contextlib.asynccontextmanager
    async def fake_conn():
        yield Conn()

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail, "portal_conn", fake_conn)
    return sent, logged


def test_send_mail(smtp):
    sent, logged = smtp
    asyncio.run(mail.send_mail(["a@x.pl", "a@x.pl", " b@x.pl "], "Temat", "Treść ąę", plugin="wylaczenia"))
    (msg,) = sent
    assert msg["To"] == "a@x.pl, b@x.pl" and msg["Subject"] == "Temat"
    assert "powiadomienia@webgis.example.pl" in msg["From"] and "Treść ąę" in msg.get_content()
    assert logged[0][0] == "wylaczenia" and logged[0][3] is True


def test_send_mail_errors(smtp, monkeypatch):
    with pytest.raises(mail.MailError, match="adresat"):
        asyncio.run(mail.send_mail([], "T", "x"))
    monkeypatch.setattr(get_settings(), "smtp_host", None)
    with pytest.raises(mail.MailError, match="skonfigurowana"):
        asyncio.run(mail.send_mail(["a@x.pl"], "T", "x"))


def test_recipients(monkeypatch):
    rows = [{"id": 3, "login": "jan", "email": "jan@x.pl"}, {"id": 7, "login": "ola", "email": "Ola@X.pl"}]

    class Res:
        async def fetchall(self):
            return rows

    class Conn:
        async def execute(self, q, params):
            return Res()

    @contextlib.asynccontextmanager
    async def fake_conn():
        yield Conn()

    monkeypatch.setattr(mail, "portal_conn", fake_conn)
    got = asyncio.run(mail.recipients("3, ola@x.pl, obcy@y.pl, jan@x.pl"))
    # konto 3, konto z adresem ola@x.pl (adres z konta), adres spoza kont; jan@x.pl drugi raz — pominięty
    assert got == [("jan", "jan@x.pl"), ("ola", "Ola@X.pl"), (None, "obcy@y.pl")]
