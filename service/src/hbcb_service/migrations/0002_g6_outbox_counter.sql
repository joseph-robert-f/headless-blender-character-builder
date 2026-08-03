-- Keep prolonged Redis outages recoverable.  The G5 smallint/check pair made
-- the 101st dispatch transition fail, including a later successful enqueue.
ALTER TABLE hbcb.queue_outbox
    DROP CONSTRAINT outbox_dispatch_count_check;

ALTER TABLE hbcb.queue_outbox
    ALTER COLUMN dispatch_count TYPE bigint;

ALTER TABLE hbcb.queue_outbox
    ADD CONSTRAINT outbox_dispatch_count_check CHECK (dispatch_count >= 0);
