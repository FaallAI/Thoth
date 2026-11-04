-- Audit A1 (2026-10-30): a workspace token records who minted it, so it stops working once that
-- person leaves the workspace, loses the owner or admin role, or is disabled. Existing rows stay
-- NULL; a workspace token without a creator is refused.
ALTER TABLE access_tokens ADD COLUMN created_by_user_id TEXT REFERENCES users (user_id);
