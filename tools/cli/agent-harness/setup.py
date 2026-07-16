from __future__ import annotations

from setuptools import find_namespace_packages, setup


setup(
    name="cli-anything-factortester-research",
    version="0.1.0",
    description="CLI-Anything harness for FactorTester factor research workflows",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    package_data={
        "cli_anything.factortester_research": ["skills/*.md"],
    },
    install_requires=["click>=8.0"],
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "cli-anything-factortester-research=cli_anything.factortester_research.factortester_research_cli:cli",
        ],
    },
)
