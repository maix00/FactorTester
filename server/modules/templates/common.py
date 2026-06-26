"""Shared helpers for template routes."""

from server.modules.shared.factor_param_utils import factor_param_value_display
from tools.data.account_manage import load_user_templates, new_template_id, save_user_templates


SINGLE_FACTOR_SETTING_TEMPLATE_KIND = 'global'


def build_factor_rows(factor_family, params_list):
    factors = factor_family.get_factors(params_list=params_list)
    rows = []
    for idx, (factor, row) in enumerate(zip(factors, params_list)):
        display_params = {}
        for param in factor_family.params:
            value = row.get(param.alias)
            display_params[param.alias] = factor_param_value_display(param, value)
        rows.append({
            'index': idx,
            'factor_alias': factor.alias,
            'params': display_params,
        })
    return rows


load_template_list = load_user_templates
save_template_list = save_user_templates
new_template_id = new_template_id
