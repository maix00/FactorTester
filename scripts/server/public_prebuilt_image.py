#!/usr/bin/env python3
"""Reuse a prepared image only when its immutable release inputs match."""
from __future__ import annotations
import argparse,json,subprocess


def inspect_prepared(image, *, revision, nautilus_revision, python_deps_id, run=subprocess.run):
    result=run(['docker','image','inspect',image],capture_output=True,text=True,timeout=30)
    if result.returncode:
        if 'no such image' in result.stderr.lower() or 'no such object' in result.stderr.lower():
            return None
        raise RuntimeError('cannot inspect prepared image')
    values=json.loads(result.stdout)
    if not isinstance(values,list) or len(values)!=1:
        raise ValueError('prepared image inspection is ambiguous')
    value=values[0];labels=value.get('Config',{}).get('Labels') or {}
    expected={'org.opencontainers.image.revision':revision,
              'org.traderesearch.nautilus.revision':nautilus_revision,
              'org.traderesearch.python-deps.identity':python_deps_id}
    if any(labels.get(key)!=wanted for key,wanted in expected.items()):
        raise ValueError('prepared image does not match the frozen release inputs')
    identity=value.get('Id','')
    if not identity.startswith('sha256:') or len(identity)!=71:
        raise ValueError('prepared image has no immutable image identity')
    return identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('image','revision','nautilus-revision','python-deps-id'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:
        identity=inspect_prepared(args.image,revision=args.revision,nautilus_revision=args.nautilus_revision,python_deps_id=args.python_deps_id)
    except (ValueError,RuntimeError,subprocess.SubprocessError) as error:
        parser.exit(2,str(error)+'\n')
    if identity is None:parser.exit(3)
    print('prepared image verified: '+identity)

if __name__=='__main__':main()
