-- Schemat aplikacyjny Sophii. Dane przestrzenne użytkownika żyją w innych schematach
-- (np. "public", "ewidencja"...) — "portal" przechowuje tylko konfigurację i uprawnienia.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS portal;
SET search_path = portal, public;

-- ---------------------------------------------------------------- użytkownicy i grupy
CREATE TABLE users (
    id            serial PRIMARY KEY,
    login         text NOT NULL UNIQUE,
    full_name     text,
    email         text,
    password_hash text NOT NULL,
    is_admin      boolean NOT NULL DEFAULT false,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE groups (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    description text
);

CREATE TABLE user_groups (
    user_id  int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id int NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, group_id)
);

-- ---------------------------------------------------------------- zasięgi przestrzenne
-- Nazwane obszary (gminy, obręby, rejony...). Przechowywane w EPSG:2180;
-- przy sprawdzaniu są transformowane do układu warstwy.
CREATE TABLE extents (
    id   serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    geom geometry(MultiPolygon, 2180) NOT NULL
);
CREATE INDEX extents_geom_idx ON extents USING gist (geom);

-- Przypisanie zasięgu do grupy LUB użytkownika. Brak przypisań = brak ograniczenia.
-- mode: 'view' ogranicza też podgląd (filtr WMS/WFS), 'edit' tylko edycję.
CREATE TABLE extent_assignments (
    id        serial PRIMARY KEY,
    extent_id int NOT NULL REFERENCES extents(id) ON DELETE CASCADE,
    user_id   int REFERENCES users(id) ON DELETE CASCADE,
    group_id  int REFERENCES groups(id) ON DELETE CASCADE,
    mode      text NOT NULL DEFAULT 'edit' CHECK (mode IN ('view', 'edit')),
    CHECK ((user_id IS NULL) <> (group_id IS NULL))
);

-- ---------------------------------------------------------------- projekty QGIS
CREATE TABLE projects (
    id          serial PRIMARY KEY,
    slug        text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9_-]*$'),
    title       text NOT NULL,
    description text,
    file_name   text NOT NULL,          -- względem PROJECTS_DIR, np. "ewidencja/ewidencja.qgz"
    sort_order  int NOT NULL DEFAULT 0,
    is_public   boolean NOT NULL DEFAULT false,  -- podgląd dla niezalogowanych
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Rola grupy w projekcie: viewer < editor < manager
CREATE TABLE project_access (
    project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    group_id   int NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    role       text NOT NULL CHECK (role IN ('viewer', 'editor', 'manager')),
    PRIMARY KEY (project_id, group_id)
);

-- Nadpisania per warstwa (layer_id = id warstwy w projekcie QGIS). Brak wiersza =
-- uprawnienia wynikają z roli projektu i konfiguracji warstwy (sidecar JSON).
CREATE TABLE layer_access (
    project_id int  NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    group_id   int  NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    layer_id   text NOT NULL,
    can_view   boolean NOT NULL DEFAULT true,
    can_insert boolean NOT NULL DEFAULT false,
    can_update boolean NOT NULL DEFAULT false,
    can_delete boolean NOT NULL DEFAULT false,
    PRIMARY KEY (project_id, group_id, layer_id)
);

-- ---------------------------------------------------------------- załączniki (PDF)
-- Plik na dysku (wolumen "attachments"), metadane tutaj. Obiekt identyfikowany
-- trójką (projekt, warstwa, klucz główny) — bez modyfikowania tabel użytkownika.
CREATE TABLE attachments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   int  NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    layer_id     text NOT NULL,
    feature_pk   text NOT NULL,
    file_name    text NOT NULL,
    content_type text NOT NULL,
    size_bytes   bigint NOT NULL,
    sha256       text NOT NULL,
    description  text,
    uploaded_by  int REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX attachments_feature_idx ON attachments (project_id, layer_id, feature_pk);

-- ---------------------------------------------------------------- dziennik zmian
CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    user_id    int REFERENCES users(id) ON DELETE SET NULL,
    project_id int REFERENCES projects(id) ON DELETE SET NULL,
    layer_id   text,
    feature_pk text,
    action     text NOT NULL,   -- insert | update | delete | attach | detach | login
    old_data   jsonb,
    new_data   jsonb
);
CREATE INDEX audit_log_feature_idx ON audit_log (project_id, layer_id, feature_pk);
