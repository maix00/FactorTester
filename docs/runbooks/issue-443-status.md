# Issue 443 status snapshot

Last verified: public ECS `71b7ba268bad9edf845e6330f1971164ad4335c1`, local Manager `http://10.118.197.132:8770/app`.

## Implemented and verified

- React desktop shell with Dockview tabs, splits, layout persistence.
- Left sidebar is entry-only; opened pages live only in Dockview.
- Active tab shows icon/title/close; inactive tabs show icon only.
- Outer URL remains `/app` for tab, settings and mobile navigation.
- Settings is a global overlay; desktop matches the legacy two-column
  settings layout. Language is a settings item.
- Mobile has bottom tabs; settings is an internal list → detail → back flow
  (including browser back).
- i18next/react-i18next resources, language switch, legacy `ft-language`
  bridge, Intl formatters and missing-key tests.
- Ant Design notification queue outside Dockview; Ionic Toast/Modal/List
  notification center on mobile; uncaught errors routed to it.
- PWA manifest and shell-only service worker; API/auth responses are not
  cached.
- Native pages: account, desktop/mobile runs, settings, research/report read and report component operations, catalog lists/details, job artifact download/cancel.
- Public image `factortester-public:71b7ba268bad9edf845e6330f1971164ad4335c1` is healthy and contains the local Nautilus wheel plus the committed cp314 `py_alpha_lib` wheel.
- Nautilus wheel built from the local submodule source; public import reports `2.0.0rc8`; `alpha` imports from the cp314 wheel.
- Server suite: `1518 passed, 2 skipped`; web tests: `10 passed`; typecheck passes.

## Not complete

- Research editor, trading workbench and IC/factor-series workbench still use bridges.
- Research Report tables do not yet all use `TRDataTable`.
- Real strategy-family RunSpec public acceptance still needs an authenticated public run.
- Interactive/mobile page screenshots after the public image switch have not been refreshed.

## Do not claim

Do not claim real strategy-family public acceptance or that all pages are
native React. Nautilus is installed in the public image; the strategy-family
acceptance run is still pending.

## Desktop page render check

Verified with Playwright against the local Manager:

```text
Research  -> native landing page + legacy detail bridge
Runs      -> native page
Trading   -> native strategy-family landing + legacy workbench bridge
Catalog   -> native page with a legacy editor bridge
Account   -> native account page
```

All five entries render; Research, Runs, Trading, Catalog and Account have React landing pages. The legacy trading workbench remains a bridge.
