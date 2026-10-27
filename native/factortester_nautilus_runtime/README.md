# FactorTester Nautilus runtime composition

Builds the vendored Nautilus Python package and independent FactorTester factor bridge
into one native extension. Nautilus owns the data, cache, messaging and trading engines.
The composition adds factor-plan/strategy registration without a dependency from
Nautilus core to FactorTester. Features and package version follow the vendored Python
package; this wheel replaces that package rather than installing a second native engine.
