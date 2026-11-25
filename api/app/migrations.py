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
    ("audit_undo", """
        -- Cofanie operacji: wpisy jednego żądania mają wspólne `op`, `srid` = układ geometrii w old/new_data
        ALTER TABLE portal.audit_log ADD COLUMN IF NOT EXISTS op uuid;
        ALTER TABLE portal.audit_log ADD COLUMN IF NOT EXISTS srid int;
        ALTER TABLE portal.audit_log ADD COLUMN IF NOT EXISTS undone_at timestamptz;
        CREATE INDEX IF NOT EXISTS audit_log_undo_idx ON portal.audit_log (project_id, user_id, id DESC)
            WHERE op IS NOT NULL AND undone_at IS NULL;
    """),
    ("basemaps_wms", """
        -- Zewnętrzne usługi WMS jako podkład/nakładka (np. krajowe integracje GUGiK)
        ALTER TABLE portal.basemaps DROP CONSTRAINT IF EXISTS basemaps_kind_check;
        ALTER TABLE portal.basemaps ADD CONSTRAINT basemaps_kind_check CHECK (kind IN ('wmts', 'xyz', 'sophia', 'wms'));
        INSERT INTO portal.basemaps (name, kind, is_overlay, opacity, visible_default, sort_order, attribution, config)
        SELECT 'Użytki gruntowe (KIUG)', 'wms', true, 0.85, false, 60, '© GUGiK, starostwa (KIUG)',
               '{"url": "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzytkowGruntowych",
                 "layers": "uzytki,kontury", "format": "image/png", "version": "1.1.1"}'::jsonb
        WHERE NOT EXISTS (SELECT 1 FROM portal.basemaps WHERE config->>'url' LIKE '%KrajowaIntegracjaUzytkowGruntowych%');
        INSERT INTO portal.basemaps (name, kind, is_overlay, opacity, visible_default, sort_order, attribution, config)
        SELECT 'Plany miejscowe (KIMPZP)', 'wms', true, 0.7, false, 70, '© GUGiK, gminy (KIMPZP)',
               '{"url": "https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaMiejscowychPlanowZagospodarowaniaPrzestrzennego",
                 "layers": "raster,wektor-str,wektor-pow,wektor-lin,wektor-lzb,wektor-pkt,granice,plany_granice",
                 "format": "image/png", "version": "1.1.1"}'::jsonb
        WHERE NOT EXISTS (SELECT 1 FROM portal.basemaps WHERE config->>'url' LIKE '%KrajowaIntegracjaMiejscowychPlanow%');
    """),
    ("plugins", """
        -- Wtyczki (api/app/plugins.py): stan, migracje i uprawnienia (grupy albo użytkownicy)
        CREATE TABLE IF NOT EXISTS portal.plugins (
            id          text PRIMARY KEY,
            enabled     boolean NOT NULL DEFAULT false,
            settings    jsonb NOT NULL DEFAULT '{}',
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS portal.plugin_migrations (
            plugin_id   text NOT NULL,
            name        text NOT NULL,
            applied_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (plugin_id, name)
        );
        CREATE TABLE IF NOT EXISTS portal.plugin_access (
            id          serial PRIMARY KEY,
            plugin_id   text NOT NULL,
            capability  text NOT NULL,
            group_id    int REFERENCES portal.groups(id) ON DELETE CASCADE,
            user_id     int REFERENCES portal.users(id) ON DELETE CASCADE,
            CHECK (num_nonnulls(group_id, user_id) = 1)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS plugin_access_uniq
            ON portal.plugin_access (plugin_id, capability, coalesce(group_id, 0), coalesce(user_id, 0));
    """),
    ("upload_limits", """
        -- Limity wielkości plików w projekcie (app/storage.py): niższe niż globalne, per zbiór plików
        CREATE TABLE IF NOT EXISTS portal.upload_limits (
            project_id  int NOT NULL REFERENCES portal.projects(id) ON DELETE CASCADE,
            set_id      text NOT NULL,                 -- <id_warstwy>:<pole> albo plugin:<wtyczka>:<id>
            max_mb      numeric(8, 1) NOT NULL CHECK (max_mb > 0),
            source      text NOT NULL DEFAULT 'webui' CHECK (source IN ('webui', 'fia')),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            updated_by  text,
            PRIMARY KEY (project_id, set_id)
        );
    """),
    ("protection_unlock", """
        -- Bezpiecznik obiektów chronionych (app/protection.py): odblokowanie projektu na określony czas
        CREATE TABLE IF NOT EXISTS portal.protection_unlock (
            project_id  int PRIMARY KEY REFERENCES portal.projects(id) ON DELETE CASCADE,
            until       timestamptz NOT NULL,
            reason      text NOT NULL,
            by_login    text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS portal.protection_unlock_log (
            id          bigserial PRIMARY KEY,
            project_id  int NOT NULL,
            action      text NOT NULL CHECK (action IN ('unlock', 'lock')),
            until       timestamptz,
            reason      text,
            by_login    text NOT NULL,
            at          timestamptz NOT NULL DEFAULT now()
        );
    """),
]


async def run_migrations() -> None:
    async with portal_conn() as conn:
        # jeden proces naraz (kilka workerów uvicorn startuje równocześnie)
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('sophia_migrations'))")
        for name, sql in MIGRATIONS:
            await conn.execute(sql)
            log.debug("migracja %s: OK", name)
