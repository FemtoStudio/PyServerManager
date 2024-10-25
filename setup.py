
from setuptools import setup, find_packages

setup(
    name='PyServerManager',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'PySide6==6.5.0',
        'numpy',
    ],
    entry_points={
        'console_scripts': [
            'pyservermanager=server_manager.server_manager:main',  # Adjust if necessary
        ]
    },
    author='Your Name',
    author_email='your.email@example.com',
    description='A tool for monitoring and managing server connections with a GUI',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/pyservermanager',
    classifiers=[
        'Programming Language :: Python :: 3.10',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
)
