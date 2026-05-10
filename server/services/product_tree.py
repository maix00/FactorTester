"""Product tree construction and Fancytree conversion helpers."""

from __future__ import annotations

import re

import Settings as Settings


def convert_to_fancytree(tree_dict, checkbox_default=True):
    def iter_child_entries(value):
        entries = []
        processed_keys = set()
        if isinstance(value, dict) and "$SUBCLASS$" in value:
            sub_dict = value["$SUBCLASS$"]
            if isinstance(sub_dict, dict):
                for subkey, subval in sorted(sub_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                    if subkey not in ("$SUBCLASS$", "$OBJECTS$"):
                        entries.append((subkey, subval))
                processed_keys.update(sub_dict.keys())
        if isinstance(value, dict):
            for k, v in sorted(value.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                if k in ("$SUBCLASS$", "$OBJECTS$") or k in processed_keys:
                    continue
                entries.append((k, v))
        return entries

    def build_nodes(key, value, path):
        if isinstance(key, type) and bool(key.__dict__.get('_is_hidden_product_tree_class', False)):
            flattened = []
            for child_key, child_val in iter_child_entries(value):
                flattened.extend(build_nodes(child_key, child_val, path))
            return flattened

        key_str = str(key) if not isinstance(key, type) else key.__name__
        current_path = f"{path}/{key_str}" if path else key_str
        child_nodes = []
        for child_key, child_val in iter_child_entries(value):
            child_nodes.extend(build_nodes(child_key, child_val, current_path))

        has_objects = isinstance(value, dict) and "$OBJECTS$" in value and bool(value["$OBJECTS$"])
        has_subclass = isinstance(value, dict) and "$SUBCLASS$" in value and bool(value["$SUBCLASS$"])
        node = {"title": key_str, "key": current_path, "checkbox": checkbox_default}
        if child_nodes:
            node["folder"] = True
            node["lazy"] = False
            node["children"] = child_nodes
            if not has_objects or has_subclass:
                node["expanded"] = True
            if has_objects:
                node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
                product_folder = {
                    "title": "Product Lists",
                    "key": current_path + "/_products",
                    "folder": True,
                    "lazy": True,
                    "checkbox": False,
                }
                node["children"].insert(0, product_folder)
            else:
                node['checkbox'] = False
        elif has_objects:
            node["folder"] = True
            node["lazy"] = True
            node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
        else:
            node["folder"] = False
            node["lazy"] = False
        return [node]

    top_nodes = []
    for key, value in sorted(tree_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
        if key not in ("$SUBCLASS$", "$OBJECTS$"):
            top_nodes.extend(build_nodes(key, value, ""))
    return top_nodes


def find_node_by_path(tree_dict, path_parts):
    def iter_child_entries(current):
        if not isinstance(current, dict):
            return []
        entries = []
        for key, value in current.items():
            if key in ('$SUBCLASS$', '$OBJECTS$'):
                continue
            entries.append((key, value))
        sub_dict = current.get('$SUBCLASS$')
        if isinstance(sub_dict, dict):
            for key, value in sub_dict.items():
                if key in ('$SUBCLASS$', '$OBJECTS$'):
                    continue
                entries.append((key, value))
        return entries

    def find_child(current, part):
        entries = iter_child_entries(current)
        for key, value in entries:
            key_str = str(key) if not isinstance(key, type) else key.__name__
            if key_str == part:
                return value
        for key, value in entries:
            if isinstance(key, type) and bool(key.__dict__.get('_is_hidden_product_tree_class', False)) and isinstance(value, dict):
                found = find_child(value, part)
                if found is not None:
                    return found
        return None

    flag = False
    original_path_parts = path_parts.copy()
    if len(path_parts) >= 2 and path_parts[-2] == '_products':
        path_parts = path_parts[:-2]
        flag = True
    current = tree_dict
    for part in path_parts:
        if len(current) == 1 and '$OBJECTS$' in current:
            flag = True
            break
        matched = find_child(current, part)
        if matched is None:
            return None
        if not isinstance(matched, dict):
            return None
        current = matched
    if flag:
        assert '$OBJECTS$' in current and isinstance(current['$OBJECTS$'], list), \
            f"路径 {original_path_parts} 指向的节点没有 $OBJECTS$ 列表"
        current = current['$OBJECTS$']
        for obj in current:
            if obj.name == original_path_parts[-1]:
                return obj
        return None
    return current


def get_minimal_paths(paths):
    filtered = [p for p in paths if not p.endswith('/_products')]
    filtered.sort(key=len)
    result = []
    for p in filtered:
        if not any(p.startswith(r + '/') or p == r for r in result):
            result.append(p)
    return result


def _future_code_exchange(future):
    code = str(getattr(future, 'code', '')).upper()
    alias = str(getattr(future, 'alias', getattr(future, 'name', '')))
    exchange = alias.split('.')[1].split('@')[0].upper() if '.' in alias else ''
    return (code, exchange) if code and exchange else None


def _contract_code_exchange(contract, exchange_map):
    name = str(getattr(contract, 'name', getattr(contract, 'alias', contract)))
    if '|' in name:
        parts = name.split('|')
        if len(parts) >= 3:
            exchange = exchange_map.get(parts[0], parts[0]).upper()
            code = parts[2].upper()
            return code, exchange

    match = re.match(r'^([A-Za-z]+)\d+\.?([A-Za-z]+)?', name)
    if match:
        code = match.group(1).upper()
        exchange = exchange_map.get(match.group(2) or '', match.group(2) or '').upper()
        return (code, exchange) if exchange else None
    return None


def build_submission_tree():
    """Single-factor product tree: product categories + CN futures contracts."""
    try:
        from sources.LocalCNFutures.CNFutures import (
            CNFuturesContract,
            CNFuturesDayNightTimeCategory,
            CNFuturesSectorCategory,
            exchange_map,
            get_all_futures_contract,
        )
        from tools.products.Futures import (
            make_contract_category_from_futures_category,
            map_contracts_to_futures,
        )
        from tools.products.Product import Product
        from tools.products.categories.Category import combine_trees

        product_tree = Settings.get_cat_tree()
        contracts = list(get_all_futures_contract())
        futures = Settings.get_all_products()

        contract_to_future = map_contracts_to_futures(
            contracts,
            futures,
            contract_key=lambda c: _contract_code_exchange(c, exchange_map),
            futures_key=_future_code_exchange,
        )

        sector_category = make_contract_category_from_futures_category(
            CNFuturesSectorCategory,
            CNFuturesContract,
            contracts,
            contract_to_future,
        )
        daynight_category = make_contract_category_from_futures_category(
            CNFuturesDayNightTimeCategory,
            CNFuturesContract,
            contracts,
            contract_to_future,
        )
        contract_tree = (sector_category * daynight_category).get_tree_with_parents(
            all_objects=contracts,
            ancester=Product,
        )
        return combine_trees(product_tree, contract_tree).tree
    except Exception:
        return Settings.get_cat_tree().tree


tree = build_submission_tree()
fancytree_cache = None
