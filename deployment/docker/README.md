# Phase 1 Docker Architecture

Phase 1 builds one WEAVE-owned application image, not separate backend and frontend images.

The application image will contain:

- the Nuitka-compiled API executable,
- the Nuitka-compiled ARQ worker executable,
- the built staff frontend assets,
- the built student frontend assets,
- required runtime libraries.

Docker may start the same image with different commands to create an API container and a worker container. The API container will also serve the built frontend assets, so there is no separate frontend process to start.

PostgreSQL and Redis remain separate official images and will be introduced with Compose in a later phase.
