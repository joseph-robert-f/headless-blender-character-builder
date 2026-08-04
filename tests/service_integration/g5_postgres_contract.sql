-- Negative and positive constraint probes for the G5 PostgreSQL schema.
-- The caller runs this in a transaction and rolls it back after the PASS row.

INSERT INTO hbcb.builds (
    id, namespace, request_canonical, request_sha256, spec_sha256, status,
    state_version, max_attempts, created_at, updated_at
) VALUES
    ('10000000-0000-4000-8000-000000000001', 'local', '\x7b7d', repeat('a', 64), repeat('b', 64), 'queued', 1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('10000000-0000-4000-8000-000000000002', 'local', '\x7b7d', repeat('c', 64), repeat('d', 64), 'queued', 1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

DO $contract$
BEGIN
    BEGIN
        INSERT INTO hbcb.builds (
            id, namespace, request_canonical, request_sha256, spec_sha256,
            status, state_version, max_attempts, manifest_object_key,
            manifest_sha256, manifest_bytes, created_at, updated_at,
            finished_at, published_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000011', 'local', '\x7b7d',
            repeat('a', 64), repeat('b', 64), 'succeeded', 2, 2,
            'local/v1/builds/10000000-0000-4000-8000-000000000011/attempts/20000000-0000-4000-8000-000000000011/complete-v1/manifest.json',
            NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'succeeded build accepted a NULL manifest hash';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO hbcb.builds (
            id, namespace, request_canonical, request_sha256, spec_sha256,
            status, state_version, max_attempts, manifest_object_key,
            manifest_sha256, manifest_bytes, created_at, updated_at,
            finished_at, published_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000012', 'local', '\x7b7d',
            repeat('a', 64), repeat('b', 64), 'succeeded', 2, 2,
            'local/v1/builds/10000000-0000-4000-8000-000000000012/attempts/20000000-0000-4000-8000-000000000012/complete-v1/manifest.json',
            repeat('e', 64), NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'succeeded build accepted a NULL manifest byte count';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO hbcb.builds (
            id, namespace, request_canonical, request_sha256, spec_sha256,
            status, state_version, max_attempts, terminal_code,
            created_at, updated_at, finished_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000013', 'local', '\x7b7d',
            repeat('a', 64), repeat('b', 64), 'failed', 2, 2, NULL,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'failed build accepted no terminal reason';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END
$contract$;

INSERT INTO hbcb.build_attempts (
    id, build_id, attempt_number, status, worker_id, lease_token_sha256,
    lease_expires_at, heartbeat_at, started_at, created_at
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    1, 'running', 'worker-1', repeat('a', 64),
    CURRENT_TIMESTAMP + interval '5 minutes', CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

DO $contract$
BEGIN
    BEGIN
        INSERT INTO hbcb.build_attempts (
            id, build_id, attempt_number, status, worker_id, lease_token_sha256,
            lease_expires_at, heartbeat_at, started_at, created_at
        ) VALUES (
            '20000000-0000-4000-8000-000000000002',
            '10000000-0000-4000-8000-000000000001',
            2, 'leased', 'worker-2', repeat('b', 64),
            CURRENT_TIMESTAMP + interval '5 minutes', CURRENT_TIMESTAMP,
            NULL, CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'build accepted a second active attempt';
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO hbcb.build_events (
            build_id, attempt_id, sequence, event_type, from_status,
            to_status, created_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000002',
            '20000000-0000-4000-8000-000000000001',
            1, 'running', 'queued', 'running', CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'event accepted an attempt owned by another build';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO hbcb.build_events (
            build_id, sequence, event_type, from_status, to_status, created_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000001',
            1, 'invalid_state_probe', 'queued', 'invented', CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'event accepted an invalid build status';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;

    BEGIN
        INSERT INTO hbcb.artifacts (
            build_id, attempt_id, relative_path, bucket, object_key, sha256,
            bytes, content_type, version_id, created_at
        ) VALUES (
            '10000000-0000-4000-8000-000000000001',
            '20000000-0000-4000-8000-000000000001',
            'model.stl', 'hbcb-artifacts',
            'local/v1/builds/10000000-0000-4000-8000-000000000001/attempts/20000000-0000-4000-8000-000000000001/complete-v1/model.stl',
            repeat('f', 64), 10, 'text/plain', 'version-1', CURRENT_TIMESTAMP
        );
        RAISE EXCEPTION 'artifact accepted a mismatched content type';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END
$contract$;

INSERT INTO hbcb.build_events (
    build_id, attempt_id, sequence, event_type, from_status, to_status, created_at
) VALUES (
    '10000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    1, 'running', 'queued', 'running', CURRENT_TIMESTAMP
);

SELECT 'G5_POSTGRES_CONTRACT: PASS' AS result;
