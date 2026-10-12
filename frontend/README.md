# Weave CBT frontend

The local CBT frontend is delivered as two independent browser applications that share the same backend and visual system.

```text
frontend/
  apps/
    staff/      staff application entrypoint
    student/    student application entrypoint
  src/          shared product code, features, API adapters, styles and UI
  dist/
    staff/      production staff build output
    student/    production student build output
```

## Development

The applications intentionally use different browser origins.

```bash
npm run dev:staff
# http://localhost:3001

npm run dev:student
# http://localhost:3002
```

Both development servers proxy `/api/v1` to the same local FastAPI backend.

The staff application owns installation/setup, staff authentication, teacher workspaces, admin workspaces and initial synchronization screens. It never restores or renders a student session.

The student application owns student authentication, the waiting room and the examination workspace. It never restores or renders a staff session and does not expose installation/setup screens.

## Builds

```bash
npm run build
```

builds both applications. They can also be built independently:

```bash
npm run build:staff
npm run build:student
```

The build outputs are written to `dist/staff/` and `dist/student/` respectively.

## Shared visual system

This split is an entrypoint/security boundary, not a visual redesign. Existing feature components, branding, icons and global styles remain under `src/` and are reused by the appropriate application.
