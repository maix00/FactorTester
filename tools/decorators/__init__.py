"""Decorator entry points only.

Helper/AST utilities stay in the corresponding submodules so import paths
preserve the semantic boundary of each decorator family.
"""

FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from .factor_workspace import factor_workspace
