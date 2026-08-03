.DEFAULT_GOAL := help

BUILDER_IMAGE ?= headless-blender-character-builder:dev
TEST_IMAGE ?= $(BUILDER_IMAGE)-test
DOCKER ?= docker
PLATFORM ?= linux/amd64
PYTHON ?= python3
BLENDER ?= blender

REQUEST := $(CURDIR)/examples/requests/facet-bot.json
BUILD_PARENT := $(CURDIR)/build
DEMO_OUTPUT := $(BUILD_PARENT)/demo

.PHONY: help image ensure-image test-image demo verify-demo demo-native verify-demo-native init-env service-up service-smoke service-down service-config g8-static g8-caddy g8-recovery g8-gate operator-smoke lint test-unit test-blender check

help:
	@echo "Headless Blender Character Builder"
	@echo "  make demo          Build the keyless Docker demo"
	@echo "  make verify-demo   Reopen and verify the published artifacts"
	@echo "  make init-env      Generate ignored local-service credentials"
	@echo "  make service-up    Start the local asynchronous Compose service"
	@echo "  make service-smoke Exercise the service, restart, and artifacts end to end"
	@echo "  make service-down  Stop services while preserving durable volumes"
	@echo "  make g8-gate       Validate VPS config and run the local recovery drill"
	@echo "  make operator-smoke Conditionally test an authorized public HTTPS target"
	@echo "  make test-unit     Run unit/contract/security tests in Docker"
	@echo "  make test-blender  Run Blender integration gates in Docker"
	@echo "  make check         Run static, unit, security, and Blender tests"
	@echo "  make demo-native BLENDER=/absolute/path/to/blender"

image:
	$(DOCKER) build --file docker/builder.Dockerfile --target builder --tag "$(BUILDER_IMAGE)" --platform "$(PLATFORM)" .

ensure-image:
	@if ! $(DOCKER) image inspect --platform "$(PLATFORM)" "$(BUILDER_IMAGE)" >/dev/null 2>&1; then \
	  $(MAKE) image; \
	fi

test-image:
	$(DOCKER) build --file docker/builder.Dockerfile --target test --tag "$(TEST_IMAGE)" --platform "$(PLATFORM)" .

demo: image
	@set -eu; \
	  test -f "$(REQUEST)"; \
	  test ! -e "$(DEMO_OUTPUT)"; \
	  mkdir -p "$(BUILD_PARENT)"; \
	  host_uid=`id -u`; runtime_uid=$$host_uid; runtime_gid=`id -g`; \
	  if test "$$runtime_uid" = 0; then runtime_uid=65532; fi; \
	  if test "$$runtime_gid" = 0; then runtime_gid=65532; fi; \
	  if test "$$host_uid" = 0; then chown "$$runtime_uid:$$runtime_gid" "$(BUILD_PARENT)"; fi; \
	  image_id=`$(DOCKER) image inspect --platform "$(PLATFORM)" --format '{{.Id}}' "$(BUILDER_IMAGE)"`; \
	  $(DOCKER) run \
	    --rm \
	    --init \
	    --platform "$(PLATFORM)" \
	    --network none \
	    --read-only \
	    --cap-drop ALL \
	    --security-opt no-new-privileges:true \
	    --pids-limit 512 \
	    --cpus 4 \
	    --memory 4g \
	    --user "$$runtime_uid:$$runtime_gid" \
	    --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 \
	    --mount "type=bind,source=$(REQUEST),target=/input/request.json,readonly" \
	    --mount "type=bind,source=$(BUILD_PARENT),target=/output" \
	    --env HBCB_EXECUTION_MODE=container \
	    --env "HBCB_WORKER_IMAGE_REFERENCE=$(BUILDER_IMAGE)" \
	    --env "HBCB_WORKER_IMAGE_ID=$$image_id" \
	    "$(BUILDER_IMAGE)" \
	    build --request /input/request.json --output /output/demo

verify-demo:
	@set -eu; \
	  test -f "$(REQUEST)"; \
	  test -d "$(DEMO_OUTPUT)"; \
	  runtime_uid=`id -u`; runtime_gid=`id -g`; \
	  if test "$$runtime_uid" = 0; then runtime_uid=65532; fi; \
	  if test "$$runtime_gid" = 0; then runtime_gid=65532; fi; \
	  image_id=`$(DOCKER) image inspect --platform "$(PLATFORM)" --format '{{.Id}}' "$(BUILDER_IMAGE)"`; \
	  $(DOCKER) run \
	    --rm \
	    --init \
	    --platform "$(PLATFORM)" \
	    --network none \
	    --read-only \
	    --cap-drop ALL \
	    --security-opt no-new-privileges:true \
	    --pids-limit 512 \
	    --cpus 4 \
	    --memory 4g \
	    --user "$$runtime_uid:$$runtime_gid" \
	    --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 \
	    --mount "type=bind,source=$(REQUEST),target=/input/request.json,readonly" \
	    --mount "type=bind,source=$(BUILD_PARENT),target=/output,readonly" \
	    --env HBCB_EXECUTION_MODE=container \
	    --env "HBCB_WORKER_IMAGE_REFERENCE=$(BUILDER_IMAGE)" \
	    --env "HBCB_WORKER_IMAGE_ID=$$image_id" \
	    "$(BUILDER_IMAGE)" \
	    verify --request /input/request.json --output /output/demo

demo-native:
	@set -eu; \
	  test -f "$(REQUEST)"; \
	  test ! -e "$(DEMO_OUTPUT)"; \
	  mkdir -p "$(BUILD_PARENT)"; \
	  HBCB_BLENDER_BINARY="$(BLENDER)" "$(PYTHON)" -m builder_cli \
	    build --request "$(REQUEST)" --output "$(DEMO_OUTPUT)"

verify-demo-native:
	@set -eu; \
	  test -d "$(DEMO_OUTPUT)"; \
	  HBCB_BLENDER_BINARY="$(BLENDER)" "$(PYTHON)" -m builder_cli \
	    verify --request "$(REQUEST)" --output "$(DEMO_OUTPUT)"

init-env:
	./scripts/init-env

service-up: ensure-image
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose up

service-smoke:
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-smoke

service-down:
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose down

service-config: ensure-image
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose config

g8-static:
	PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/deployment -p 'test_*.py' -v
	HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/deployment/g8_static_gate.py

g8-caddy:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/deployment/g8_caddy_gate.py

g8-recovery:
	HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/g8-recovery-drill

g8-gate: ensure-image
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose up
	BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-smoke
	$(MAKE) g8-static PYTHON="$(PYTHON)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)"
	$(MAKE) g8-caddy PYTHON="$(PYTHON)"
	$(MAKE) g8-recovery BUILDER_IMAGE="$(BUILDER_IMAGE)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)"

operator-smoke:
	./scripts/operator-smoke

lint: test-image
	git diff --check
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 2 --memory 2g --tmpfs /work:rw,nosuid,nodev,noexec,size=512m,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -c 'import ast,pathlib; files=sorted(pathlib.Path("blender").rglob("*.py"))+sorted(pathlib.Path("builder_cli").rglob("*.py"))+sorted(pathlib.Path("shared").rglob("*.py"))+sorted(pathlib.Path("tests").rglob("*.py")); [ast.parse(path.read_bytes(), filename=str(path)) for path in files]; print("AST_CHECK: PASS (%d files)" % len(files))'

test-unit: test-image
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -m unittest discover -s tests -v

test-blender: test-image
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" tests/blender_integration/g2_gate.py --blender /opt/blender/blender --evidence-dir /work/g2 --timeout-seconds 900
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" tests/blender_integration/g3_gate.py --blender /opt/blender/blender --work-dir /work/g3 --timeout-seconds 1800

check: lint test-unit test-blender
