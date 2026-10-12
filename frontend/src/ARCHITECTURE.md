# Frontend architecture

The frontend is organized by responsibility rather than by generic file type.

Two independent Vite applications live under `frontend/apps/`:

```text
apps/
  staff/      staff/admin application entrypoint
  student/    candidate application entrypoint
```

They intentionally run on separate browser origins while sharing the same backend and shared product code.

The reusable application code remains organized under `src/`:

```text
src/
  app/       application composition, global reducer, gateway wiring
  api/       HTTP transport adapters grouped by backend domain
  features/  role/user-facing feature modules
  shared/    reusable UI and icon primitives with no feature ownership
  styles/    application-wide CSS
  assets/    bundled static assets
```

## Application boundaries

- The staff application owns setup/pairing, staff authentication, sync readiness, teacher screens and admin screens.
- The student application owns student authentication, waiting-room state and the examination workspace.
- Staff startup restores only staff sessions.
- Student startup restores only student sessions.
- The student application does not render setup, teacher or admin screens.
- The staff application does not render student login, waiting-room or examination screens.

## Shared source boundaries

- `app/` may compose features, shared primitives, and API-backed gateways.
- `api/` owns HTTP details. Feature components use the domain adapters through the app gateway rather than calling `fetch` directly.
- `features/` owns user-facing flows. Feature-specific components, pages, hooks, and CSS stay inside their feature folder.
- `shared/` contains reusable presentation primitives only. It must not depend on a feature.
- `styles/` contains truly global styles. Feature-specific styles stay with the feature.
- Avoid recreating generic top-level `components/`, `lib/`, `services/`, or `state/` buckets. Put code under the owner that gives it context.

`src/app/StaffApp.jsx` and `src/app/StudentApp.jsx` are the active application roots. The older combined `src/app/App.jsx` remains only as a compatibility surface for existing tests/imports and is not used by the normal staff/student build scripts.
