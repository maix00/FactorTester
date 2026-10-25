# Issue 443 status snapshot

Last verified: local Manager at `http://10.118.197.132:8770/app`.

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
- Native pages: account, desktop/mobile runs, settings.
- Legacy pages still embedded for research, trading and catalog; all registered
  routes return 200 through the local Manager.
- Local Docker stack health script; duplicate stopped CouchDB container removed.

## Not complete

- Nautilus wheel has not yet been produced for the local submodule commit.
- The public production revision has not been changed to this shell.
- Research/trading/catalog are not native React migrations.
- Research Report tables do not yet use `TRDataTable`.
- Real strategy-family RunSpec public acceptance is still pending.

## Do not claim

Do not claim Nautilus is installed, the strategy-family chain is accepted, or
that all pages are native React. The legacy iframe bridge remains intentional
during migration.

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
