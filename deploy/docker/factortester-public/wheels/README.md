# Local Nautilus wheels

Place the wheel built from `vendor/nautilus_trader` here before a public
build that sets `NAUTILUS_WHEEL_REQUIRED=1`. The build fails when the flag is
set and no `nautilus_trader-*.whl` is present; it never silently skips a
required local build.
