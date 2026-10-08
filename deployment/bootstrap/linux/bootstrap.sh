#!/usr/bin/env bash

set -Eeuo pipefail

RUNTIME_MARKER="/etc/weave-cbt-runtime"
RUNTIME_SCHEMA_VERSION="1"


log() {
    printf '[WEAVE] %s\n' "$1"
}


log_check() {
    printf '[WEAVE][CHECK] %s\n' "$1"
}


log_action() {
    printf '[WEAVE][ACTION] %s\n' "$1"
}


log_ok() {
    printf '[WEAVE][OK] %s\n' "$1"
}


log_skip() {
    printf '[WEAVE][SKIP] %s\n' "$1"
}


log_wait() {
    printf '[WEAVE][WAIT] %s\n' "$1"
}


die() {
    printf '[WEAVE] ERROR: %s\n' "$1" >&2
    exit 1
}


on_error() {
    local exit_code=$?
    local line_number=$1

    printf '[WEAVE] ERROR: Linux bootstrap failed at line %s with exit code %s.\n' \
        "$line_number" "$exit_code" >&2

    exit "$exit_code"
}


trap 'on_error "$LINENO"' ERR


require_root() {
    log_check "Checking root privileges."

    if [ "$(id -u)" -ne 0 ]; then
        die "WEAVE CBT bootstrap must be run as root."
    fi

    log_ok "Root privileges confirmed."
}


require_systemd() {
    log_check "Checking systemd availability."

    if ! command -v systemctl >/dev/null 2>&1; then
        die "systemctl is required. WEAVE CBT currently supports systemd-based Linux hosts."
    fi

    local init_system
    init_system="$(ps -p 1 -o comm= | tr -d '[:space:]')"

    if [ "$init_system" != "systemd" ]; then
        die "systemd must be PID 1. Detected '$init_system'."
    fi

    log_ok "systemd is running as PID 1."
}


detect_distribution() {
    log_check "Detecting Linux distribution."

    if [ ! -r /etc/os-release ]; then
        die "Unable to detect Linux distribution because /etc/os-release is unavailable."
    fi

    # shellcheck disable=SC1091
    . /etc/os-release

    DISTRO_ID="$ID"

    case "$DISTRO_ID" in
        ubuntu)
            DOCKER_REPOSITORY_DISTRO="ubuntu"
            DISTRO_CODENAME="${UBUNTU_CODENAME:-}"

            if [ -z "$DISTRO_CODENAME" ]; then
                DISTRO_CODENAME="${VERSION_CODENAME:-}"
            fi
            ;;
        debian)
            DOCKER_REPOSITORY_DISTRO="debian"
            DISTRO_CODENAME="${VERSION_CODENAME:-}"
            ;;
        *)
            die "Unsupported Linux distribution '$DISTRO_ID'. WEAVE CBT currently supports Ubuntu and Debian."
            ;;
    esac

    if [ -z "$DISTRO_CODENAME" ]; then
        die "Unable to determine the distribution codename for '$DISTRO_ID'."
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        die "apt-get is required for supported WEAVE CBT Linux installations."
    fi

    if ! command -v dpkg >/dev/null 2>&1; then
        die "dpkg is required for supported WEAVE CBT Linux installations."
    fi

    log_ok "Detected supported distribution '$DISTRO_ID' ('$DISTRO_CODENAME')."
}


docker_is_standardized() {
    dpkg -s docker-ce >/dev/null 2>&1 \
        && dpkg -s docker-ce-cli >/dev/null 2>&1 \
        && dpkg -s containerd.io >/dev/null 2>&1 \
        && dpkg -s docker-compose-plugin >/dev/null 2>&1 \
        && command -v docker >/dev/null 2>&1 \
        && command -v dockerd >/dev/null 2>&1 \
        && systemctl cat docker.service >/dev/null 2>&1
}


remove_conflicting_packages() {
    local package

    for package in \
        docker.io \
        docker-compose \
        docker-compose-v2 \
        docker-doc \
        docker-buildx \
        podman-docker \
        containerd \
        runc
    do
        if dpkg -s "$package" >/dev/null 2>&1; then
            log "Removing conflicting package '$package'."
            apt-get remove -y "$package"
        fi
    done
}


configure_docker_repository() {
    log_action "Configuring Docker's official package repository."

    export DEBIAN_FRONTEND=noninteractive

    log_action "Refreshing package metadata."
    apt-get update
    log_action "Installing repository prerequisites."
    apt-get install -y ca-certificates curl

    install -m 0755 -d /etc/apt/keyrings

    curl -fsSL \
        "https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO/gpg" \
        -o /etc/apt/keyrings/docker.asc

    chmod a+r /etc/apt/keyrings/docker.asc

    local architecture
    architecture="$(dpkg --print-architecture)"

    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO
Suites: $DISTRO_CODENAME
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    log_action "Refreshing package metadata with Docker repository enabled."
    apt-get update
}


install_docker_engine() {
    log_check "Checking Docker Engine package installation."

    if docker_is_standardized; then
        log_skip "Docker Engine is already provisioned from Docker's official packages."
        return
    fi

    log_action "Docker Engine needs provisioning."

    remove_conflicting_packages
    configure_docker_repository

    log_action "Installing Docker Engine, Buildx, and Docker Compose plugin."

    apt-get install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin
}


enable_docker_services() {
    log_action "Enabling Docker and containerd services."

    systemctl enable containerd.service
    systemctl enable docker.service

    log_action "Starting containerd and Docker services."
    systemctl start containerd.service
    systemctl start docker.service
    log_ok "Docker services are enabled and running."
}


verify_docker_runtime() {
    log_check "Verifying Docker Engine connectivity."

    local attempt

    for attempt in $(seq 1 15); do
        if docker info >/dev/null 2>&1; then
            break
        fi

        if [ "$attempt" -eq 15 ]; then
            die "Docker Engine did not become reachable."
        fi

        log_wait "Waiting for Docker Engine to become reachable (attempt $attempt/15)."
        sleep 1
    done

    log_ok "Docker Engine is reachable."
    log_check "Verifying Docker Compose plugin."

    if ! docker compose version >/dev/null 2>&1; then
        die "Docker Compose plugin is not available."
    fi

    log_ok "$(docker compose version)"
}


write_runtime_marker() {
    log_action "Writing WEAVE runtime marker to '$RUNTIME_MARKER'."

    local temporary_marker
    temporary_marker="$(mktemp /etc/.weave-cbt-runtime.XXXXXX)"

    {
        printf 'runtime_type=linux\n'
        printf 'runtime_name=native\n'
        printf 'schema_version=%s\n' "$RUNTIME_SCHEMA_VERSION"
        printf 'distribution=%s\n' "$DISTRO_ID"
        printf 'distribution_codename=%s\n' "$DISTRO_CODENAME"
    } > "$temporary_marker"

    chmod 0644 "$temporary_marker"
    mv -f "$temporary_marker" "$RUNTIME_MARKER"
    log_ok "WEAVE runtime marker written."
}


main() {
    log "Starting Linux runtime bootstrap for WEAVE CBT."
    require_root
    require_systemd
    detect_distribution

    log "Provisioning WEAVE CBT Linux runtime on '$DISTRO_ID' ('$DISTRO_CODENAME')."

    install_docker_engine
    enable_docker_services
    verify_docker_runtime
    write_runtime_marker

    log_ok "Linux runtime provisioning complete. Docker Engine is ready."
}


main "$@"
