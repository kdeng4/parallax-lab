-- Mutable provider cache is separate from immutable research records.
-- Only fixed server-owned keys are accepted by the market service.
CREATE TABLE market_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL CHECK (octet_length(value) <= 1048576)
);
INSERT INTO schema_migrations (version) VALUES (2);
