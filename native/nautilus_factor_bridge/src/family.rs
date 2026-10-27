//! Native consumers of one shared factor publication; no market history is kept.
use crate::FactorUpdate;
use nautilus_common::{
    actor::{DataActor, DataActorNative, registry::get_actor_unchecked},
    msgbus::{self, ShareableMessageHandler},
};
use nautilus_model::{
    enums::{OrderSide, TimeInForce},
    identifiers::{InstrumentId, StrategyId},
    orders::Order,
    types::Quantity,
};
use nautilus_trading::{
    nautilus_strategy,
    strategy::{Strategy, StrategyConfig, StrategyCore, StrategyNative},
};
use rust_decimal::Decimal;
use serde::Deserialize;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicUsize, Ordering},
};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc};

/// One frame-local ordering for each signal output, shared by all its groups.
#[derive(Debug)]
pub struct SharedRankings {
    products: Vec<String>,
    rows: BTreeMap<usize, Vec<usize>>,
    pub passes: usize,
}
impl SharedRankings {
    pub fn new(products: Vec<String>, outputs: Vec<usize>) -> Self {
        let count = products.len();
        Self {
            products,
            rows: outputs
                .into_iter()
                .map(|i| (i, Vec::with_capacity(count)))
                .collect(),
            passes: 0,
        }
    }
    pub fn update(&mut self, update: &FactorUpdate) -> anyhow::Result<()> {
        let count = self.products.len();
        for (&output, ranking) in &mut self.rows {
            let start = output
                .checked_mul(count)
                .ok_or_else(|| anyhow::anyhow!("ranking output overflow"))?;
            let values = update
                .values
                .get(start..start + count)
                .ok_or_else(|| anyhow::anyhow!("missing ranking output"))?;
            ranking.clear();
            ranking.extend((0..count).filter(|&i| !values[i].is_nan()));
            ranking.sort_unstable_by(|&l, &r| {
                values[l]
                    .partial_cmp(&values[r])
                    .unwrap()
                    .then_with(|| self.products[l].cmp(&self.products[r]))
            });
            self.passes += 1;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum FamilyRule {
    CrossSectionalGroup {
        split_count: usize,
        group_index: usize,
    },
    Threshold {
        entry: f64,
        exit: f64,
        side_mode: String,
    },
}

impl FamilyRule {
    fn fill_targets(&self, values: &[f64], ranking: &[usize], targets: &mut [i8]) {
        targets.fill(0);
        match self {
            FamilyRule::CrossSectionalGroup {
                split_count,
                group_index,
            } => {
                let size = ranking.len();
                for &index in &ranking
                    [(group_index - 1) * size / split_count..group_index * size / split_count]
                {
                    targets[index] = 1;
                }
            }
            FamilyRule::Threshold {
                entry,
                exit,
                side_mode,
            } => {
                for (target, &value) in targets.iter_mut().zip(values) {
                    // Preserve the frozen family's existing absolute-threshold side modes.
                    *target = if value >= *entry {
                        if side_mode == "short_only" { -1 } else { 1 }
                    } else if value <= -*entry {
                        if side_mode == "long_only" { 1 } else { -1 }
                    } else if value.abs() <= *exit {
                        0
                    } else {
                        0
                    };
                }
            }
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsumerSpec {
    pub strategy_id: String,
    pub signal_output: usize,
    pub rule: FamilyRule,
}

#[derive(Debug)]
pub struct FamilyStrategy {
    core: StrategyCore,
    spec: ConsumerSpec,
    instruments: Vec<InstrumentId>,
    rankings: Rc<RefCell<SharedRankings>>,
    topic: String,
    handler: Option<ShareableMessageHandler>,
    targets: Vec<i8>,
    pub publications: Arc<AtomicUsize>,
    error: Arc<Mutex<Option<String>>>,
}

impl FamilyStrategy {
    pub fn new(
        spec: ConsumerSpec,
        instruments: Vec<InstrumentId>,
        rankings: Rc<RefCell<SharedRankings>>,
        topic: String,
        error: Arc<Mutex<Option<String>>>,
    ) -> anyhow::Result<Self> {
        match &spec.rule {
            FamilyRule::CrossSectionalGroup {
                split_count,
                group_index,
            } => {
                anyhow::ensure!(
                    *split_count >= 2 && (1..=*split_count).contains(group_index),
                    "invalid group configuration"
                );
            }
            FamilyRule::Threshold {
                entry,
                exit,
                side_mode,
            } => {
                anyhow::ensure!(
                    entry.is_finite() && exit.is_finite() && *entry >= *exit && *exit >= 0.0,
                    "invalid threshold configuration"
                );
                anyhow::ensure!(
                    ["long_short", "long_only", "short_only"].contains(&side_mode.as_str()),
                    "invalid side mode"
                );
            }
        }
        let core = StrategyCore::new_checked(StrategyConfig {
            strategy_id: Some(StrategyId::new_checked(spec.strategy_id.as_str())?),
            ..Default::default()
        })?;
        let count = instruments.len();
        Ok(Self {
            core,
            spec,
            instruments,
            rankings,
            topic,
            handler: None,
            targets: vec![0; count],
            publications: Arc::new(AtomicUsize::new(0)),
            error,
        })
    }

    fn consume(&mut self, update: &FactorUpdate) -> anyhow::Result<()> {
        let count = self.instruments.len();
        let start = self
            .spec
            .signal_output
            .checked_mul(count)
            .ok_or_else(|| anyhow::anyhow!("output overflow"))?;
        let values = update
            .values
            .get(start..start + count)
            .ok_or_else(|| anyhow::anyhow!("missing signal output"))?;
        {
            let rankings = self.rankings.borrow();
            let ranking = rankings
                .rows
                .get(&self.spec.signal_output)
                .map(Vec::as_slice)
                .unwrap_or(&[]);
            self.spec
                .rule
                .fill_targets(values, ranking, &mut self.targets);
        }
        self.publications.fetch_add(1, Ordering::Relaxed);
        let strategy_id = self
            .strategy_core()
            .strategy_id()
            .ok_or_else(|| anyhow::anyhow!("strategy unregistered"))?;
        for index in 0..count {
            let instrument_id = self.instruments[index];
            let delta = {
                let cache = self.cache_ref();
                let position: Decimal = cache
                    .positions_open_refs(None, Some(&instrument_id), Some(&strategy_id), None, None)
                    .iter()
                    .map(|p| p.signed_qty)
                    .sum();
                let open = cache.orders_open_refs(
                    None,
                    Some(&instrument_id),
                    Some(&strategy_id),
                    None,
                    None,
                );
                let inflight = cache.orders_inflight_refs(
                    None,
                    Some(&instrument_id),
                    Some(&strategy_id),
                    None,
                    None,
                );
                let pending: Decimal = open
                    .iter()
                    .chain(inflight.iter().filter(|order| {
                        !open
                            .iter()
                            .any(|existing| existing.client_order_id() == order.client_order_id())
                    }))
                    .map(|o| {
                        o.leaves_qty().as_decimal()
                            * if o.order_side() == OrderSide::Buy {
                                Decimal::ONE
                            } else {
                                -Decimal::ONE
                            }
                    })
                    .sum();
                Decimal::from(self.targets[index] as i64) - position - pending
            };
            if delta == Decimal::ZERO {
                continue;
            }
            let order = self.order_factory().market(
                instrument_id,
                if delta > Decimal::ZERO {
                    OrderSide::Buy
                } else {
                    OrderSide::Sell
                },
                delta.abs().to_string().parse::<Quantity>().map_err(anyhow::Error::msg)?,
                Some(TimeInForce::AtTheOpen),
                None,
                None,
                None,
                None,
                None,
                None,
            );
            self.submit_order(order, None, None, None)?;
        }
        Ok(())
    }
}

impl DataActor for FamilyStrategy {
    fn on_start(&mut self) -> anyhow::Result<()> {
        let id = self.actor_id().inner();
        let handler = ShareableMessageHandler::from_typed(move |update: &FactorUpdate| {
            let mut strategy = get_actor_unchecked::<FamilyStrategy>(&id);
            if let Err(error) = strategy.consume(update) {
                let message = error.to_string();
                let mut state = strategy.error.lock().unwrap();
                if state.is_none() {
                    *state = Some(message.clone());
                }
                drop(state);
                strategy.shutdown_system(Some(message));
            }
        });
        msgbus::subscribe_any(self.topic.as_str().into(), handler.clone(), None);
        self.handler = Some(handler);
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> {
        if let Some(handler) = self.handler.take() {
            msgbus::unsubscribe_any(self.topic.as_str().into(), &handler);
        }
        Ok(())
    }
}
nautilus_strategy!(FamilyStrategy);

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn group_ranking_is_stable_and_shared_across_consumers() {
        let mut ranks = SharedRankings::new(vec!["B".into(), "A".into(), "C".into()], vec![0, 0]);
        ranks
            .update(&FactorUpdate {
                timestamp_ns: 1,
                available_at_ns: 1,
                products: vec![],
                values: vec![-0.0, 0.0, f64::NAN],
            })
            .unwrap();
        let mut targets = [0; 3];
        FamilyRule::CrossSectionalGroup {
            split_count: 2,
            group_index: 1,
        }
        .fill_targets(&[], &ranks.rows[&0], &mut targets);
        assert_eq!(targets, [0, 1, 0]);
        assert_eq!(ranks.passes, 1);
    }
    #[test]
    fn frozen_threshold_side_modes_match_the_contract() {
        for (mode, expected) in [
            ("long_short", [1, -1, 0, 0, 0]),
            ("long_only", [1, 1, 0, 0, 0]),
            ("short_only", [-1, -1, 0, 0, 0]),
        ] {
            let mut targets = [0; 5];
            FamilyRule::Threshold {
                entry: 1.0,
                exit: 0.0,
                side_mode: mode.into(),
            }
            .fill_targets(&[1.2, -1.2, 0.0, 0.5, f64::NAN], &[], &mut targets);
            assert_eq!(targets, expected);
        }
    }
}
