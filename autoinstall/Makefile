.PHONY: autoinstall iso clean help

.DEFAULT_GOAL := help

BUILD_DIR ?= build

AUTOINSTALL_TEMPLATE ?= autoinstall.yaml.template
AUTOINSTALL_OUTPUT ?= $(BUILD_DIR)/autoinstall.yaml
ANSIBLE_SSH_PUBLIC_KEY_FILE ?=
INSTALL_PASSWORD_HASH_FILE ?=
LUKS_PASSWORD_FILE ?=

SOURCE_ISO ?=
OUTPUT_ISO ?= $(BUILD_DIR)/ubuntu-autoinstall.iso
VOLUME_ID ?= ubuntu-autoinstall

autoinstall: ## Render build/autoinstall.yaml from the template (needs INSTALL_PASSWORD_HASH, LUKS_PASSWORD)
	@AUTOINSTALL_TEMPLATE="$(AUTOINSTALL_TEMPLATE)" \
	AUTOINSTALL_OUTPUT="$(AUTOINSTALL_OUTPUT)" \
	ANSIBLE_SSH_PUBLIC_KEY_FILE="$(ANSIBLE_SSH_PUBLIC_KEY_FILE)" \
	INSTALL_PASSWORD_HASH_FILE="$(INSTALL_PASSWORD_HASH_FILE)" \
	LUKS_PASSWORD_FILE="$(LUKS_PASSWORD_FILE)" \
	python3 scripts/render_autoinstall.py

iso: autoinstall ## Build build/ubuntu-autoinstall.iso from SOURCE_ISO + the rendered autoinstall.yaml
	@SOURCE_ISO="$(SOURCE_ISO)" \
	AUTOINSTALL_FILE="$(AUTOINSTALL_OUTPUT)" \
	OUTPUT_ISO="$(OUTPUT_ISO)" \
	VOLUME_ID="$(VOLUME_ID)" \
	scripts/build_iso.sh

clean: ## Remove the build/ directory
	rm -rf "$(BUILD_DIR)"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
