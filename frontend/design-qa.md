# Dashboard shell and teacher overview design QA

## Evidence

- Source visual truth: user-provided dashboard header, compact Weave header, teacher welcome-card, and KPI-card conversation images. Conversation attachments do not expose local filesystem paths.
- Implementation screenshot: unavailable because the user explicitly prohibited browser-tool use for this run.
- Intended viewport/state: desktop teacher Overview and admin Dashboard with authenticated staff account.
- Density normalization: not applicable because no implementation capture was authorized.
- Full-view comparison: blocked; source images were available, but a matching rendered implementation capture was not authorized.
- Focused-region comparison: blocked for the header, account pill, welcome panel, and KPI cards for the same reason.

## Implemented changes

- Teacher and admin topbars reduced to a 68 px minimum height.
- Teacher and admin now share one compact account-pill component with a single-letter 34 px avatar, display-name-first identity with email fallback, role label, chevron, and logout-only dropdown.
- Account dropdowns now render from elevated teacher and admin topbar stacking layers so dashboard cards cannot cover them.
- Teacher and admin topbars now show the tenant logo and school name; their collapse controls live inside their respective sidebars.
- Both desktop sidebars support the same explicit expanded and collapsed shell behavior.
- Notification controls were removed from both shells.
- Teacher greeting now derives morning, afternoon, or evening from the local hour.
- The greeting carries a sun icon during morning and afternoon and a moon icon during evening hours, derived from the same time state as its copy.
- The teacher slogan was removed.
- The teacher overview now has a standalone `Teacher's Dashboard` page title above the welcome panel.
- The teacher welcome panel uses tenant-branding primary tokens, an inverse foreground, and the same blueprint grid treatment as the sidebar.
- The teacher welcome panel now has a 250 px minimum height and a structured tenant identity row with the synchronized school logo and name.
- Beneath the school identity, the welcome panel presents the time-aware greeting followed by separate current-session and current-term chips.
- Teacher KPI cards now use a roomier four-column desktop layout with stacked icon, label, value, and caption content and a 170 px minimum height.
- The former full-width Quick Actions card was replaced by one top-right Quick Actions button before the welcome panel; it opens a compact icon-led menu for the same four teacher workflows.

## Required fidelity surfaces

- Fonts and typography: source-level values preserve the established dashboard font stack and readable hierarchy; rendered comparison blocked.
- Spacing and layout rhythm: shell and component dimensions were changed to the supplied proportions; rendered comparison blocked.
- Colors and visual tokens: the welcome panel uses `--color-primary`, `--color-on-primary`, and related tenant tokens rather than a hardcoded school color.
- Image quality and asset fidelity: existing icon components and school-logo assets were preserved; no replacement raster or code-drawn assets were introduced.
- Copy and content: notification controls and the teacher slogan were removed; greeting copy is now time-aware.

## Findings

- [P2] Rendered fidelity cannot be confirmed.
  Location: teacher/admin header, teacher welcome panel, teacher KPI row.
  Evidence: the source references are available, but no implementation screenshot can be captured without the prohibited browser tool.
  Impact: wrapping, exact proportions, and final visual balance cannot be judged from source code and automated checks alone.
  Fix: authorize a later browser-based visual pass at the reference desktop viewport.

## Automated verification

- Focused dashboard-shell and teacher-overview tests cover the shared account pill, notification removal, dropdown sign-out, topbar school identity, sidebar collapse controls, time-aware evening greeting and moon icon, slogan removal, and quick-action menu navigation.
- Focused ESLint passed for the changed components and tests.
- Staff production build passed.

## Follow-up polish

- None can be classified until rendered evidence is available.

final result: blocked
