.PHONY: autoinstall iso autoinstall-vm iso-vm clean help

.DEFAULT_GOAL := help

BUILD_DIR ?= build

AUTOINSTALL_TEMPLATE ?= autoinstall.yaml.template
AUTOINSTALL_OUTPUT ?= $(BUILD_DIR)/autoinstall.yaml
ANSIBLE_SSH_PUBLIC_KEY_FILE ?=

SOURCE_ISO ?=
OUTPUT_ISO ?= $(BUILD_DIR)/ubuntu-autoinstall.iso
VOLUME_ID ?= ubuntu-autoinstall

# VM variant: no disk encryption, automatic layout (any disk size).
VM_TEMPLATE := autoinstall-vm.yaml.template
VM_OUTPUT := $(BUILD_DIR)/autoinstall-vm.yaml
VM_ISO := $(BUILD_DIR)/ubuntu-autoinstall-vm.iso

autoinstall: ## Render build/autoinstall.yaml from the template
	@AUTOINSTALL_TEMPLATE="$(AUTOINSTALL_TEMPLATE)" \
	AUTOINSTALL_OUTPUT="$(AUTOINSTALL_OUTPUT)" \
	ANSIBLE_SSH_PUBLIC_KEY_FILE="$(ANSIBLE_SSH_PUBLIC_KEY_FILE)" \
	python3 scripts/render_autoinstall.py

iso: autoinstall ## Build build/ubuntu-autoinstall.iso from SOURCE_ISO + the rendered autoinstall.yaml
	@SOURCE_ISO="$(SOURCE_ISO)" \
	AUTOINSTALL_FILE="$(AUTOINSTALL_OUTPUT)" \
	OUTPUT_ISO="$(OUTPUT_ISO)" \
	VOLUME_ID="$(VOLUME_ID)" \
	scripts/build_iso.sh

autoinstall-vm: ## Render build/autoinstall-vm.yaml from the VM template
	@$(MAKE) --no-print-directory autoinstall \
		AUTOINSTALL_TEMPLATE="$(VM_TEMPLATE)" AUTOINSTALL_OUTPUT="$(VM_OUTPUT)"

iso-vm: ## Build build/ubuntu-autoinstall-vm.iso (no encryption, auto layout) for VMs
	@$(MAKE) --no-print-directory iso \
		AUTOINSTALL_TEMPLATE="$(VM_TEMPLATE)" AUTOINSTALL_OUTPUT="$(VM_OUTPUT)" \
		OUTPUT_ISO="$(VM_ISO)"

clean: ## Remove the build/ directory
	rm -rf "$(BUILD_DIR)"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
