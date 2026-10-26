# nautilus-factor-bridge

Independent Rust bridge between Nautilus market events and py-alpha-lib.

```text
Nautilus Bar
  -> FactorActor<E: FactorEngine>
  -> MarketBar
  -> Rust factor engine
  -> Vec<f64>
```

Engines:

```text
WindowEngine          one window, one product
ProductWindowEngine   one window, all products
MultiWindowEngine     several windows, one product
MatrixPlanEngine      factors x products
```

`FactorActor` registers with `nautilus_common::actor::registry` and consumes
`nautilus_model::data::Bar`; no Python is involved.

Nautilus core does not depend on this crate. `nautilus-*` dependencies are
optional behind the `nautilus` feature; `py-alpha-lib` never depends on
Nautilus.

Still missing: a FactorExpr DAG engine, signal notification, and trader wiring.
