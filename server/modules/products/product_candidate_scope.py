"""Apply product picker constraints using the same definition resolver as runs."""

from server.modules.products.product_category_paths import category_tree, resolve_product_scope_paths
from server.modules.products.product_path_selection import _collect_products_from_node
from server.modules.products.product_group_store import load_authoritative_product_groups
from tools.products.classifier_paths import classifier_object_path


def constrain_product_records(rows, *, username, category_ids=(), group_refs=(), product_paths=()):
    allowed = None
    if category_ids:
        allowed = {
            classifier_object_path(product)
            for category_id in category_ids
            for product in _collect_products_from_node(category_tree(category_id, username))
        }
    if group_refs or product_paths:
        groups = {str(group["id"]): group for group in load_authoritative_product_groups(username)}
        group_paths = set(product_paths)
        for ref in group_refs:
            key = ref.removeprefix("product-group:")
            if key not in groups:
                raise ValueError(f"产品组不可用: {ref}")
            group = groups[key]
            group_paths.update(resolve_product_scope_paths(
                group["paths"], username=username, category_ids=group.get("category_ids"),
            ))
        allowed = group_paths if allowed is None else allowed & group_paths
    return [row for row in rows if allowed is None or row.get("product_path") in allowed]
