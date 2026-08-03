from __future__ import annotations

import json
import unittest

from hbcb_service.auth import authorize_bearer, validate_service_token
from hbcb_service.config import SecretValue, ServiceConfig
from hbcb_service.errors import AuthorizationError, ConfigurationError, IdempotencyConflict, ServiceError
from hbcb_service.idempotency import (
    RequestFingerprint,
    digest_idempotency_key,
    require_same_request,
    validate_idempotency_key,
)

try:
    from .support import facet_request_bytes, valid_environment
except ImportError:  # Direct ``unittest -s tests/service_unit`` discovery.
    from support import facet_request_bytes, valid_environment


class ConfigurationTests(unittest.TestCase):
    def test_valid_config_is_bounded_and_redacted(self) -> None:
        environment = valid_environment()
        config = ServiceConfig.from_environment(environment)
        self.assertEqual(config.deployment_namespace, "local")
        self.assertEqual(config.signed_url_ttl_seconds, 300)
        rendered = repr(config) + repr(config.redacted()) + str(config.api_token)
        for secret_name in (
            "HBCB_API_TOKEN",
            "HBCB_IDEMPOTENCY_SECRET",
            "HBCB_DATABASE_URL",
            "HBCB_REDIS_URL",
            "HBCB_STORAGE_SECRET_KEY",
        ):
            self.assertNotIn(environment[secret_name], rendered)
        self.assertEqual(config.api_token.reveal(), environment["HBCB_API_TOKEN"])

    def test_missing_placeholder_and_malformed_settings_fail_closed(self) -> None:
        cases = (
            ("HBCB_API_TOKEN", "replace-me"),
            ("HBCB_DEPLOYMENT_NAMESPACE", "../escape"),
            ("HBCB_DATABASE_URL", "https://postgres.invalid/db"),
            ("HBCB_DATABASE_URL", "postgresql://postgres:5432/hbcb"),
            ("HBCB_DATABASE_URL", "postgresql://user:password@postgres:5432/"),
            ("HBCB_REDIS_URL", "redis://redis:99999/0"),
            ("HBCB_REDIS_URL", "redis://redis:6379/0"),
            ("HBCB_REDIS_URL", "redis://:password@redis:6379/16"),
            ("HBCB_STORAGE_INTERNAL_ENDPOINT", "http://minio:9000"),
            ("HBCB_STORAGE_PUBLIC_ENDPOINT", "localhost:0"),
            ("HBCB_STORAGE_BUCKET", "Bad_Bucket"),
            ("HBCB_STORAGE_SECURE", "yes"),
            ("HBCB_SIGNED_URL_TTL_SECONDS", "901"),
        )
        for name, value in cases:
            with self.subTest(name=name):
                environment = valid_environment()
                environment[name] = value
                with self.assertRaises((ConfigurationError, AuthorizationError)):
                    ServiceConfig.from_environment(environment)
        environment = valid_environment()
        del environment["HBCB_REDIS_URL"]
        with self.assertRaises(ConfigurationError):
            ServiceConfig.from_environment(environment)

    def test_secret_value_never_renders_plaintext(self) -> None:
        secret = SecretValue("z" * 64)
        self.assertEqual(repr(secret), "SecretValue(<redacted>)")
        self.assertEqual(str(secret), "SecretValue(<redacted>)")
        self.assertNotIn("z" * 64, repr(secret))


class AuthorizationTests(unittest.TestCase):
    def test_exact_bearer_token_authorizes(self) -> None:
        token = "a" * 64
        self.assertIsNone(authorize_bearer("Bearer " + token, token))
        self.assertIsNone(authorize_bearer(("Bearer " + token).encode("ascii"), token))

    def test_missing_malformed_multiple_and_wrong_tokens_fail_without_echo(self) -> None:
        token = "a" * 64
        candidates = (
            None,
            "bearer " + token,
            "Bearer  " + token,
            "Bearer " + token + " extra",
            "Basic " + token,
            "Bearer " + ("b" * 64),
            b"Bearer \xff",
            "Bearer " + ("a" * 1025),
        )
        for candidate in candidates:
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaises(AuthorizationError) as captured:
                    authorize_bearer(candidate, token)
                rendered = str(captured.exception)
                self.assertNotIn(token, rendered)
                self.assertNotIn("b" * 64, rendered)

    def test_configured_token_policy_is_strict(self) -> None:
        for candidate in ("short", "a b" * 20, "é" * 64, "a" * 257):
            with self.assertRaises(AuthorizationError):
                validate_service_token(candidate)


class IdempotencyTests(unittest.TestCase):
    def test_key_is_bounded_visible_ascii_and_hmac_digest_is_stable(self) -> None:
        secret = b"s" * 32
        key = "request-1234"
        self.assertEqual(validate_idempotency_key(key), key.encode("ascii"))
        first = digest_idempotency_key(key, secret)
        second = digest_idempotency_key(key, secret)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, digest_idempotency_key(key, b"t" * 32))
        for invalid in ("a", "with space", "é" * 8, "a" * 129, "line\nbreak"):
            with self.assertRaises(ServiceError):
                validate_idempotency_key(invalid)

    def test_fingerprint_uses_normalized_canonical_request(self) -> None:
        original = json.loads(facet_request_bytes())
        reordered = {
            "quality_profile": original["quality_profile"],
            "render_profile": original["render_profile"],
            "output_profile": original["output_profile"],
            "spec": original["spec"],
            "generator": original["generator"],
            "request_version": original["request_version"],
        }
        first = RequestFingerprint.from_request(facet_request_bytes())
        second = RequestFingerprint.from_request(json.dumps(reordered).encode("utf-8"))
        self.assertEqual(first, second)
        with self.assertRaises(ServiceError):
            RequestFingerprint(
                request_sha256=first.request_sha256,
                spec_sha256="f" * 64,
                canonical_request=first.canonical_request,
            )

    def test_conflicting_request_hash_raises_fixed_error(self) -> None:
        require_same_request("a" * 64, "a" * 64)
        with self.assertRaises(IdempotencyConflict) as captured:
            require_same_request("a" * 64, "b" * 64)
        self.assertEqual(captured.exception.code, "idempotency_conflict")
        self.assertNotIn("a" * 64, str(captured.exception))
