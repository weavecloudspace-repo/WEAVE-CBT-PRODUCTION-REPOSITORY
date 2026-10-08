#!/usr/bin/env bash

set -Eeuo pipefail

RUNTIME_MARKER="/etc/weave-cbt-runtime"
RUNTIME_SCHEMA_VERSION="1"
DOCKER_SOURCES_FILE="/etc/apt/sources.list.d/docker.sources"
DOCKER_KEYRING="/etc/apt/keyrings/docker.asc"

export DEBIAN_FRONTEND=noninteractive

APT_GET=(
    apt-get
    -o DPkg::Lock::Timeout=120
    -o Acquire::Retries=3
    -o Acquire::http::Timeout=30
    -o Acquire::https::Timeout=30
)


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


log_warn() {
    printf '[WEAVE][WARN] %s\n' "$1" >&2
}


die() {
    printf '[WEAVE][ERROR] %s\n' "$1" >&2
    exit 1
}


on_error() {
    local exit_code=$?
    local line_number=$1

    printf '[WEAVE][ERROR] Linux bootstrap failed at line %s with exit code %s.\n' \
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


require_commands() {
    log_check "Checking required host commands."

    local command_name

    for command_name in ps systemctl journalctl apt-get apt-cache dpkg dpkg-query install mktemp awk seq tr; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            die "Required command '$command_name' is unavailable."
        fi
    done

    log_ok "Required host commands are available."
}


require_systemd() {
    log_check "Checking systemd availability."

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

    DISTRO_ID="${ID:-}"
    DISTRO_VERSION="${VERSION_ID:-unknown}"

    if [ -z "$DISTRO_ID" ]; then
        die "/etc/os-release does not define a Linux distribution ID."
    fi

    case "$DISTRO_ID" in
        ubuntu)
            DOCKER_REPOSITORY_DISTRO="ubuntu"
            DISTRO_CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
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

    ARCHITECTURE="$(dpkg --print-architecture)"

    if [ -z "$ARCHITECTURE" ]; then
        die "Unable to determine the host package architecture."
    fi

    log_ok "Detected $DISTRO_ID $DISTRO_VERSION ('$DISTRO_CODENAME', architecture '$ARCHITECTURE')."
}


package_installed() {
    local package_name=$1
    local status

    status="$(dpkg-query -W -f='${Status}' "$package_name" 2>/dev/null || true)"
    [ "$status" = "install ok installed" ]
}


docker_is_standardized() {
    package_installed docker-ce \
        && package_installed docker-ce-cli \
        && package_installed containerd.io \
        && package_installed docker-buildx-plugin \
        && package_installed docker-compose-plugin \
        && command -v docker >/dev/null 2>&1 \
        && command -v dockerd >/dev/null 2>&1 \
        && systemctl cat docker.service >/dev/null 2>&1 \
        && systemctl cat containerd.service >/dev/null 2>&1
}


remove_conflicting_packages() {
    log_check "Checking for packages that conflict with Docker CE."

    local package_name
    local conflicts_found=0

    for package_name in \
        docker.io \
        docker-compose \
        docker-compose-v2 \
        docker-doc \
        docker-buildx \
        podman-docker \
        containerd \
        runc
    do
        if package_installed "$package_name"; then
            conflicts_found=1
            log_action "Removing conflicting package '$package_name'."
            "${APT_GET[@]}" remove -y "$package_name"
        fi
    done

    if [ "$conflicts_found" -eq 0 ]; then
        log_skip "No conflicting Docker packages are installed."
    fi
}


configure_docker_repository() {
    log_action "Configuring Docker's official package repository."

    if [ -f "$DOCKER_SOURCES_FILE" ]; then
        log_action "Resetting existing Docker apt source before repository bootstrap."
        rm -f "$DOCKER_SOURCES_FILE"
    fi

    log_action "Refreshing package metadata."
    "${APT_GET[@]}" update

    log_action "Installing repository prerequisites."
    "${APT_GET[@]}" install -y ca-certificates curl

    install -m 0755 -d /etc/apt/keyrings

    local temporary_key
    temporary_key="$(mktemp)"

    log_action "Downloading Docker repository signing key."

    if ! curl --fail --silent --show-error --location \
        --retry 5 --retry-delay 2 --retry-connrefused \
        --connect-timeout 20 --max-time 120 \
        "https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO/gpg" \
        -o "$temporary_key"
    then
        rm -f "$temporary_key"
        die "Failed to download Docker repository signing key."
    fi

    install -m 0644 "$temporary_key" "$DOCKER_KEYRING"
    rm -f "$temporary_key"

    local temporary_sources
    temporary_sources="$(mktemp /etc/apt/sources.list.d/.docker.sources.XXXXXX)"

    cat > "$temporary_sources" <<EOF
Types: deb
URIs: https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO
Suites: $DISTRO_CODENAME
Components: stable
Architectures: $ARCHITECTURE
Signed-By: $DOCKER_KEYRING
EOF

    chmod 0644 "$temporary_sources"
    mv -f "$temporary_sources" "$DOCKER_SOURCES_FILE"

    log_action "Refreshing package metadata with Docker repository enabled."
    "${APT_GET[@]}" update

    local candidate
    candidate="$(apt-cache policy docker-ce | awk '/Candidate:/ { print $2; exit }')"

    if [ -z "$candidate" ] || [ "$candidate" = "(none)" ]; then
        die "Docker repository has no docker-ce package for $DISTRO_ID '$DISTRO_CODENAME' on '$ARCHITECTURE'."
    fi

    log_ok "Docker repository is usable; docker-ce candidate is '$candidate'."
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

    "${APT_GET[@]}" install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    if ! docker_is_standardized; then
        die "Docker packages were installed, but the expected Docker CE runtime is incomplete."
    fi

    log_ok "Docker Engine packages are installed."
}


show_service_diagnostics() {
    local service_name=$1

    log_warn "Diagnostics for $service_name:"
    systemctl status "$service_name" --no-pager --full >&2 || true
    journalctl -u "$service_name" --no-pager -n 50 >&2 || true
}


enable_docker_services() {
    log_action "Reloading systemd service definitions."
    systemctl daemon-reload

    log_action "Enabling containerd and Docker services."

    if ! systemctl enable containerd.service; then
        show_service_diagnostics containerd.service
        die "Failed to enable containerd.service."
    fi

    if ! systemctl enable docker.service; then
        show_service_diagnostics docker.service
        die "Failed to enable docker.service."
    fi

    log_action "Starting containerd service."

    if ! systemctl start containerd.service; then
        show_service_diagnostics containerd.service
        die "Failed to start containerd.service."
    fi

    log_action "Starting Docker service."

    if ! systemctl start docker.service; then
        show_service_diagnostics docker.service
        die "Failed to start docker.service."
    fi

    if ! systemctl is-active --quiet containerd.service; then
        show_service_diagnostics containerd.service
        die "containerd.service is not active after startup."
    fi

    if ! systemctl is-active --quiet docker.service; then
        show_service_diagnostics docker.service
        die "docker.service is not active after startup."
    fi

    log_ok "Docker and containerd services are enabled and active."
}


verify_docker_runtime() {
    log_check "Verifying Docker Engine connectivity."

    local attempt

    for attempt in $(seq 1 15); do
        if docker info >/dev/null 2>&1; then
            break
        fi

        if [ "$attempt" -eq 15 ]; then
            show_service_diagnostics docker.service
            die "Docker Engine did not become reachable."
        fi

        log_wait "Waiting for Docker Engine to become reachable (attempt $attempt/15)."
        sleep 1
    done

    log_ok "$(docker --version)"

    log_check "Verifying Docker Compose plugin."

    if ! docker compose version >/dev/null 2>&1; then
        die "Docker Compose plugin is not available."
    fi

    log_ok "$(docker compose version)"
}


check_host_reboot_notice() {
    if [ -f /var/run/reboot-required ]; then
        log_warn "The Linux host reports that a reboot is recommended. Docker is healthy now, but restart the host before production exam use."
    fi
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
        printf 'distribution_version=%s\n' "$DISTRO_VERSION"
        printf 'distribution_codename=%s\n' "$DISTRO_CODENAME"
        printf 'architecture=%s\n' "$ARCHITECTURE"
    } > "$temporary_marker"

    chmod 0644 "$temporary_marker"
    mv -f "$temporary_marker" "$RUNTIME_MARKER"

    log_ok "WEAVE runtime marker written."
}


main() {
    log "Starting Linux runtime bootstrap for WEAVE CBT."

    require_root
    require_commands
    require_systemd
    detect_distribution

    log "Provisioning WEAVE CBT Linux runtime on '$DISTRO_ID' ('$DISTRO_CODENAME')."

    install_docker_engine
    enable_docker_services
    verify_docker_runtime
    check_host_reboot_notice
    write_runtime_marker

    log_ok "Linux runtime provisioning complete. Docker Engine is ready."
}


main "$@"
