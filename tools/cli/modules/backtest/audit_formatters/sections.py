"""Step audit section rendering orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import click

from tools.cli.modules.backtest.audit_formatters import printer_helpers
from tools.cli.modules.backtest.audit_formatters import source_groups


@dataclass(frozen=True)
class StepAuditSectionPrinter:
    print_step_section: Callable[[str], None]
    field_sort_key: Callable[[str], tuple[int, int, str]]
    field_display_value_kind: Callable[[str], str | None]
    print_market_snapshot_value_table: Callable[[str, list[dict[str, Any]]], bool]
    print_market_snapshot_change_table: Callable[[str, list[tuple[str, list[dict[str, Any]]]]], bool]
    print_market_data_sample_value_table: Callable[[str, list[dict[str, Any]]], bool]
    print_market_data_sample_change_table: Callable[[str, list[tuple[str, list[dict[str, Any]]]]], bool]
    print_delta_mapping_value_tables: Callable[[str, list[dict[str, Any]]], bool]
    print_delta_mapping_change_tables: Callable[[str, list[tuple[str, list[dict[str, Any]]]]], bool]
    print_delta_mapping_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_delta_mapping_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_order_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_order_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_execution_price_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_execution_price_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    scalar_value_record_group: Callable[[dict[str, Any]], tuple[Any, Any, Any]]
    scalar_value_group_key: Callable[[dict[str, Any]], Any]
    scalar_change_record_group: Callable[[str, list[dict[str, Any]]], tuple[Any, Any, Any]]
    scalar_change_group_key: Callable[[tuple[str, list[dict[str, Any]]]], Any]
    drop_empty_non_ledger_entries: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]]
    print_strategy_record_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_ledger_scalar_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_strategy_scalar_value_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_ledger_grouped_values: Callable[[str, str, list[dict[str, Any]]], bool]
    display_field_value: Callable[[str, Any], Any]
    display_key: Callable[[Any], str]
    print_audit_source_routes: Callable[[str, list[dict[str, Any]]], None]
    print_audit_value: Callable[[str, str, Any], None]
    print_lifecycle_notice_change: Callable[[str, str, list[dict[str, Any]]], bool]
    print_weight_change_tables: Callable[[str, str, list[dict[str, Any]]], bool]
    print_strategy_scalar_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_positions_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_cash_pool_scalar_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_ledger_scalar_change_table: Callable[[str, str, list[dict[str, Any]]], bool]
    print_ledger_grouped_changes: Callable[[str, str, list[dict[str, Any]]], bool]
    print_audit_diff_value: Callable[[str, str, Any, Any], None]

    def print_fields(
        self,
        title: str,
        records: list[dict[str, Any]],
        *,
        empty_message: str = "（无字段）",
    ) -> None:
        self.print_step_section(title)
        if not records:
            click.echo(f"  {empty_message}")
            return
        sorted_records = printer_helpers.sorted_field_records(records, sort_key=self.field_sort_key)
        consumed_indexes: set[int] = set()
        index = 0
        while index < len(sorted_records):
            if index in consumed_indexes:
                index += 1
                continue
            record = sorted_records[index]
            field_name = str(record.get("field") or "")
            values = record.get("values") or []
            if self._is_market_snapshot_field(field_name):
                combined_snapshot = [
                    item for item_index, item in enumerate(sorted_records)
                    if item_index not in consumed_indexes
                    and self._is_market_snapshot_field(str(item.get("field") or ""))
                ]
                if self.print_market_snapshot_value_table("    ", combined_snapshot):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_records)
                        if self._is_market_snapshot_field(str(item.get("field") or ""))
                    )
                    index += 1
                    continue
            if self._is_market_data_sample_field(field_name):
                combined = [
                    item for item_index, item in enumerate(sorted_records)
                    if item_index not in consumed_indexes
                    and self._is_market_data_sample_field(str(item.get("field") or ""))
                ]
                if self.print_market_data_sample_value_table("    ", combined):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_records)
                        if self._is_market_data_sample_field(str(item.get("field") or ""))
                    )
                    index += 1
                    continue
            if self._is_delta_table_field(field_name):
                combined_delta = [
                    item for item_index, item in enumerate(sorted_records)
                    if item_index not in consumed_indexes
                    and self._is_delta_table_field(str(item.get("field") or ""))
                ]
                if self.print_delta_mapping_value_tables("    ", combined_delta):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_records)
                        if self._is_delta_table_field(str(item.get("field") or ""))
                    )
                    index += 1
                    continue
            if self._is_order_table_field(field_name) and self.print_order_value_table("    ", field_name, values):
                index += 1
                continue
            if self._is_execution_price_table_field(field_name) and self.print_execution_price_value_table("    ", field_name, values):
                index += 1
                continue
            if self.print_delta_mapping_value_table("    ", field_name, values):
                index += 1
                continue
            current_table, combined_printer, current_routes = self.scalar_value_record_group(record)
            if current_table is not None:
                printed, next_index = printer_helpers.try_print_combined_group(
                    sorted_records,
                    start=index,
                    consumed_indexes=consumed_indexes,
                    current_key=(combined_printer, current_routes),
                    key_fn=self.scalar_value_group_key,
                    printer=combined_printer,
                    prefix="    ",
                    combine=lambda current, matches: [current, *matches],
                )
                if printed:
                    index = next_index
                    continue
            if current_table is not None:
                index += 1
                continue
            values = self.drop_empty_non_ledger_entries(field_name, values)
            if not values:
                click.echo(f"  {printer_helpers.combined_single_field_label(field_name)}:", color=True)
                click.echo("    （当前无值）")
                index += 1
                continue
            if self.print_strategy_record_value_table("    ", field_name, values):
                index += 1
                continue
            click.echo(f"  {printer_helpers.combined_single_field_label(field_name)}:", color=True)
            if self.print_ledger_scalar_value_table("    ", field_name, values):
                index += 1
                continue
            if self.print_strategy_scalar_value_table("    ", field_name, values):
                index += 1
                continue
            if self.print_ledger_grouped_values("    ", field_name, values):
                index += 1
                continue
            self._print_value_buckets(field_name, values)
            index += 1

    def print_changes(
        self,
        title: str,
        changes: list[dict[str, Any]],
    ) -> None:
        self.print_step_section(title)
        if not changes:
            click.echo("  （无变化）")
            return
        sorted_items = printer_helpers.sorted_field_change_items(changes, sort_key=self.field_sort_key)
        consumed_indexes: set[int] = set()
        index = 0
        while index < len(sorted_items):
            if index in consumed_indexes:
                index += 1
                continue
            field_name, field_changes = sorted_items[index]
            if self._is_market_snapshot_field(field_name):
                combined_snapshot = [
                    item for item_index, item in enumerate(sorted_items)
                    if item_index not in consumed_indexes
                    and self._is_market_snapshot_field(item[0])
                ]
                if self.print_market_snapshot_change_table("  ", combined_snapshot):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_items)
                        if self._is_market_snapshot_field(item[0])
                    )
                    index += 1
                    continue
            if self._is_market_data_sample_field(field_name):
                combined_market = [
                    item for item_index, item in enumerate(sorted_items)
                    if item_index not in consumed_indexes
                    and self._is_market_data_sample_field(item[0])
                ]
                if self.print_market_data_sample_change_table("  ", combined_market):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_items)
                        if self._is_market_data_sample_field(item[0])
                    )
                    index += 1
                    continue
            if self._is_delta_table_field(field_name):
                combined_delta = [
                    item for item_index, item in enumerate(sorted_items)
                    if item_index not in consumed_indexes
                    and self._is_delta_table_field(item[0])
                ]
                if self.print_delta_mapping_change_tables("    ", combined_delta):
                    consumed_indexes.update(
                        item_index for item_index, item in enumerate(sorted_items)
                        if self._is_delta_table_field(item[0])
                    )
                    index += 1
                    continue
            if self._is_order_table_field(field_name) and self.print_order_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self._is_execution_price_table_field(field_name) and self.print_execution_price_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_delta_mapping_change_table("    ", field_name, field_changes):
                index += 1
                continue
            current_table, combined_printer, current_routes = self.scalar_change_record_group(field_name, field_changes)
            if current_table is not None:
                printed, next_index = printer_helpers.try_print_combined_group(
                    sorted_items,
                    start=index,
                    consumed_indexes=consumed_indexes,
                    current_key=(combined_printer, current_routes),
                    key_fn=self.scalar_change_group_key,
                    printer=combined_printer,
                    prefix="  ",
                    combine=lambda current, matches: [current, *matches],
                )
                if printed:
                    index = next_index
                    continue
            if current_table is not None:
                index += 1
                continue
            click.echo(f"  {printer_helpers.combined_single_field_label(field_name)}:", color=True)
            if self.print_lifecycle_notice_change("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_weight_change_tables("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_strategy_scalar_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_positions_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_cash_pool_scalar_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_ledger_scalar_change_table("    ", field_name, field_changes):
                index += 1
                continue
            if self.print_ledger_grouped_changes("    ", field_name, field_changes):
                index += 1
                continue
            self._print_change_buckets(field_name, field_changes)
            index += 1

    def _is_market_data_sample_field(self, field_name: str) -> bool:
        return self.field_display_value_kind(field_name) == "market_data_sample"

    def _is_market_snapshot_field(self, field_name: str) -> bool:
        return self.field_display_value_kind(field_name) == "market_snapshot"

    def _is_delta_table_field(self, field_name: str) -> bool:
        return self.field_display_value_kind(field_name) == "delta_table"

    def _is_order_table_field(self, field_name: str) -> bool:
        return self.field_display_value_kind(field_name) == "order_table"

    def _is_execution_price_table_field(self, field_name: str) -> bool:
        return self.field_display_value_kind(field_name) == "execution_price_table"

    def _print_value_buckets(
        self,
        field_name: str,
        values: list[dict[str, Any]],
    ) -> None:
        buckets = source_groups.grouped_values(
            field_name,
            values,
            display_field_value=self.display_field_value,
            display_key=self.display_key,
        )
        for bucket in buckets:
            label = source_groups.source_group_label(bucket["entries"], shared_group=len(buckets) == 1)
            if source_groups.source_route_rows(bucket["entries"]):
                click.echo(f"    {label}:")
                self.print_audit_source_routes("      ", bucket["entries"])
                self.print_audit_value("      ", "value", bucket["value"])
            else:
                self.print_audit_value("    ", label, bucket["value"])

    def _print_change_buckets(
        self,
        field_name: str,
        field_changes: list[dict[str, Any]],
    ) -> None:
        buckets = printer_helpers.field_change_buckets(
            field_name,
            field_changes,
            display_value=self.display_field_value,
            display_key=self.display_key,
        )
        for bucket in buckets:
            label = source_groups.source_group_label(bucket["entries"], shared_group=len(buckets) == 1)
            if source_groups.source_route_rows(bucket["entries"]):
                click.echo(f"    {label}:")
                self.print_audit_source_routes("      ", bucket["entries"])
                self.print_audit_diff_value("      ", "value", bucket["before"], bucket["after"])
            else:
                self.print_audit_diff_value("    ", label, bucket["before"], bucket["after"])
