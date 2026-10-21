-- A workflow import excludes a comment card the reaction beat had no room for, and says so
-- (spec 2026-10-21 5c-1, section 7). A person's own exclusion carries no reason.
ALTER TABLE studio_import_decisions
    ADD COLUMN reason TEXT CHECK (reason IS NULL OR reason = 'not_placed');
