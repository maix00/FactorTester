# ADR 178: React shell navigation and overlay layers

Status: accepted.

## Desktop

- The left sidebar contains only feature entry points (`研究`, `运行`, `交易`,
  `目录`, `账户`). It does not keep a second "opened pages" list.
- Opened pages live only in Dockview tabs/groups/splits.
- The active tab shows icon + title + close. Inactive tabs show icon only;
  their full title is available on hover.
- Tab identity is Dockview state, not the outer URL. The outer URL remains
  `/app` while tabs, splits and layout change.
- Settings is a centered global Overlay outside Dockview, with the same
  two-column layout as the legacy settings page (section nav + content).
- Notifications are a sibling global layer outside Dockview, with their own
  queue/dedupe rules.

## Mobile

- Bottom tabs are the primary navigation (`研究`, `运行`, `交易`, `工作区`,
  `设置`).
- A settings tab is a list of sections. Selecting a section opens a detail page
  with a back button; returning restores the settings list and bottom tabs.
- Workspace is a list of open/recent pages on narrow screens.
- Embedded legacy pages use `presentation=embedded` so they keep their own
  topbar under the mobile tabs; `presentation=canvas` is reserved for
  stack-style pages that provide their own header.

## Layering

```text
global notifications
global settings overlay
Dockview workspace
└── per-tab isolation layer (page dialogs/drawers)
```

No page creates its own global notification host.
