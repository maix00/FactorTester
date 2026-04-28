"""
multi_factor_analysis Blueprint package.

  correlation.py  — 因子相关性矩阵 (Spearman + Pearson)
  combination.py  — 因子合成回测 (等权/IC加权/IR加权/最大夏普/最小方差/风险平价)
  heatmap.py      — 因子 IC 热力图 (按月/季度，mean_ic/cum_ic/ir)
  hierarchy.py    — 因子分层回测 (先按A分组，再在每个A组内按B分组)
"""
from flask import Blueprint

mfa_bp = Blueprint('mfa', __name__)

from . import correlation   # noqa: E402, F401
from . import combination   # noqa: E402, F401
from . import heatmap       # noqa: E402, F401
from . import hierarchy     # noqa: E402, F401
