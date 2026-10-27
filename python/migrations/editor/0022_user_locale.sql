-- Restyle spec D1 (2026-10-29): the dashboard language each user chose; NULL until they
-- choose, and the browser language decides.
ALTER TABLE users
    ADD COLUMN locale TEXT CHECK (locale IS NULL OR locale IN ('en', 'id'));
