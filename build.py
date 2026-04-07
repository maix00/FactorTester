#!/usr/bin/env python3
"""
跨平台打包脚本 - 使用 PyInstaller 统一打包
- macOS: 生成 .app
- Windows: 生成 .exe
"""

import os
import sys
import platform
import subprocess
import shutil
import glob

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIRS = ['templates', 'static']
HIDDEN_IMPORTS = ['importlib', 'webbrowser', 'threading', 'Settings', 'Factor', 'Products', 'tkinter']

def clean_build_dirs():
    for d in ['build', 'dist']:
        path = os.path.join(ROOT_DIR, d)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
    for f in glob.glob(os.path.join(ROOT_DIR, '*.spec')):
        os.remove(f)

def build_mac():
    print("\n=== 使用 PyInstaller 打包 macOS .app ===\n")
    
    # 检查 PyInstaller 是否安装
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未安装 PyInstaller，请运行: pip install pyinstaller")
        sys.exit(1)

    # 路径分隔符（macOS 使用冒号）
    sep = ':'
    
    # 基础命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'FactorTester',
        '--windowed',               # 无控制台，生成 .app
        '--onedir',                 # 生成目录（macOS 下 --windowed 会自动生成 .app bundle）
        '--noconfirm',              # 覆盖输出目录
        '--clean',                  # 清理临时文件
    ]

    # ========== 添加资源目录 ==========
    # templates 和 static 是前端资源
    cmd.extend([
        '--add-data', f'templates{sep}templates',
        '--add-data', f'static{sep}static',
    ])

    # utils 目录（包含 path_manager.py 等）
    if os.path.exists('utils'):
        cmd.extend(['--add-data', f'utils{sep}utils'])

    # ========== 添加 Python 模块文件（作为数据文件，确保它们能被导入）==========
    # 这些文件需要放在 .app 内部的根目录，以便直接导入
    python_files = [
        'factor_server.py',
        'CNFutures.py',
        'Factor.py',
        'Products.py',
        'Settings.py',
        'Tools.py',
        'Category.py',
        # 如果还有其他自定义模块，继续添加
    ]
    for pyf in python_files:
        if os.path.exists(pyf):
            cmd.extend(['--add-data', f'{pyf}{sep}.'])

    # ========== 隐藏导入（防止模块遗漏）==========
    hidden_imports = [
        'importlib',
        'webbrowser',
        'threading',
        'socket',
        'logging',
        'tkinter',                  # 用于弹窗选择数据目录
        'utils.path_manager',       # 自定义路径管理模块
        # 你可能还需要其他依赖，例如：
        # 'pandas',
        # 'numpy',
        # 'flask',
    ]
    for mod in hidden_imports:
        cmd.append(f'--hidden-import={mod}')

    # ========== 入口脚本 ==========
    # 使用 launcher.py 作为入口，它负责启动 Flask 和打开浏览器
    if not os.path.exists('launcher.py'):
        print("错误: 找不到 launcher.py，请确保它在项目根目录")
        sys.exit(1)
    cmd.append('launcher.py')

    # 打印命令（便于调试）
    print("执行命令:")
    print(' '.join(cmd))
    print()

    # 执行打包
    try:
        subprocess.run(cmd, cwd=ROOT_DIR, check=True)
        app_path = os.path.join(ROOT_DIR, 'dist', 'FactorTester.app')
        if os.path.exists(app_path):
            print(f"\n✅ 打包成功！应用位于: {app_path}")
            # 自动打开 dist 文件夹
            subprocess.run(['open', os.path.join(ROOT_DIR, 'dist')])
        else:
            print("\n⚠️ 打包完成但未找到 .app，请检查 dist 目录")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")
        
def build_windows():
    print("\n=== 使用 PyInstaller 打包 Windows .exe ===\n")
    try:
        import PyInstaller
    except ImportError:
        print("错误: 未安装 PyInstaller，请运行: pip install pyinstaller")
        sys.exit(1)

    sep = ';'
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', 'FactorTester',
        '--onefile',
        '--windowed',
        '--noconfirm',
        '--clean',
        '--add-data', f'templates{sep}templates',
        '--add-data', f'static{sep}static',
    ]
    for mod in HIDDEN_IMPORTS:
        cmd.append(f'--hidden-import={mod}')
    cmd.append('factor_server.py')

    print("执行命令:", ' '.join(cmd))
    try:
        subprocess.run(cmd, cwd=ROOT_DIR, check=True)
        exe_path = os.path.join(ROOT_DIR, 'dist', 'FactorTester.exe')
        print(f"\n✅ 打包成功！可执行文件: {exe_path}")
        subprocess.run(['explorer', os.path.join(ROOT_DIR, 'dist')])
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 打包失败: {e}")

def main():
    system = platform.system()
    print(f"检测到操作系统: {system}")
    print(f"Python 解释器: {sys.executable}")
    clean_build_dirs()

    if system == 'Darwin':
        build_mac()
    elif system == 'Windows':
        build_windows()
    else:
        print(f"不支持的操作系统: {system}，仅支持 macOS (Darwin) 和 Windows")

if __name__ == '__main__':
    main()