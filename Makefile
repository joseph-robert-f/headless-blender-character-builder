# Headless Blender Character Builder
#
# `make help` lists everything. The demo needs Blender and nothing else; there
# is no .env, no service stack, and no account to create.

SHELL := /bin/bash
PYTHON ?= python3
CLI := $(PYTHON) hbcb-cli
IMAGE ?= headless-blender-character-builder:dev
DEMO_DIR ?= build/demo
PRESET ?= facet-bot

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@echo "Headless Blender Character Builder"
	@echo
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "First time here?  make doctor  then  make demo"

.PHONY: doctor
doctor: ## Check that Blender and everything else needed is present
	@$(CLI) doctor

.PHONY: demo
demo: ## Build the bundled example into build/demo
	@$(CLI) build --preset $(PRESET) -o $(DEMO_DIR)

.PHONY: verify-demo
verify-demo: ## Re-check build/demo in a fresh Blender process
	@$(CLI) verify $(DEMO_DIR)

.PHONY: demo-fast
demo-fast: ## Build the example without renders (seconds instead of a minute)
	@$(CLI) build --preset $(PRESET) --no-renders -o $(DEMO_DIR)

.PHONY: presets
presets: ## List the bundled character presets
	@$(CLI) presets

.PHONY: profiles
profiles: ## List the printer profiles
	@$(CLI) profiles

.PHONY: test-unit
test-unit: ## Run the fast tests (no Blender required)
	@$(PYTHON) -m unittest discover -s tests/unit -t . -v

.PHONY: test-blender
test-blender: ## Run the geometry and artifact tests inside Blender
	@$(CLI) selftest

.PHONY: test
test: test-unit test-blender ## Run every test

.PHONY: lint
lint: ## Format and lint checks
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check . && ruff format --check .; \
	else \
		echo "ruff not installed; skipping (pip install ruff)"; \
		$(PYTHON) -m compileall -q hbcb blender tests; \
	fi

.PHONY: check
check: lint test ## Everything CI runs

.PHONY: docker-build
docker-build: ## Build the container image
	@docker build -f docker/builder.Dockerfile -t $(IMAGE) .

.PHONY: docker-demo
docker-demo: docker-build ## Build the example in a locked-down container
	@mkdir -p $(DEMO_DIR)
	@docker run --rm \
		--network none \
		--cap-drop ALL \
		--security-opt no-new-privileges:true \
		--pids-limit 512 \
		--memory 8g \
		--user "$$(id -u):$$(id -g)" \
		--tmpfs /tmp:rw,nosuid,nodev,size=2g \
		-v "$$PWD/$(DEMO_DIR):/output" \
		$(IMAGE) build --preset $(PRESET) -o /output

.PHONY: clean
clean: ## Remove build output
	@rm -rf build
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
