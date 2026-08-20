#!/usr/bin/env bash
# Bake an autoinstall.yaml into a base Ubuntu live-server ISO, producing a
# single ISO that boots straight into an unattended install.
set -euo pipefail

SOURCE_ISO="${SOURCE_ISO:-}"
AUTOINSTALL_FILE="${AUTOINSTALL_FILE:-build/autoinstall.yaml}"
OUTPUT_ISO="${OUTPUT_ISO:-build/ubuntu-autoinstall.iso}"
VOLUME_ID="${VOLUME_ID:-ubuntu-autoinstall}"

usage() {
    cat <<EOF
Usage: SOURCE_ISO=/path/to/ubuntu-*.iso $0 [options]

Options (env vars, or flags with the same name lowercased):
  --source-iso PATH        Base Ubuntu live-server ISO (required)
  --autoinstall-file PATH  Rendered autoinstall.yaml; generated here if missing (default: build/autoinstall.yaml)
  --output-iso PATH        Output ISO path (default: build/ubuntu-autoinstall.iso)
  --volume-id ID           ISO volume id, max 32 chars (default: ubuntu-autoinstall)
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --source-iso) SOURCE_ISO="$2"; shift 2 ;;
        --autoinstall-file) AUTOINSTALL_FILE="$2"; shift 2 ;;
        --output-iso) OUTPUT_ISO="$2"; shift 2 ;;
        --volume-id) VOLUME_ID="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
    esac
done

if [ -z "$SOURCE_ISO" ]; then
    if [ -t 0 ]; then
        read -e -r -p "Path to base Ubuntu live-server ISO: " SOURCE_ISO
    fi
    if [ -z "$SOURCE_ISO" ]; then
        echo "SOURCE_ISO is required (base Ubuntu live-server ISO)." >&2
        usage
        exit 1
    fi
fi
SOURCE_ISO="${SOURCE_ISO/#\~/$HOME}"
if [ ! -f "$SOURCE_ISO" ]; then
    echo "Source ISO not found: $SOURCE_ISO" >&2
    exit 1
fi
if [ ! -f "$AUTOINSTALL_FILE" ]; then
    echo "Autoinstall file not found, generating $AUTOINSTALL_FILE ..."
    AUTOINSTALL_OUTPUT="$AUTOINSTALL_FILE" \
        python3 "$(dirname "${BASH_SOURCE[0]}")/render_autoinstall.py"
fi
if ! command -v xorriso >/dev/null 2>&1; then
    echo "xorriso is required. Install it with: sudo apt install xorriso" >&2
    exit 1
fi

WORKDIR="$(mktemp -d)"
SCRATCH="$(mktemp -d)"
# Files extracted from the ISO come out read-only (including directories),
# so a bare rm -rf can't clean up if we exit before the chmod below runs
# (e.g. on error mid-extraction) — chmod first so cleanup can't get stuck.
cleanup() { chmod -R u+w "$WORKDIR" "$SCRATCH" 2>/dev/null; rm -rf "$WORKDIR" "$SCRATCH"; }
trap cleanup EXIT

echo "Extracting $SOURCE_ISO ..."
xorriso -osirrox on -indev "$SOURCE_ISO" -extract / "$WORKDIR" >/dev/null
chmod -R u+w "$WORKDIR"

echo "Embedding NoCloud autoinstall data ..."
cp "$AUTOINSTALL_FILE" "$WORKDIR/user-data"
: > "$WORKDIR/meta-data"

# Point the installer at the ISO itself as its NoCloud data source and
# select autoinstall automatically, on every boot-menu entry that starts
# the live-server kernel. Entries end their static params with a "---"
# marker (casper's convention for where dynamically-added params go);
# insert before it when present, otherwise append at end of line.
inject_params() {
    local file="$1" anchor="$2" params="$3"
    [ -f "$file" ] || return 0
    if grep -qE "$anchor" "$file"; then
        sed -E -i "\\#${anchor}#{ /---/ s@ ---@ ${params} ---@; /---/! s@\$@ ${params}@ }" "$file"
    fi
}

# GRUB re-parses this line as script, so a literal ";" would be read as a
# statement separator and never reach the kernel — it must be escaped.
inject_params "$WORKDIR/boot/grub/grub.cfg" '/casper/vmlinuz' \
    'autoinstall ds=nocloud\\;s=/cdrom/'

# isolinux's APPEND line is passed to the kernel verbatim, so ";" is used
# unescaped here — escaping it would leave a literal backslash in the
# kernel command line and break cloud-init's ds= parsing.
inject_params "$WORKDIR/isolinux/txt.cfg" '^[[:space:]]*append\b' \
    'autoinstall ds=nocloud;s=/cdrom/'

# Recent Ubuntu ISOs (22.04.3+) are BIOS+UEFI hybrid-GPT: the BIOS boot
# image is a normal file, but the UEFI image is an appended partition with
# no ISO9660 path of its own (xorriso reports it as "hidden"). That means
# it can't be repacked by pointing mkisofs at paths in the extracted tree
# alone — the hidden image's raw bytes have to be pulled out of the source
# ISO by LBA and re-attached as an appended GPT partition on rebuild.
report="$(xorriso -indev "$SOURCE_ISO" -report_el_torito plain 2>&1)"
bios_path="$(awk '/^El Torito img path/ && $6==1 {print $NF}' <<<"$report")"
uefi_ldsiz="$(awk '/^El Torito boot img/ && $6==2 {print $12}' <<<"$report")"
uefi_lba="$(awk '/^El Torito boot img/ && $6==2 {print $13}' <<<"$report")"

if [ -z "$bios_path" ] || [ -z "$uefi_ldsiz" ] || [ -z "$uefi_lba" ]; then
    echo "Could not read expected BIOS/UEFI boot images from $SOURCE_ISO." >&2
    echo "This script targets modern hybrid-GPT Ubuntu ISOs (22.04.3+/24.04/26.04)." >&2
    exit 1
fi
bios_path="${bios_path#/}"

efi_img="$SCRATCH/efi.img"
mbr_img="$SCRATCH/mbr.img"
dd if="$SOURCE_ISO" of="$efi_img" bs=2048 skip="$uefi_lba" count="$((uefi_ldsiz / 4))" status=none
dd if="$SOURCE_ISO" of="$mbr_img" bs=1 count=432 status=none

mkdir -p "$(dirname "$OUTPUT_ISO")"
rm -f "$OUTPUT_ISO"

echo "Repacking $OUTPUT_ISO ..."
xorriso -as mkisofs \
        -r -V "$VOLUME_ID" \
        -J -joliet-long -l \
        -iso-level 3 \
        -partition_offset 16 \
        --grub2-mbr "$mbr_img" \
        --mbr-force-bootable \
        -append_partition 2 0xEF "$efi_img" \
        -appended_part_as_gpt \
        -c boot.catalog \
        -b "$bios_path" \
          -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
        -eltorito-alt-boot \
        -e --interval:appended_partition_2::: \
          -no-emul-boot \
        -o "$OUTPUT_ISO" \
        "$WORKDIR" \
        >/dev/null

echo "Built $OUTPUT_ISO ($(du -h "$OUTPUT_ISO" | cut -f1))"
