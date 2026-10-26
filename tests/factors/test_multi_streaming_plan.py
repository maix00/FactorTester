import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.streaming.incremental import (
    compile_incremental_factor,
    compile_incremental_factors,
)


def _stamps(n):
    return [
        pd.Timestamp('2026-01-05 09:31') + pd.Timedelta(minutes=i)
        for i in range(n)
    ]


def test_multi_factor_streaming_shares_intermediate_state():
    close = ColumnRef(DataColumn.CLOSE)
    first = close.rolling(3).mean()
    second = first.rolling(2).std()
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    single_first = compile_incremental_factor(
        'first', first, ('A',), source_freq=DataFreq.MIN1,
    )
    single_second = compile_incremental_factor(
        'second', second, ('A',), source_freq=DataFreq.MIN1,
    )
    multi = compile_incremental_factors(
        {'first': first, 'second': second}, ('A',), source_freq=DataFreq.MIN1,
    )
    for stamp, value in zip(_stamps(len(values)), values, strict=True):
        fields = {'A': {DataColumn.CLOSE.name: value}}
        single_first.on_bar(stamp, fields)
        single_second.on_bar(stamp, fields)
        multi.on_bar(stamp, fields)
    expected = {
        'first': single_first.on_signal(stamp)['A'],
        'second': single_second.on_signal(stamp)['A'],
    }
    actual = multi.on_signal(stamp)
    assert actual['first']['A'] == expected['first']
    assert actual['second']['A'] == expected['second']
