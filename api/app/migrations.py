"""Idempotentne zmiany schematu `portal`, uruchamiane przy starcie API.

db/init/*.sql wykonuje się tylko przy tworzeniu pustej bazy, więc nowe tabele dla działających
instalacji dokładamy tutaj (CREATE ... IF NOT EXISTS). Kolejność ma znaczenie, wpisy tylko dopisujemy.
"""
import logging

from .db import portal_conn

log = logging.getLogger("sophia")

MIGRATIONS: list[tuple[str, str]] = [
    ("basemaps", """
        CREATE TABLE IF NOT EXISTS portal.basemaps (
            id              serial PRIMARY KEY,
            name            text NOT NULL,
            kind            text NOT NULL CHECK (kind IN ('wmts', 'xyz', 'sophia')),
            is_overlay      boolean NOT NULL DEFAULT false,   -- nakładka (np. cieniowanie) zamiast podkładu
            opacity         real NOT NULL DEFAULT 1 CHECK (opacity >= 0 AND opacity <= 1),
            visible_default boolean NOT NULL DEFAULT false,   -- podkład startowy / nakładka włączona
            enabled         boolean NOT NULL DEFAULT true,
            sort_order      integer NOT NULL DEFAULT 0,
            attribution     text,
            config          jsonb NOT NULL DEFAULT '{}',      -- parametry zależne od rodzaju
            updated_at      timestamptz NOT NULL DEFAULT now()
        );
        -- Pierwsze uruchomienie: OpenStreetMap jako podkład, żeby mapa nie była pusta
        INSERT INTO portal.basemaps (name, kind, visible_default, sort_order, attribution, config)
        SELECT 'OpenStreetMap', 'xyz', true, 100, '© OpenStreetMap',
               '{"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "max_zoom": 19}'::jsonb
        WHERE NOT EXISTS (SELECT 1 FROM portal.basemaps);
    """),
    ("permissions_v2", """
        -- Serwer: autor projektów (publikacja przez Fię bez pełnych praw administratora)
        ALTER TABLE portal.users ADD COLUMN IF NOT EXISTS can_publish boolean NOT NULL DEFAULT false;
        -- Projekt opublikowany przez autora: autor ma w nim rolę „manager”
        ALTER TABLE portal.projects ADD COLUMN IF NOT EXISTS owner_id int REFERENCES portal.users(id) ON DELETE SET NULL;
        -- Grupa w projekcie: prawa do zdjęć i plików (domyślnie tak) oraz zakres danych
        ALTER TABLE portal.project_access ADD COLUMN IF NOT EXISTS can_photos boolean NOT NULL DEFAULT true;
        ALTER TABLE portal.project_access ADD COLUMN IF NOT EXISTS can_files boolean NOT NULL DEFAULT true;
        ALTER TABLE portal.project_access ADD COLUMN IF NOT EXISTS scope_all boolean NOT NULL DEFAULT true;
        ALTER TABLE portal.project_access ADD COLUMN IF NOT EXISTS scope_codes text[] NOT NULL DEFAULT '{}';
    """),
]


async def run_migrations() -> None:
    async with portal_conn() as conn:
        # jeden proces naraz (kilka workerów uvicorn startuje równocześnie)
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('sophia_migrations'))")
        for name, sql in MIGRATIONS:
            await conn.execute(sql)
            log.debug("migracja %s: OK", name)
