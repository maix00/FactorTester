# TradeResearch Nautilus runtime composition

Builds the vendored Nautilus Python package and independent TradeResearch factor bridge
into one native extension. Nautilus owns the data, cache, messaging and trading engines.
The composition adds factor-plan/strategy registration without a dependency from
Nautilus core to TradeResearch. Features and package version follow the vendored Python
package; this wheel replaces that package rather than installing a second native engine.
