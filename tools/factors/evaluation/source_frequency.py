"""One source-frequency decision for coverage checks and factor execution."""
from tools.data.types import DataFreq


def resolve_source_frequency(factor, products, freq=None):
    if freq is not None:
        return DataFreq(freq)
    family = getattr(factor, 'family', None)
    declared = (getattr(family, '_source_freq', None)
                or getattr(family, 'source_freq', None)
                or getattr(family, '_freq_name', None))
    if declared is not None:
        return DataFreq(declared)
    if not products:
        raise ValueError(f'{factor}: 无法推断数据频率，因为没有提供产品')
    desired = set()
    for reference in getattr(getattr(factor, '_expr', None), 'const_refs', ()):
        try:
            desired.add(DataFreq(reference.value))
        except (TypeError, ValueError):
            continue
    output = getattr(factor, 'freq', None)
    if output is not None:
        desired.add(DataFreq(output))
    def compatible(candidate):
        seconds = candidate.value.total_seconds()
        return seconds > 0 and all(value.value.total_seconds() % seconds == 0 for value in desired)
    common = None
    for product in products:
        available = {DataFreq(value) for value in product.list_available_freqs()}
        if not available or not any(compatible(value) for value in available):
            continue
        common = available if common is None else common & available
    available = sorted(common or (), key=lambda value: value.value, reverse=True)
    if not available:
        raise ValueError(f'{factor}: 产品数据没有公共可用频率，无法确定数据频率')
    if not desired:
        return available[-1]
    selected = next((value for value in available if compatible(value)), None)
    if selected is None:
        raise ValueError(f'{factor}: 期望频率与产品可用频率不兼容，无法确定数据频率')
    return selected
