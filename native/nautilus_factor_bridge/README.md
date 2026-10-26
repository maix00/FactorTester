# nautilus-factor-bridge

Independent Rust bridge between Nautilus market events and py-alpha-lib.

```text
Nautilus actor/plugin
  -> nautilus-factor-bridge
       -> py-alpha-lib (FactorEngine state)
```

`nautilus-core` is an optional feature; Nautilus core does not depend on this
crate and py-alpha-lib does not depend on Nautilus.
