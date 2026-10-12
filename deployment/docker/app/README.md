# WEAVE Application Image

This directory defines the single WEAVE CBT application image used by Phase 1.

Build responsibilities:

1. Build the staff and student Vite applications into static assets.
2. Compile the API entry point with Nuitka.
3. Compile the ARQ worker entry point with Nuitka.
4. Assemble those artifacts into one final image.

Runtime responsibilities:

- API container: starts the compiled API executable and serves both the REST API and built frontend assets.
- Worker container: starts the compiled worker executable.

Both containers use the same `weave-cbt:<version>` image but run different commands.

PostgreSQL and Redis are intentionally not packaged into this image.

No runtime implementation is present in this scaffold yet.
