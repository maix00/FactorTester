//! Authoritative boundary input for a completed slice, routed as Nautilus
//! custom data. The source adapter emits it before that slice's Bar callbacks.
use std::{any::Any, sync::Arc};
use nautilus_core::UnixNanos;
use nautilus_model::data::{CustomDataTrait, HasTsInit};

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct FactorBoundary {
    pub timestamp_ns: u64,
    pub flags: Vec<u8>,
}

impl HasTsInit for FactorBoundary {
    fn ts_init(&self) -> UnixNanos { self.timestamp_ns.into() }
}

impl CustomDataTrait for FactorBoundary {
    fn type_name(&self) -> &'static str { "FactorBoundary" }
    fn type_name_static() -> &'static str { "FactorBoundary" }
    fn as_any(&self) -> &dyn Any { self }
    fn ts_event(&self) -> UnixNanos { self.timestamp_ns.into() }
    fn to_json(&self) -> anyhow::Result<String> { Ok(serde_json::to_string(self)?) }
    fn clone_arc(&self) -> Arc<dyn CustomDataTrait> { Arc::new(self.clone()) }
    fn eq_arc(&self, other: &dyn CustomDataTrait) -> bool { other.as_any().downcast_ref::<Self>() == Some(self) }
    fn from_json(value: serde_json::Value) -> anyhow::Result<Arc<dyn CustomDataTrait>> {
        Ok(Arc::new(serde_json::from_value::<Self>(value)?))
    }
}
