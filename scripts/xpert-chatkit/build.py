"""构建固定版本的本地 Xpert UI。依赖缓存与上游 checkout 留在仓库外。"""
import argparse
from pathlib import Path
import shutil
import subprocess
import json
import hashlib
import os

REVISION = '20d26e03db7ca740cac78e5c69a95eb18dbdb613'
ROOT = Path(__file__).resolve().parents[2]

def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, env={**os.environ, "VITE_XPERTAI_API_URL": "/ft-profile-bridge/"})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True, help='固定 SHA 的已安装依赖的上游 checkout')
    parser.add_argument('--pnpm', default='pnpm')
    args = parser.parse_args()
    source = args.source.resolve()
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if actual != REVISION:
        raise SystemExit(f'上游版本不匹配：{actual}')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip():
        raise SystemExit('上游 checkout 必须干净')
    patch = Path(__file__).with_name('host-integration.patch')
    run('git', 'apply', '--check', str(patch), cwd=source)
    run('git', 'apply', str(patch), cwd=source)
    try:
        run(args.pnpm, '--filter', '@xpert-ai/chatkit-ui', 'exec', 'vite', 'build', '--base=./', cwd=source)
    finally:
        run('git', 'apply', '--reverse', str(patch), cwd=source)
    run(args.pnpm, '--filter', '@xpert-ai/chatkit-web-component', 'run', 'build', cwd=source)
    target = ROOT / 'static/vendor/xpert-chatkit'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'packages/chatkit-ui/dist/app', target, dirs_exist_ok=True)
    shutil.copy2(source / 'packages/web-component/dist/xpert-chatkit.umd.cjs', target / 'xpert-chatkit.js')
    shutil.copy2(source / 'LICENSE', target / 'LICENSE')
    bootstrap = Path(__file__).with_name('frame-bootstrap.js').read_bytes()
    bootstrap_name = 'frame-bootstrap-' + hashlib.sha256(bootstrap).hexdigest()[:12] + '.js'
    (target / bootstrap_name).write_bytes(bootstrap)
    theme = Path(__file__).with_name('frame-theme.css').read_bytes()
    theme_name = 'frame-theme-' + hashlib.sha256(theme).hexdigest()[:12] + '.css'
    (target / theme_name).write_bytes(theme)
    index = target / 'index.html'
    index.write_text(index.read_text().replace('<head>', f'<head>\n<script src="./{bootstrap_name}"></script>\n<link rel="stylesheet" href="./{theme_name}">'))
    manifest_path = ROOT / 'server/manager/web/module-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['vendor_assets'] = ['vendor/xpert-chatkit/' + str(p.relative_to(target))
        for p in sorted(target.rglob('*')) if p.is_file()] + ['vendor/xpert-chatkit/UPSTREAM']
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')
    (target / 'UPSTREAM').write_text(f'https://github.com/xpert-ai/chatkit-js\n{REVISION}\n')

if __name__ == '__main__':
    main()
