import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="PyServerManager",
    version="0.2.0",
    author="FemtoStudio",
    author_email="info@femtostudio.ca",
    description="An open-source Python tool for server management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/FemtoStudio/PyServerManager.git",
    packages=setuptools.find_packages(),  # Automatically finds all sub-packages
    install_requires=[
        "PySide6>=6.0.0",
        "numpy",
        "tqdm",
        "psutil",
    ],
    entry_points={
        "console_scripts": [
            "pyservermanager=PyServerManager.cli.entrypoints:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
