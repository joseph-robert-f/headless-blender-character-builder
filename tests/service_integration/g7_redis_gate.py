#!/usr/bin/env python3
"""Real Redis Streams stale-claim and dead-letter gate for G7."""

from __future__ import annotations

import json
import os
from uuid import uuid4

from hbcb_service.config import SecretValue
from hbcb_service.queue import RedisStreamsQueue, STALE_CLAIM_IDLE_MS
from hbcb_service.runtime import redis_client


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    value = os.environ.get("HBCB_REDIS_URL", "")
    client = redis_client(SecretValue(value))
    namespace = "g7-" + uuid4().hex[:16]
    queue = RedisStreamsQueue(client, namespace)
    build_id = uuid4()
    second_id = uuid4()
    try:
        require(client.ping() is True, "Redis ping failed")
        queue.initialize()
        queue.enqueue(build_id)
        original = queue.claim("crash-window", block_ms=0)
        require(original is not None and original.build_id == build_id, "initial claim failed")

        # XCLAIM's IDLE option sets the pending entry's observed idle time
        # without a 60-second sleep.  The production adapter must then recover
        # that exact PEL entry through XAUTOCLAIM for another consumer.
        claimed = client.xclaim(
            queue.stream,
            queue.group,
            "abandoned",
            min_idle_time=0,
            message_ids=[original.receipt],
            idle=STALE_CLAIM_IDLE_MS + 1000,
        )
        require(len(claimed) == 1, "could not seed a stale pending entry")
        recovered = queue.claim("recovery", block_ms=0)
        require(recovered is not None, "XAUTOCLAIM did not recover the stale entry")
        require(recovered.build_id == build_id, "reclaimed build ID changed")
        require(recovered.receipt == original.receipt, "reclaimed receipt changed")
        queue.acknowledge(recovered)

        queue.enqueue(second_id)
        second = queue.claim("dead-letter", block_ms=0)
        require(second is not None and second.build_id == second_id, "second claim failed")
        queue.dead_letter(second)
        dead = client.xrange(queue.dead_stream, min="-", max="+")
        require(len(dead) == 1, "dead-letter stream does not contain exactly one entry")
        fields = dead[0][1]
        require(set(fields) == {b"build_id"}, "Redis payload leaked fields beyond build_id")
        require(fields[b"build_id"].decode("ascii") == str(second_id), "dead build ID changed")
        pending = client.xpending(queue.stream, queue.group)
        require(int(pending["pending"]) == 0, "queue retains pending entries after settlement")
        info = client.info(section="server")
        print(
            json.dumps(
                {
                    "dead_letters": 1,
                    "gate": "G7_REDIS_GATE",
                    "payload_fields": ["build_id"],
                    "redis_version": str(info.get("redis_version", "unknown")),
                    "result": "PASS",
                    "stale_claim_idle_ms": STALE_CLAIM_IDLE_MS,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        client.delete(queue.stream, queue.dead_stream)
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
