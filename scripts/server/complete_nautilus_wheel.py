"""Complete a composed wheel using pinned Python sources; wheel owns RECORD."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import tempfile
from wheel.cli.pack import pack
from wheel.cli.unpack import unpack


def complete(wheel:Path,source:Path):
    with tempfile.TemporaryDirectory(prefix='.package-',dir=wheel.parent) as temporary:
        root=Path(temporary);unpack(str(wheel),str(root))
        tree=next(p for p in root.iterdir() if p.is_dir())
        package=tree/'nautilus_trader';package.mkdir(exist_ok=True)
        for item in source.rglob('*'):
            if not item.is_file() or '__pycache__' in item.parts or item.suffix in {'.so','.pyc','.pyd'}:continue
            target=package/item.relative_to(source)
            # Generated type stubs already supplied by the compiler win.
            if target.exists() and item.suffix!='.py':continue
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(item,target)
        required=['__init__.py','_fixup.py','backtest/__init__.py','analysis/tearsheet.py']
        if any(not (package/name).is_file() for name in required):raise ValueError('incomplete pinned Nautilus Python source')
        output=root/'packed';output.mkdir();pack(str(tree),str(output),None)
        result=next(output.glob('*.whl'))
        if result.name!=wheel.name:raise ValueError('wheel identity changed during Python packaging')
        result.replace(wheel)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--wheel',type=Path,required=True);parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();complete(args.wheel,args.source)
