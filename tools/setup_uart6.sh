#!/usr/bin/env bash
# Enable the ROCK 5C's receiver UART in Radxa OS extlinux.
set -euo pipefail

uart6_overlay_enabled() {
    local extlinux=$1 overlay=$2
    awk -v overlay="$overlay" '
        tolower($1) == "fdtoverlays" {
            for (i = 2; i <= NF && $i !~ /^#/; i++) {
                split($i, parts, "/")
                if (parts[length(parts)] == overlay) enabled = 1
            }
        }
        END { exit !enabled }
    ' "$extlinux"
}

enable_uart6() {
    local extlinux=$1 dtbo=$2 rsetup=$3 backups=$4
    local overlay=${dtbo##*/} backup restore
    uart6_changed=false
    if [[ ! -f "$extlinux" ]]; then
        echo "UART6 setup requires an extlinux boot configuration at $extlinux." >&2
        return 1
    fi
    if [[ -f "$dtbo" ]] && uart6_overlay_enabled "$extlinux" "$overlay"; then
        echo "UART6-M1 is already configured in $extlinux."
        return 0
    fi
    if [[ ! -x "$rsetup" ]]; then
        echo "UART6 setup requires Radxa OS rsetup at $rsetup." >&2
        return 1
    fi

    extlinux=$(readlink -f -- "$extlinux")
    backup=$(mktemp "$backups/extlinux-before-uart6-$(date +%Y%m%d-%H%M%S).XXXXXX.conf")
    cp -p -- "$extlinux" "$backup"
    echo "Boot configuration backed up to $backup"
    if ! "$rsetup" enable_overlays "$overlay" || [[ ! -f "$dtbo" ]] || ! uart6_overlay_enabled "$extlinux" "$overlay"; then
        restore=$(mktemp "${extlinux}.uart6-restore.XXXXXX")
        cp -p -- "$backup" "$restore"
        mv -f -- "$restore" "$extlinux"
        echo "UART6 overlay verification failed. Restored $extlinux from $backup." >&2
        return 1
    fi
    uart6_changed=true
    echo "UART6-M1 boot configuration verified."
}

main() {
    local reboot=false model
    case "${1:-}" in
        --reboot) reboot=true; shift ;;
        --help|-h) echo "Usage: sudo bash tools/setup_uart6.sh [--reboot]"; return 0 ;;
    esac
    if (( $# )); then
        echo "Usage: sudo bash tools/setup_uart6.sh [--reboot]" >&2
        return 2
    fi

    if [[ -r /proc/device-tree/model ]]; then
        model=$(tr -d '\000' < /proc/device-tree/model)
    else
        model=unknown
    fi
    case "$model" in
        'Radxa ROCK 5C'|'Radxa ROCK 5C Lite') ;;
        *) echo "Skipping UART6-M1 setup on $model. It is specific to the Radxa ROCK 5C."; return 0 ;;
    esac
    if (( EUID != 0 )); then
        echo "Run with sudo: sudo bash tools/setup_uart6.sh" >&2
        return 1
    fi

    install -d -m 0750 /var/log/eposter /var/backups/eposter/uart6
    exec 9>/run/lock/eposter-uart6.lock
    flock -x 9
    exec > >(tee -a /var/log/eposter/uart6-setup.log) 2>&1
    echo "$(date -Is) Receiver UART6: Radxa TX pin 19, RX pin 21, GND pin 20."
    enable_uart6 /boot/extlinux/extlinux.conf /boot/dtbo/rk3588-uart6-m1.dtbo \
        /usr/bin/rsetup /var/backups/eposter/uart6

    if [[ "$uart6_changed" == true || ! -c /dev/ttyS6 ]]; then
        echo 'Reboot the board to activate /dev/ttyS6.'
        if [[ "$reboot" == true ]]; then
            systemctl reboot
        fi
    else
        echo 'UART6 is available at /dev/ttyS6.'
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
