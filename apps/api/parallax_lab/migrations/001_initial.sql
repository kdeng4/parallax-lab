CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE experiments (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    summary JSONB NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE events (
    id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL REFERENCES experiments(id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    timestamp TIMESTAMPTZ NOT NULL,
    run_id UUID,
    type TEXT NOT NULL,
    payload JSONB NOT NULL,
    UNIQUE (experiment_id, sequence)
);
CREATE INDEX experiments_recent ON experiments (created_at DESC, id DESC);
CREATE INDEX events_filter ON events (experiment_id, run_id, type, timestamp);
CREATE FUNCTION reject_research_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Research records are immutable; audit events are append-only'
        USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION reject_research_mutation();
CREATE TRIGGER experiments_immutable BEFORE UPDATE OR DELETE ON experiments
    FOR EACH ROW EXECUTE FUNCTION reject_research_mutation();
INSERT INTO schema_migrations (version) VALUES (1);
