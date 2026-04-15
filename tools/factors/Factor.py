import pandas as pd
from typing import TYPE_CHECKING, Callable, List, Dict, Optional, Set, Any

from tools import SerialObject, DataFreq
from tools.products.Product import Product
from tools.parameters.Parameter import Parameter
from tools.factors.Parameters import StartCalcPointParam, ReturnFreqParam, FactorNextPeriodReturns

if TYPE_CHECKING:
    from tools.factors.FactorFamily import FactorFamily

class Factor(SerialObject):

    def __new__(cls, alias: Optional[str] = None, single_use: bool = False, *args, **kwargs):
        return super().__new__(cls, type_alias='F', alias=alias, search=True, single_use=single_use)
    
    def __init__(self, alias: Optional[str], func: Callable[..., pd.DataFrame] = lambda _: pd.DataFrame(), 
                 family: Optional[FactorFamily] = None, param_vals: Optional[Dict[Parameter, Any]] = None,
                 single_use: bool = False):
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='F', alias=alias, single_use=single_use)
            self.func = func
            self.min_gap: Optional[pd.Timedelta] = None
            self.freq: Optional[DataFreq] = None
            self.family = family
            
            if param_vals is None:
                assert self.family is not None, "如果没有提供param_vals参数，则必须提供family参数以从中获取默认参数值"
                self.params = self.family.params
            else:
                param_vals = param_vals if param_vals is not None else {}
                self.params = list(param_vals.keys()) if param_vals is not None else []
                for param in self.params:
                    param.register(self, param_vals[param])
            self.params_dict = {param.alias: param for param in self.params}

            self.table: pd.DataFrame = pd.DataFrame()
            self.products: Set[Product] = set()
            self.returns: pd.DataFrame = pd.DataFrame()
            self.ic_series: pd.Series = pd.Series()
            self.ic_stats: pd.Series = pd.Series()
            self.report: pd.DataFrame = pd.DataFrame()

    def clear(self):
        self.table = pd.DataFrame()
        self.products = set()
        self.returns = pd.DataFrame()
        self.ic_series = pd.Series()
        self.ic_stats = pd.Series()
        self.report = pd.DataFrame()

    def get_current_return_freq(self) -> Any:
        return ReturnFreqParam.get_value(self)
    
    def change_current_return_freq(self, return_freq: Any) -> None:
        ReturnFreqParam.register(self, return_freq)

    def get_current_start_calc_point(self) -> Any:
        return StartCalcPointParam.get_value(self)
    
    if TYPE_CHECKING:
        from tools.parameters import DateOrTimeParam
        
    def get_StartCalcPointParam(self) -> DateOrTimeParam:
        return StartCalcPointParam
    
    def change_current_start_calc_point(self, start_calc_point: Any, **kwargs) -> None:
        StartCalcPointParam.register(self, start_calc_point, **kwargs)

    def _set_products(self):
        self.products = set([col for col in self.table.columns if isinstance(col, Product)])

    def get_freq(self, infer: bool = False) -> DataFreq:
        if self.table.empty:
            raise ValueError(f"{self}: 无法获取频率，因为表格为空")
        if infer:
            idx_lvls = len(self.table.index.names)
            series = self.table.index.get_level_values(idx_lvls-1).to_series()
            series = pd.to_datetime(series, errors='coerce').sort_values()
            return DataFreq(series.diff().dropna().mode()[0])
        else:
            signal_index = next((str(name) for name in self.table.index.names if name and str(name).startswith('_SIGNAL')), None)
            if signal_index is None:
                raise ValueError(f"{self}: 无法获取频率，因为没有找到以'_SIGNAL'开头的索引列")
            return DataFreq(signal_index)

    def calc(self, products: Product|List[Product]|Set[Product]) -> pd.DataFrame:
        if isinstance(products, Product):
            products = [products]
        products = list(products)
        if not products:
            raise ValueError(f"{self}: 无法计算，因为没有提供产品")
        if self.family is not None:
            self.family.current_sync_signal_index = None
        self.table = self.func(products)
        if self.table.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")
        col_todrop = [col for col in self.table.columns if (droppedna := self.table[col].dropna()).empty or max(droppedna) == min(droppedna)]
        self.table.drop(columns=col_todrop, inplace=True)
        if self.table.empty:
            raise ValueError(f"{self}: 计算结果为空，请检查func的实现")
        self._set_products()
        self.freq = self.get_freq()
        return self.table
    
    def calc_returns(self, next_return: bool = True, return_freq: Optional[Any] = None,
                     returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED) -> pd.DataFrame:
        if return_freq is not None:
            return_freq = DataFreq(return_freq)
        else:
            if self.freq is None:
                self.freq = self.get_freq()
            return_freq = self.freq
        if self.products is None or not self.products:
            self._set_products()
        assert self.freq is not None, f"{self}: 无法计算收益，因为频率未设置，请先调用calc方法计算因子值以设置频率，或者手动设置频率后再调用本方法"
        start_calc_point = self.get_current_start_calc_point()
        from tools.factors.FactorFamily import ReturnsFamily
        StartCalcPointParam.register(ReturnsFamily, start_calc_point)
        ReturnsFamily.products = self.products
        shift = -1 if returns_col.value.name.startswith('OPEN') else 0
        return_factor = ReturnsFamily.get_factor(RF=return_freq.value, SC=returns_col.value, EC=returns_col.value, S=(shift if next_return else shift + 1))
        StartCalcPointParam.register(return_factor, start_calc_point)
        self.returns = return_factor.calc(self.products)
        return self.returns