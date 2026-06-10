#!/usr/bin/env python3
"""
Setup script for WiFiSense-CLI.

Zero external dependencies - uses only Python standard library.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="wifisense-cli",
    version="0.1.0",
    description="Lightweight Terminal WiFi Signal Intelligence & IoT Event Engine",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="WiFiSense-CLI Contributors",
    license="MIT",
    python_requires=">=3.8",
    packages=find_packages(),
    package_data={
        "wifisense": [],
    },
    include_package_data=True,
    install_requires=[],
    extras_require={
        "dev": [],
    },
    entry_points={
        "console_scripts": [
            "wifisense=wifisense.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Monitoring",
        "Topic :: Utilities",
    ],
    keywords=["wifi", "rssi", "signal", "monitoring", "iot", "cli", "tui"],
)
