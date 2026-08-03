-- Durable maintenance state intentionally has no foreign key to hbcb.builds.
-- Exact object-version evidence must survive deletion of the authoritative
-- build row so object cleanup can be retried safely after a process outage.
CREATE TABLE hbcb.artifact_deletion_queue (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    namespace varchar(32) NOT NULL,
    build_id uuid NOT NULL,
    bucket varchar(63) NOT NULL,
    object_key varchar(1024) NOT NULL,
    version_id varchar(256) NOT NULL,
    sha256 char(64) NOT NULL,
    bytes bigint NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending',
    attempt_count bigint NOT NULL DEFAULT 0,
    queued_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claim_token uuid,
    lease_expires_at timestamptz,
    completed_at timestamptz,
    last_error_code varchar(64),
    UNIQUE (namespace, bucket, object_key, version_id),
    CONSTRAINT deletion_queue_namespace_check CHECK (
        namespace ~ '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'
    ),
    CONSTRAINT deletion_queue_bucket_check CHECK (
        bucket ~ '^[a-z0-9]([a-z0-9.-]{1,61}[a-z0-9])$' AND
        position('..' IN bucket) = 0
    ),
    CONSTRAINT deletion_queue_object_key_check CHECK (
        length(object_key) BETWEEN 1 AND 1024 AND
        object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' AND
        position('..' IN object_key) = 0 AND
        position(chr(92) IN object_key) = 0
    ),
    CONSTRAINT deletion_queue_version_check CHECK (
        length(version_id) BETWEEN 1 AND 256 AND version_id ~ '^[!-~]+$'
    ),
    CONSTRAINT deletion_queue_sha_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT deletion_queue_bytes_check CHECK (bytes BETWEEN 1 AND 2147483648),
    CONSTRAINT deletion_queue_status_check CHECK (
        status IN ('pending', 'deleting', 'deleted', 'failed')
    ),
    CONSTRAINT deletion_queue_attempt_count_check CHECK (
        attempt_count BETWEEN 0 AND 1000000
    ),
    CONSTRAINT deletion_queue_error_check CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'
    ),
    CONSTRAINT deletion_queue_state_check CHECK (
        (
            status = 'pending' AND claim_token IS NULL AND
            lease_expires_at IS NULL AND completed_at IS NULL AND
            last_error_code IS NULL
        ) OR (
            status = 'deleting' AND claim_token IS NOT NULL AND
            lease_expires_at IS NOT NULL AND completed_at IS NULL AND
            last_error_code IS NULL
        ) OR (
            status = 'deleted' AND claim_token IS NULL AND
            lease_expires_at IS NULL AND completed_at IS NOT NULL AND
            last_error_code IS NULL
        ) OR (
            status = 'failed' AND claim_token IS NULL AND
            lease_expires_at IS NULL AND completed_at IS NULL AND
            last_error_code IS NOT NULL
        )
    )
);

CREATE INDEX deletion_queue_ready_idx
    ON hbcb.artifact_deletion_queue (queued_at, id)
    WHERE status IN ('pending', 'failed');
CREATE INDEX deletion_queue_expired_claim_idx
    ON hbcb.artifact_deletion_queue (lease_expires_at, id)
    WHERE status = 'deleting';
CREATE INDEX deletion_queue_build_idx
    ON hbcb.artifact_deletion_queue (namespace, build_id);

CREATE TABLE hbcb.artifact_deletion_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    deletion_id bigint NOT NULL,
    attempt_number bigint NOT NULL,
    worker_id varchar(128) NOT NULL,
    claim_token uuid NOT NULL,
    outcome varchar(16) NOT NULL,
    error_code varchar(64),
    attempted_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (deletion_id, attempt_number),
    CONSTRAINT deletion_attempt_queue_fk FOREIGN KEY (deletion_id)
        REFERENCES hbcb.artifact_deletion_queue (id) ON DELETE RESTRICT,
    CONSTRAINT deletion_attempt_number_check CHECK (
        attempt_number BETWEEN 1 AND 1000000
    ),
    CONSTRAINT deletion_attempt_worker_check CHECK (
        worker_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CONSTRAINT deletion_attempt_outcome_check CHECK (
        outcome IN ('deleted', 'failed')
    ),
    CONSTRAINT deletion_attempt_error_check CHECK (
        (outcome = 'deleted' AND error_code IS NULL) OR
        (outcome = 'failed' AND error_code ~ '^[a-z][a-z0-9_]{0,63}$')
    )
);

CREATE INDEX deletion_attempt_queue_idx
    ON hbcb.artifact_deletion_attempts (deletion_id, attempted_at);

-- Restore operations produce new S3 version IDs even when bytes are identical.
-- This append-only audit row records the exact evidence used to replace the
-- restored hbcb.artifacts.version_id value.
CREATE TABLE hbcb.artifact_restore_remaps (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    namespace varchar(32) NOT NULL,
    build_id uuid NOT NULL,
    bucket varchar(63) NOT NULL,
    object_key varchar(1024) NOT NULL,
    source_version_id varchar(256) NOT NULL,
    restored_version_id varchar(256) NOT NULL,
    sha256 char(64) NOT NULL,
    bytes bigint NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (namespace, bucket, object_key, source_version_id, restored_version_id),
    CONSTRAINT restore_remap_namespace_check CHECK (
        namespace ~ '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'
    ),
    CONSTRAINT restore_remap_bucket_check CHECK (
        bucket ~ '^[a-z0-9]([a-z0-9.-]{1,61}[a-z0-9])$' AND
        position('..' IN bucket) = 0
    ),
    CONSTRAINT restore_remap_object_key_check CHECK (
        length(object_key) BETWEEN 1 AND 1024 AND
        object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' AND
        position('..' IN object_key) = 0 AND
        position(chr(92) IN object_key) = 0
    ),
    CONSTRAINT restore_remap_source_version_check CHECK (
        length(source_version_id) BETWEEN 1 AND 256 AND source_version_id ~ '^[!-~]+$'
    ),
    CONSTRAINT restore_remap_restored_version_check CHECK (
        length(restored_version_id) BETWEEN 1 AND 256 AND restored_version_id ~ '^[!-~]+$'
    ),
    CONSTRAINT restore_remap_distinct_version_check CHECK (
        source_version_id <> restored_version_id
    ),
    CONSTRAINT restore_remap_sha_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT restore_remap_bytes_check CHECK (bytes BETWEEN 1 AND 2147483648)
);

CREATE INDEX restore_remap_build_idx
    ON hbcb.artifact_restore_remaps (namespace, build_id, recorded_at);
