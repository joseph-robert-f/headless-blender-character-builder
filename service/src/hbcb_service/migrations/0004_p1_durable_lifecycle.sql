-- Record why exact-version deletion evidence exists.  Orphan discovery uses
-- the same durable queue as build retention, but additionally records the
-- immutable object's last-modified timestamp used for the grace decision.
ALTER TABLE hbcb.artifact_deletion_queue
    ADD COLUMN evidence_origin varchar(32) NOT NULL DEFAULT 'build_retention',
    ADD COLUMN object_last_modified timestamptz;

ALTER TABLE hbcb.artifact_deletion_queue
    ADD CONSTRAINT deletion_queue_evidence_origin_check CHECK (
        evidence_origin IN ('build_retention', 'orphan_inventory')
    ),
    ADD CONSTRAINT deletion_queue_object_time_check CHECK (
        (evidence_origin = 'build_retention' AND object_last_modified IS NULL) OR
        (evidence_origin = 'orphan_inventory' AND object_last_modified IS NOT NULL)
    );

CREATE INDEX deletion_queue_orphan_evidence_idx
    ON hbcb.artifact_deletion_queue (
        namespace, object_last_modified, id
    )
    WHERE evidence_origin = 'orphan_inventory';
