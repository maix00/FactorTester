/** Presentation groups registered tabs; field definitions remain server-owned. */
const sections: Record<string, string[]> = {
  data: ["data_source", "frequency", "time", "calendar", "factor", "price_type", "return_frequency"],
  execution: ["engine", "order", "position_policy", "rebalance_trigger", "target_allocation", "rollover", "delivery_force_close", "strategy_book", "group_strategy", "term_carry_strategy"],
  funds: ["capital", "cost", "margin", "accounting", "volume_capacity"],
};
export function settingsSection(registeredTab: string): string {
  return Object.entries(sections).find(([, tabs]) => tabs.includes(registeredTab))?.[0] || "other";
}
