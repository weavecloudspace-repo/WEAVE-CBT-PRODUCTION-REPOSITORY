# Linux release acceptance checklist

Status: manual acceptance required before production promotion. CI packaging and headless smoke tests do not establish successful operation in a real desktop session.

## Fresh installation

- Use an isolated Ubuntu 24.04 LTS amd64 host and a supported Debian amd64 host, with both a normal desktop account and an administrator.
- Install the official Linux desktop DEB on a fresh desktop; independently test the standalone CLI archive on a fresh host. Record package versions and the selected release channel.
- Verify that the GUI opens without root privileges, detects a root-installed server, and reports service health without granting the user unrestricted Docker socket access.
- Confirm that administrative actions require explicit Polkit authorization and fail with actionable diagnostics when no authentication agent is available.
- Verify that installation refuses to overwrite a different release channel, detects mixed DEB/standalone installations, and preserves existing unrelated Docker workloads.

## Startup and recovery

- Confirm Docker and containerd are enabled under systemd and that the API, worker, PostgreSQL, Redis and Nginx recover after a full host reboot without running the CLI manually.
- Confirm that intentionally stopped containers remain stopped until the administrator starts them.
- Test abrupt power loss on a disposable installation, verify database integrity, and restore from a backup. Do not use production examination data.
- Test upgrade, interrupted upgrade, rollback, and uninstall; verify named volumes and school data remain intact unless an explicit destructive operation was authorized.

## School LAN and HTTPS

- Inspect host listening addresses for TCP 80/443 and confirm only intended school networks can connect. Docker published ports may bypass naive UFW INPUT rules; verify actual packet filtering from another device and an untrusted network.
- Verify student and staff portals from wired and Wi-Fi clients on the same routed school LAN. Verify offline examination operation with the internet disconnected.
- Verify the paired hostname resolves to the private school address for students; configure a router DNS A record and DHCP reservation where supported.
- Issue and activate a trusted certificate, then confirm the HTTP 308 redirect, HTTPS certificate chain, hostname, SNI, and application routes. Never bypass TLS certificate verification in diagnostics.
- Confirm DNS and HTTPS still work after DHCP renewal, router replacement, and server reboot.

## Evidence required

Record distro, kernel, CPU architecture, package names and checksums, installation logs, commands, actual user privileges, reboot results, GUI screenshots, client-side DNS/HTTPS checks, and any failures. Do not claim real-device Linux acceptance solely from GitHub Actions.
