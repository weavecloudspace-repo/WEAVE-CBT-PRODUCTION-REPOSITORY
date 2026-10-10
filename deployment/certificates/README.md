# WEAVE CBT local HTTPS

The CBT host obtains browser-trusted certificates using Let's Encrypt DNS-01.
The school server stores its own private keys and ACME account; Bunny credentials
remain exclusively on WEAVE Cloud.

## Installation and operation

1. Deploy the updated WEAVE Cloud API before updating CBT pairing.
2. Pair CBT with WEAVE, and verify the cloud-assigned hostname appears in the
   local installation status response. Existing paired nodes can refresh it.
3. Configure the school's router/local DNS resolver so the assigned hostname
   resolves to the CBT host's private LAN IPv4 address. Public A records are
   unnecessary; DNS-01 uses public TXT records managed by WEAVE Cloud.
4. Install the version-matched CBT release with its certificate assets.
5. Run: weave tls --dry-run
6. When the dry run succeeds, run: weave tls
7. Test HTTPS and hostname resolution from a separate student computer.

Windows WSL2 requires a previously configured restricted school LAN listener,
through the existing weave lan command. The TLS command creates a separate
restricted port 443 listener, never a wildcard Internet-facing mapping.

Certificates, ACME account and renewal state persist in the tls_certificates
Docker volume. Only the identity *subdirectory* of the school data volume is
mounted read-only into the official Certbot image. The Docker socket, school
exam database, Bunny key and Redis are not exposed to Certbot.

After initial issuance the renewer checks approximately every 12 hours.
Nginx watches certificate changes and gracefully reloads when needed.
An internet outage does not stop ongoing LAN examinations with an already-valid
certificate. Internet access is needed again before the certificate expires.

TLS enrollment is opt-in for existing installations and cannot automatically
issue a certificate until the CBT machine is paired and local DNS is configured.
Never store certificates, machine credentials or private keys in GitHub or logs.
