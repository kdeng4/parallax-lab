CREATE TABLE live_studies (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX live_studies_active ON live_studies (status, created_at DESC);
CREATE TABLE live_snapshots (
    id UUID PRIMARY KEY,
    study_id UUID NOT NULL REFERENCES live_studies(id),
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE live_points (
    id TEXT PRIMARY KEY,
    study_id UUID NOT NULL REFERENCES live_studies(id),
    timestamp TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX live_points_study ON live_points (study_id, timestamp);
CREATE TABLE live_events (
    id UUID PRIMARY KEY,
    study_id UUID NOT NULL REFERENCES live_studies(id),
    timestamp TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX live_events_study ON live_events (study_id, timestamp DESC);
CREATE TRIGGER live_snapshots_immutable BEFORE UPDATE OR DELETE ON live_snapshots
    FOR EACH ROW EXECUTE FUNCTION reject_research_mutation();
CREATE TRIGGER live_points_immutable BEFORE UPDATE OR DELETE ON live_points
    FOR EACH ROW EXECUTE FUNCTION reject_research_mutation();
CREATE TRIGGER live_events_immutable BEFORE UPDATE OR DELETE ON live_events
    FOR EACH ROW EXECUTE FUNCTION reject_research_mutation();
INSERT INTO schema_migrations (version) VALUES (3);
