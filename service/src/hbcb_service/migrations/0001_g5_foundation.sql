CREATE SCHEMA IF NOT EXISTS hbcb;

CREATE TABLE hbcb.builds (
    id uuid PRIMARY KEY,
    namespace varchar(32) NOT NULL,
    request_canonical bytea NOT NULL,
    request_sha256 char(64) NOT NULL,
    spec_sha256 char(64) NOT NULL,
    status varchar(32) NOT NULL,
    state_version bigint NOT NULL DEFAULT 1,
    max_attempts smallint NOT NULL DEFAULT 2,
    cancel_requested_at timestamptz,
    terminal_code varchar(64),
    manifest_object_key varchar(1024),
    manifest_sha256 char(64),
    manifest_bytes bigint,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    finished_at timestamptz,
    published_at timestamptz,
    UNIQUE (namespace, id),
    CONSTRAINT builds_namespace_check CHECK (
        namespace ~ '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'
    ),
    CONSTRAINT builds_request_size_check CHECK (
        octet_length(request_canonical) BETWEEN 1 AND 65536
    ),
    CONSTRAINT builds_request_sha_check CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT builds_spec_sha_check CHECK (spec_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT builds_status_check CHECK (
        status IN (
            'validating', 'queued', 'running', 'geometry_qa', 'rendering',
            'succeeded', 'failed', 'canceled', 'needs_review'
        )
    ),
    CONSTRAINT builds_state_version_check CHECK (state_version >= 0),
    CONSTRAINT builds_max_attempts_check CHECK (max_attempts BETWEEN 1 AND 5),
    CONSTRAINT builds_terminal_code_check CHECK (
        terminal_code IS NULL OR terminal_code ~ '^[a-z][a-z0-9_]{0,63}$'
    ),
    CONSTRAINT builds_timestamp_order_check CHECK (updated_at >= created_at),
    CONSTRAINT builds_terminal_timestamp_check CHECK (
        (status IN ('succeeded', 'failed', 'canceled', 'needs_review')) =
        (finished_at IS NOT NULL)
    ),
    CONSTRAINT builds_terminal_code_state_check CHECK (
        (status = 'succeeded' AND terminal_code IS NULL) OR
        (status IN ('failed', 'canceled', 'needs_review') AND terminal_code IS NOT NULL) OR
        (status NOT IN ('succeeded', 'failed', 'canceled', 'needs_review') AND terminal_code IS NULL)
    ),
    CONSTRAINT builds_cancel_check CHECK (
        status <> 'canceled' OR cancel_requested_at IS NOT NULL
    ),
    CONSTRAINT builds_manifest_state_check CHECK (
        (
            status = 'succeeded' AND
            manifest_object_key IS NOT NULL AND
            manifest_sha256 IS NOT NULL AND
            manifest_sha256 ~ '^[0-9a-f]{64}$' AND
            manifest_bytes IS NOT NULL AND
            manifest_bytes BETWEEN 1 AND 2147483648 AND
            published_at IS NOT NULL
        ) OR (
            status <> 'succeeded' AND
            manifest_object_key IS NULL AND
            manifest_sha256 IS NULL AND
            manifest_bytes IS NULL AND
            published_at IS NULL
        )
    ),
    CONSTRAINT builds_manifest_key_check CHECK (
        manifest_object_key IS NULL OR (
            length(manifest_object_key) BETWEEN 1 AND 1024 AND
            manifest_object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' AND
            position('..' IN manifest_object_key) = 0 AND
            position(chr(92) IN manifest_object_key) = 0
        )
    )
);

CREATE INDEX builds_status_created_idx ON hbcb.builds (status, created_at);

CREATE TABLE hbcb.idempotency_keys (
    namespace varchar(32) NOT NULL,
    key_sha256 char(64) NOT NULL,
    request_sha256 char(64) NOT NULL,
    build_id uuid NOT NULL UNIQUE,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (namespace, key_sha256),
    CONSTRAINT idempotency_namespace_check CHECK (
        namespace ~ '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'
    ),
    CONSTRAINT idempotency_key_sha_check CHECK (key_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotency_request_sha_check CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotency_build_fk FOREIGN KEY (namespace, build_id)
        REFERENCES hbcb.builds (namespace, id) ON DELETE CASCADE
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE hbcb.build_attempts (
    id uuid PRIMARY KEY,
    build_id uuid NOT NULL,
    attempt_number smallint NOT NULL,
    status varchar(32) NOT NULL,
    worker_id varchar(128) NOT NULL,
    lease_token_sha256 char(64) NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    exit_code smallint,
    reason_code varchar(64),
    created_at timestamptz NOT NULL,
    UNIQUE (build_id, attempt_number),
    UNIQUE (build_id, id),
    CONSTRAINT attempts_build_fk FOREIGN KEY (build_id)
        REFERENCES hbcb.builds (id) ON DELETE CASCADE,
    CONSTRAINT attempts_number_check CHECK (attempt_number BETWEEN 1 AND 5),
    CONSTRAINT attempts_status_check CHECK (
        status IN (
            'leased', 'running', 'succeeded', 'failed', 'needs_review',
            'canceled', 'timed_out', 'lost'
        )
    ),
    CONSTRAINT attempts_worker_check CHECK (
        worker_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CONSTRAINT attempts_lease_sha_check CHECK (lease_token_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT attempts_exit_code_check CHECK (exit_code IS NULL OR exit_code BETWEEN 0 AND 255),
    CONSTRAINT attempts_reason_check CHECK (
        reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]{0,63}$'
    ),
    CONSTRAINT attempts_terminal_timestamp_check CHECK (
        (status IN ('succeeded', 'failed', 'needs_review', 'canceled', 'timed_out', 'lost')) =
        (finished_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX attempts_one_active_idx
    ON hbcb.build_attempts (build_id)
    WHERE status IN ('leased', 'running');
CREATE INDEX attempts_expired_lease_idx
    ON hbcb.build_attempts (lease_expires_at)
    WHERE status IN ('leased', 'running');

CREATE TABLE hbcb.build_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    build_id uuid NOT NULL,
    attempt_id uuid,
    sequence bigint NOT NULL,
    event_type varchar(64) NOT NULL,
    from_status varchar(32),
    to_status varchar(32) NOT NULL,
    reason_code varchar(64),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (build_id, sequence),
    CONSTRAINT events_build_fk FOREIGN KEY (build_id)
        REFERENCES hbcb.builds (id) ON DELETE CASCADE,
    CONSTRAINT events_attempt_owner_fk FOREIGN KEY (build_id, attempt_id)
        REFERENCES hbcb.build_attempts (build_id, id) ON DELETE CASCADE,
    CONSTRAINT events_type_check CHECK (event_type ~ '^[a-z][a-z0-9_]{0,63}$'),
    CONSTRAINT events_reason_check CHECK (
        reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]{0,63}$'
    ),
    CONSTRAINT events_status_check CHECK (
        (from_status IS NULL OR from_status IN (
            'validating', 'queued', 'running', 'geometry_qa', 'rendering',
            'succeeded', 'failed', 'canceled', 'needs_review'
        )) AND to_status IN (
            'validating', 'queued', 'running', 'geometry_qa', 'rendering',
            'succeeded', 'failed', 'canceled', 'needs_review'
        )
    ),
    CONSTRAINT events_details_check CHECK (
        jsonb_typeof(details) = 'object' AND octet_length(details::text) <= 4096
    )
);

CREATE INDEX events_build_sequence_idx ON hbcb.build_events (build_id, sequence);

CREATE TABLE hbcb.artifacts (
    build_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    relative_path varchar(64) NOT NULL,
    bucket varchar(63) NOT NULL,
    object_key varchar(1024) NOT NULL,
    sha256 char(64) NOT NULL,
    bytes bigint NOT NULL,
    content_type varchar(64) NOT NULL,
    etag varchar(256),
    version_id varchar(256) NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (build_id, relative_path),
    UNIQUE (bucket, object_key),
    CONSTRAINT artifacts_attempt_owner_fk FOREIGN KEY (build_id, attempt_id)
        REFERENCES hbcb.build_attempts (build_id, id) ON DELETE CASCADE,
    CONSTRAINT artifacts_path_check CHECK (
        relative_path IN (
            'model.blend', 'model.glb', 'model.stl', 'preview.png',
            'diagnostics/front.png', 'diagnostics/side.png', 'diagnostics/back.png',
            'qa.json', 'manifest.json'
        )
    ),
    CONSTRAINT artifacts_bucket_check CHECK (
        bucket ~ '^[a-z0-9]([a-z0-9.-]{1,61}[a-z0-9])$' AND position('..' IN bucket) = 0
    ),
    CONSTRAINT artifacts_object_key_check CHECK (
        length(object_key) BETWEEN 1 AND 1024 AND
        object_key ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$' AND
        position('..' IN object_key) = 0 AND
        position(chr(92) IN object_key) = 0
    ),
    CONSTRAINT artifacts_sha_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifacts_bytes_check CHECK (bytes BETWEEN 1 AND 2147483648),
    CONSTRAINT artifacts_storage_id_check CHECK (
        (etag IS NULL OR (
            length(etag) BETWEEN 1 AND 256 AND etag ~ '^[!-~]+$'
        )) AND
        length(version_id) BETWEEN 1 AND 256 AND version_id ~ '^[!-~]+$'
    ),
    CONSTRAINT artifacts_content_type_check CHECK (
        (relative_path = 'model.blend' AND content_type = 'application/x-blender') OR
        (relative_path = 'model.glb' AND content_type = 'model/gltf-binary') OR
        (relative_path = 'model.stl' AND content_type = 'model/stl') OR
        (relative_path IN (
            'preview.png', 'diagnostics/front.png',
            'diagnostics/side.png', 'diagnostics/back.png'
        ) AND content_type = 'image/png') OR
        (relative_path IN ('qa.json', 'manifest.json') AND content_type = 'application/json')
    )
);

CREATE TABLE hbcb.queue_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    build_id uuid NOT NULL,
    build_version bigint NOT NULL,
    available_at timestamptz NOT NULL,
    dispatched_at timestamptz,
    dispatch_count smallint NOT NULL DEFAULT 0,
    last_error_code varchar(64),
    created_at timestamptz NOT NULL,
    UNIQUE (build_id, build_version),
    CONSTRAINT outbox_build_fk FOREIGN KEY (build_id)
        REFERENCES hbcb.builds (id) ON DELETE CASCADE,
    CONSTRAINT outbox_version_check CHECK (build_version >= 0),
    CONSTRAINT outbox_dispatch_count_check CHECK (dispatch_count BETWEEN 0 AND 100),
    CONSTRAINT outbox_error_check CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,63}$'
    ),
    CONSTRAINT outbox_dispatch_state_check CHECK (
        dispatched_at IS NULL OR last_error_code IS NULL
    )
);

CREATE INDEX outbox_pending_idx
    ON hbcb.queue_outbox (available_at, id)
    WHERE dispatched_at IS NULL;
