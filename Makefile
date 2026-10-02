.DEFAULT_GOAL := help

BUILDER_IMAGE ?= headless-blender-character-builder:dev
TEST_IMAGE ?= $(BUILDER_IMAGE)-test
SERVICE_TEST_IMAGE ?= $(BUILDER_IMAGE)-service-test
WORKER_BOUNDARY_IMAGE ?= $(BUILDER_IMAGE)-worker-boundary-test
MINIO_IMAGE ?= hbcb-minio-local:final-community-20260212-hbcb.1
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

.PHONY: help image ensure-image test-image service-test-image worker-boundary-image worker-boundary-check minio-security-check postgres-security-check orphan-minio-check validate build verify inspect demo verify-demo demo-native verify-demo-native _validate-output-name init-env service-client service-up service-smoke service-down service-config service-ps service-logs service-images service-image-cleanup g8-static g8-caddy g8-recovery g8-gate operator-smoke lint test-unit test-blender dependency-check dependency-audit dependency-scan security-check release-static release-check check docs-check

help:
	@echo "Headless Blender Character Builder"
	@echo "  make validate      Do the REQUEST checks. Do not start Blender."
	@echo "  make build         Build REQUEST in build/OUTPUT_NAME."
	@echo "  make verify        Open build/OUTPUT_NAME again and do its verification checks."
	@echo "  make inspect       Show the permitted data from build/OUTPUT_NAME/manifest.json."
	@echo "  make demo          Build the Docker demo. Credentials are not necessary."
	@echo "  make verify-demo   Open the published artifacts again and do their verification checks."
	@echo "  make init-env      Make local-service credentials in ignored files."
	@echo "  make service-client Send REQUEST and save one service result after verification."
	@echo "  make service-config Do the local service configuration checks."
	@echo "  make service-up    Start the local asynchronous Compose service."
	@echo "  make service-ps    Show the local service status for this checkout."
	@echo "  make service-logs  Show API and worker diagnostic logs with output limits."
	@echo "  make service-images Show the image tags for the selected service project."
	@echo "  make service-image-cleanup Remove only those image tags. Keep volumes and cache data."
	@echo "  make service-smoke Do the maintainer service integration gate checks."
	@echo "  make orphan-minio-check Do the orphan cleanup test in disposable storage."
	@echo "  make service-down  Stop services. Keep durable volumes."
	@echo "  make g8-gate       Do the VPS configuration checks and the local recovery drill."
	@echo "  make operator-smoke Do the test on a public HTTPS target only with permission."
	@echo "  make test-unit     Do unit, contract, and security tests in Docker."
	@echo "  make worker-boundary-check Do the child credential isolation test in the worker image."
	@echo "  make minio-security-check Do local storage fixture identity checks. Make sure that the specified authentication features are disabled."
	@echo "  make postgres-security-check Do the new-volume startup test at UID 70 without gosu."
	@echo "  make test-blender  Do Blender integration gate checks in Docker."
	@echo "  make dependency-check Do the dependency pin checks without a network connection."
	@echo "  make dependency-audit Show upstream version and tag status. Do not change data."
	@echo "  make dependency-scan Build all release images and do their vulnerability scans."
	@echo "  make security-check Do the publication and security audit without a network connection."
	@echo "  make release-static Do the audit of indexed source, policies, SBOM inputs, documentation, and CI."
	@echo "  make release-check Do the complete release gate checks from a clean indexed export."
	@echo "  make check         Do static, unit, security, and Blender tests."
	@echo "  make docs-check    Examine documentation language and coverage"
	@echo "  make demo-native BLENDER=/absolute/path/to/blender"

docs-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) ./scripts/check-documentation-language
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/documentation -v

image:
	$(DOCKER) build --file docker/builder.Dockerfile --target builder --build-arg "HBCB_DISTRIBUTION_VERSION=$${HBCB_DISTRIBUTION_VERSION:-0.1.0-local}" --build-arg "HBCB_SOURCE_REVISION=$${HBCB_SOURCE_REVISION:-uncommitted}" --tag "$(BUILDER_IMAGE)" --platform "$(PLATFORM)" .

ensure-image:
	@if image_platform=`$(DOCKER) image inspect --format '{{.Os}}/{{.Architecture}}' "$(BUILDER_IMAGE)" 2>/dev/null` && \
	  test "$$image_platform" = "$(PLATFORM)"; then \
	  :; \
	else \
	  $(MAKE) image; \
	fi

test-image:
	$(DOCKER) build --file docker/builder.Dockerfile --target test --build-arg "HBCB_DISTRIBUTION_VERSION=$${HBCB_DISTRIBUTION_VERSION:-0.1.0-local}" --build-arg "HBCB_SOURCE_REVISION=$${HBCB_SOURCE_REVISION:-uncommitted}" --tag "$(TEST_IMAGE)" --platform "$(PLATFORM)" .

service-test-image: image
	$(DOCKER) build --file docker/service.Dockerfile --target service-test --build-arg "HBCB_BUILDER_IMAGE=$(BUILDER_IMAGE)" --build-arg "HBCB_DISTRIBUTION_VERSION=$${HBCB_DISTRIBUTION_VERSION:-0.1.0-local}" --build-arg "HBCB_SOURCE_REVISION=$${HBCB_SOURCE_REVISION:-uncommitted}" --tag "$(SERVICE_TEST_IMAGE)" --platform "$(PLATFORM)" .

worker-boundary-image: image
	$(DOCKER) build --file docker/service.Dockerfile --target worker --build-arg "HBCB_BUILDER_IMAGE=$(BUILDER_IMAGE)" --build-arg "HBCB_DISTRIBUTION_VERSION=$${HBCB_DISTRIBUTION_VERSION:-0.1.0-local}" --build-arg "HBCB_SOURCE_REVISION=$${HBCB_SOURCE_REVISION:-uncommitted}" --tag "$(WORKER_BOUNDARY_IMAGE)" --platform "$(PLATFORM)" .

worker-boundary-check: worker-boundary-image
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
	  --memory 1g \
	  --user 65532:65532 \
	  --tmpfs /work:rw,nosuid,nodev,noexec,size=256m,mode=0700,uid=65532,gid=65532 \
	  --mount "type=bind,source=$(CURDIR)/tests/security/worker_process_boundary_gate.py,target=/opt/hbcb/worker-process-boundary-gate.py,readonly" \
	  --env HBCB_BOUNDARY_TEST_CANARY=hbcb-boundary-synthetic-canary \
	  --entrypoint /opt/blender/4.5/python/bin/python3.11 \
	  "$(WORKER_BOUNDARY_IMAGE)" \
	  /opt/hbcb/worker-process-boundary-gate.py

minio-security-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/security/minio_fixture_gate.py --docker "$(DOCKER)" --image "$(MINIO_IMAGE)"

postgres-security-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/security/postgres_fixture_gate.py --docker "$(DOCKER)"

# Keep recursive Make here so overrides, jobserver flags, and Make 3.81 work.
validate build inspect:
	@set -eu; \
	  ./scripts/builder-container preflight $@; \
	  $(MAKE) image; \
	  ./scripts/builder-container run $@ "$(PLATFORM)" "$(BUILDER_IMAGE)" $(DOCKER)

build verify inspect: _validate-output-name

_validate-output-name:
	@./scripts/builder-container check-output-name

verify:
	@set -eu; \
	  ./scripts/builder-container preflight $@; \
	  ./scripts/builder-container run $@ "$(PLATFORM)" "$(BUILDER_IMAGE)" $(DOCKER)

demo verify-demo: override OUTPUT_NAME := demo

demo: build

verify-demo: verify

demo-native:
	@set -eu; \
	  if ! test -f "$(REQUEST)"; then \
	    echo "HBCB_MAKE: FAIL[request_missing]: Set REQUEST to a regular JSON file that is available." >&2; \
	    exit 2; \
	  fi; \
	  if test -e "$(DEMO_OUTPUT)" || test -L "$(DEMO_OUTPUT)"; then \
	    echo "HBCB_MAKE: FAIL[output_exists]: There is output in build/demo. Move that output to a different location." >&2; \
	    exit 2; \
	  fi; \
	  mkdir -p "$(BUILD_PARENT)"; \
	  HBCB_BLENDER_BINARY="$(BLENDER)" "$(PYTHON)" -m builder_cli \
	    build --request "$(REQUEST)" --output "$(DEMO_OUTPUT)"

verify-demo-native:
	@set -eu; \
	  if ! test -f "$(REQUEST)"; then \
	    echo "HBCB_MAKE: FAIL[request_missing]: Set REQUEST to a regular JSON file that is available." >&2; \
	    exit 2; \
	  fi; \
	  if test -L "$(DEMO_OUTPUT)" || ! test -d "$(DEMO_OUTPUT)"; then \
	    echo "HBCB_MAKE: FAIL[output_missing]: The build/demo folder is not available or is a symlink. Run make demo-native first." >&2; \
	    exit 2; \
	  fi; \
	  HBCB_BLENDER_BINARY="$(BLENDER)" "$(PYTHON)" -m builder_cli \
	    verify --request "$(REQUEST)" --output "$(DEMO_OUTPUT)"

init-env:
	./scripts/init-env

service-client:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) ./scripts/service-client --request "$(REQUEST)"

service-up:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose up

service-smoke:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-smoke

orphan-minio-check:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" ./scripts/orphan-minio-gate

service-down:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose down

service-config:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose config

service-ps:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose ps

service-logs:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose logs

service-images:
	DOCKER="$(DOCKER)" ./scripts/service-images list

service-image-cleanup:
	DOCKER="$(DOCKER)" ./scripts/service-images remove

g8-static:
	env -u HBCB_COMPOSE_BIN DOCKER="$(DOCKER)" PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/deployment -p 'test_*.py' -v
	DOCKER="$(DOCKER)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/deployment/g8_static_gate.py

g8-caddy:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/deployment/g8_caddy_gate.py --docker "$(DOCKER)"

g8-recovery:
	@set -eu; \
	  . ./scripts/service-common; \
	  hbcb_service_settings; \
	  builder_image="$(BUILDER_IMAGE)"; \
	  if test "$$builder_image" = headless-blender-character-builder:dev; then \
	    builder_image="$$HBCB_BUILDER_PROJECT_IMAGE"; \
	  fi; \
	  DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" \
	    HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)" \
	    BUILDER_IMAGE="$$builder_image" \
	    COMPOSE_PROJECT_NAME="$$COMPOSE_PROJECT_NAME" \
	    HBCB_POSTGRES_IMAGE="$$HBCB_POSTGRES_IMAGE" \
	    HBCB_SERVICE_API_IMAGE="$$HBCB_SERVICE_API_IMAGE" \
	    HBCB_MINIO_IMAGE="$$HBCB_MINIO_IMAGE" \
	    ./scripts/g8-recovery-drill

g8-gate:
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-compose up
	DOCKER="$(DOCKER)" PYTHON="$(PYTHON)" BUILDER_IMAGE="$(BUILDER_IMAGE)" ./scripts/service-smoke
	$(MAKE) g8-static PYTHON="$(PYTHON)" DOCKER="$(DOCKER)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)"
	$(MAKE) g8-caddy PYTHON="$(PYTHON)" DOCKER="$(DOCKER)"
	$(MAKE) g8-recovery PYTHON="$(PYTHON)" DOCKER="$(DOCKER)" BUILDER_IMAGE="$(BUILDER_IMAGE)" HBCB_COMPOSE_BIN="$(HBCB_COMPOSE_BIN)"

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

check: dependency-check lint test-unit worker-boundary-check test-blender
