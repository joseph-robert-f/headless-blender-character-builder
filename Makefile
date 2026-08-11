.DEFAULT_GOAL := help

BUILDER_IMAGE ?= headless-blender-character-builder:dev
TEST_IMAGE ?= $(BUILDER_IMAGE)-test
SERVICE_TEST_IMAGE ?= $(BUILDER_IMAGE)-service-test
DOCKER ?= docker
PLATFORM ?= linux/amd64
PYTHON ?= python3
BLENDER ?= blender
VERSION ?= $(shell sed -n '1p' VERSION)
RELEASE_VERSION ?= $(VERSION)-rc.1
DEPENDENCY_OUTPUT ?= $(CURDIR)/build/dependency-audit

REQUEST := $(CURDIR)/examples/requests/facet-bot.json
BUILD_PARENT := $(CURDIR)/build
OUTPUT_NAME ?= demo
DEMO_OUTPUT := $(BUILD_PARENT)/demo
export REQUEST BUILD_PARENT OUTPUT_NAME

.PHONY: help image ensure-image test-image service-test-image validate build verify demo verify-demo demo-native verify-demo-native _validate-output-name init-env service-up service-smoke service-down service-config g8-static g8-caddy g8-recovery g8-gate operator-smoke lint test-unit test-blender dependency-check dependency-audit dependency-scan security-check release-static release-check check

help:
	@echo "Headless Blender Character Builder"
	@echo "  make validate      Validate REQUEST without starting Blender"
	@echo "  make build         Build REQUEST under build/OUTPUT_NAME"
	@echo "  make verify        Reopen and verify build/OUTPUT_NAME"
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
	@echo "  make dependency-check Validate synchronized dependency pins offline"
	@echo "  make dependency-audit Report upstream version/tag status without mutation"
	@echo "  make dependency-scan Build and vulnerability-scan all release images"
	@echo "  make security-check Run the offline publication/security audit"
	@echo "  make release-static Audit indexed source, policies, SBOM inputs, docs, and CI"
	@echo "  make release-check Run the complete release gate from a clean indexed export"
	@echo "  make check         Run static, unit, security, and Blender tests"
	@echo "  make demo-native BLENDER=/absolute/path/to/blender"

image:
	$(DOCKER) build --file docker/builder.Dockerfile --target builder --tag "$(BUILDER_IMAGE)" --platform "$(PLATFORM)" .

ensure-image:
	@if image_platform=`$(DOCKER) image inspect --format '{{.Os}}/{{.Architecture}}' "$(BUILDER_IMAGE)" 2>/dev/null` && \
	  test "$$image_platform" = "$(PLATFORM)"; then \
	  :; \
	else \
	  $(MAKE) image; \
	fi

test-image:
	$(DOCKER) build --file docker/builder.Dockerfile --target test --tag "$(TEST_IMAGE)" --platform "$(PLATFORM)" .

service-test-image: image
	$(DOCKER) build --file docker/service.Dockerfile --target service-test --build-arg "HBCB_BUILDER_IMAGE=$(BUILDER_IMAGE)" --tag "$(SERVICE_TEST_IMAGE)" --platform "$(PLATFORM)" .

validate: ensure-image
	@set -eu; \
	  request=$$REQUEST; \
	  test -f "$$request"; \
	  runtime_uid=`id -u`; runtime_gid=`id -g`; \
	  if test "$$runtime_uid" = 0; then runtime_uid=65532; fi; \
	  if test "$$runtime_gid" = 0; then runtime_gid=65532; fi; \
	  $(DOCKER) run \
	    --rm \
	    --init \
	    --platform "$(PLATFORM)" \
	    --network none \
	    --read-only \
	    --cap-drop ALL \
	    --security-opt no-new-privileges:true \
	    --pids-limit 64 \
	    --cpus 1 \
	    --memory 512m \
	    --user "$$runtime_uid:$$runtime_gid" \
	    --tmpfs /work:rw,nosuid,nodev,noexec,size=64m,mode=1777 \
	    --mount "type=bind,source=$$request,target=/input/request.json,readonly" \
	    "$(BUILDER_IMAGE)" \
	    validate --request /input/request.json

_validate-output-name:
	@set -eu; \
	  LC_ALL=C; export LC_ALL; \
	  output_name=$${OUTPUT_NAME-}; \
	  case "$$output_name" in \
	    ''|-*|*-|*--*|*[!a-z0-9-]*) \
	      echo "OUTPUT_NAME must be a 1-48 character lowercase safe slug" >&2; \
	      exit 2 \
	      ;; \
	  esac; \
	  if test "$${#output_name}" -gt 48; then \
	    echo "OUTPUT_NAME must be a 1-48 character lowercase safe slug" >&2; \
	    exit 2; \
	  fi

build: _validate-output-name
	@set -eu; \
	  request=$$REQUEST; output_parent=$$BUILD_PARENT; output_name=$$OUTPUT_NAME; \
	  output_path=$$output_parent/$$output_name; \
	  test -f "$$request"; \
	  test ! -e "$$output_path"; \
	  $(MAKE) image; \
	  mkdir -p "$$output_parent"; \
	  host_uid=`id -u`; runtime_uid=$$host_uid; runtime_gid=`id -g`; \
	  if test "$$runtime_uid" = 0; then runtime_uid=65532; fi; \
	  if test "$$runtime_gid" = 0; then runtime_gid=65532; fi; \
	  if test "$$host_uid" = 0; then chown "$$runtime_uid:$$runtime_gid" "$$output_parent"; fi; \
	  image_metadata=`$(DOCKER) image inspect --format '{{.Os}}/{{.Architecture}}|{{.Id}}' "$(BUILDER_IMAGE)"`; \
	  image_platform=$${image_metadata%%|*}; image_id=$${image_metadata#*|}; \
	  test "$$image_platform" = "$(PLATFORM)"; \
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
	    --mount "type=bind,source=$$request,target=/input/request.json,readonly" \
	    --mount "type=bind,source=$$output_parent,target=/output" \
	    --env HBCB_EXECUTION_MODE=container \
	    --env "HBCB_WORKER_IMAGE_REFERENCE=$(BUILDER_IMAGE)" \
	    --env "HBCB_WORKER_IMAGE_ID=$$image_id" \
	    "$(BUILDER_IMAGE)" \
	    build --request /input/request.json --output "/output/$$output_name"

verify: _validate-output-name
	@set -eu; \
	  request=$$REQUEST; output_parent=$$BUILD_PARENT; output_name=$$OUTPUT_NAME; \
	  output_path=$$output_parent/$$output_name; \
	  test -f "$$request"; \
	  test -d "$$output_path"; \
	  runtime_uid=`id -u`; runtime_gid=`id -g`; \
	  if test "$$runtime_uid" = 0; then runtime_uid=65532; fi; \
	  if test "$$runtime_gid" = 0; then runtime_gid=65532; fi; \
	  image_metadata=`$(DOCKER) image inspect --format '{{.Os}}/{{.Architecture}}|{{.Id}}' "$(BUILDER_IMAGE)"`; \
	  image_platform=$${image_metadata%%|*}; image_id=$${image_metadata#*|}; \
	  test "$$image_platform" = "$(PLATFORM)"; \
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
	    --mount "type=bind,source=$$request,target=/input/request.json,readonly" \
	    --mount "type=bind,source=$$output_parent,target=/output,readonly" \
	    --env HBCB_EXECUTION_MODE=container \
	    --env "HBCB_WORKER_IMAGE_REFERENCE=$(BUILDER_IMAGE)" \
	    --env "HBCB_WORKER_IMAGE_ID=$$image_id" \
	    "$(BUILDER_IMAGE)" \
	    verify --request /input/request.json --output "/output/$$output_name"

demo verify-demo: override OUTPUT_NAME := demo

demo: build

verify-demo: verify

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
	env -u HBCB_COMPOSE_BIN PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/deployment -p 'test_*.py' -v
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
	@if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
	  git diff --check; \
	elif test "$(HBCB_INDEX_AUDITED)" = 1; then \
	  echo "INDEXED_DIFF_CHECK: PASS (verified before checkout-index export)"; \
	else \
	  echo "LINT: Git metadata is absent and HBCB_INDEX_AUDITED is not set" >&2; \
	  exit 1; \
	fi
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 2 --memory 2g --tmpfs /work:rw,nosuid,nodev,noexec,size=512m,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -c 'import ast,pathlib; files=sorted(pathlib.Path("blender").rglob("*.py"))+sorted(pathlib.Path("builder_cli").rglob("*.py"))+sorted(pathlib.Path("shared").rglob("*.py"))+sorted(pathlib.Path("tests").rglob("*.py")); [ast.parse(path.read_bytes(), filename=str(path)) for path in files]; print("AST_CHECK: PASS (%d files)" % len(files))'

test-unit: test-image service-test-image
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -m unittest discover -s tests/unit -p 'test_*.py' -v
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -m unittest discover -s tests/contract -p 'test_*.py' -v
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -m unittest discover -s tests/container -p 'test_*.py' -v
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" -m unittest discover -s tests/security -p 'test_*.py' -v
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --user 65532:65532 --tmpfs /work:rw,nosuid,nodev,noexec,size=512m,mode=1777 --tmpfs /test-exec:rw,nosuid,nodev,exec,size=512m,mode=0700,uid=65532,gid=65532 --env HOME=/work --env TMPDIR=/test-exec "$(SERVICE_TEST_IMAGE)" -m unittest discover -s tests/service_unit -p 'test_*.py' -v

test-blender: test-image
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" tests/blender_integration/g2_gate.py --blender /opt/blender/blender --evidence-dir /work/g2 --timeout-seconds 900
	$(DOCKER) run --rm --init --platform "$(PLATFORM)" --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --cpus 4 --memory 4g --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 --env HOME=/work --env TMPDIR=/work "$(TEST_IMAGE)" tests/blender_integration/g3_gate.py --blender /opt/blender/blender --work-dir /work/g3 --timeout-seconds 1800

dependency-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) ./scripts/dependency-audit

dependency-audit:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) ./scripts/dependency-audit --online

dependency-scan:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) ./scripts/dependency-scan --output "$(DEPENDENCY_OUTPUT)" --images

release-static:
	PYTHON="$(PYTHON)" DOCKER="$(DOCKER)" HBCB_RELEASE_VERSION="$(RELEASE_VERSION)" ./scripts/release-check --static

security-check: release-static

release-check:
	PYTHON="$(PYTHON)" DOCKER="$(DOCKER)" HBCB_RELEASE_VERSION="$(RELEASE_VERSION)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)" ./scripts/release-check

check: dependency-check lint test-unit test-blender
