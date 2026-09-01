from setuptools import find_packages, setup

setup(
    name="ota-marketing-diagnosis",
    version="0.1.0",
    description="Independent third-party OTA marketing diagnosis tool",
    packages=find_packages(),
    include_package_data=True,
    package_data={"marketing_diagnosis": ["templates/*.html"]},
    python_requires=">=3.11",
    install_requires=[
        "openpyxl>=3.1.0",
        "pymysql>=1.1.0",
        "flask>=3.1.0,<4",
        "lark-oapi>=1.7.1,<2",
    ],
    entry_points={"console_scripts": ["ota-marketing-diagnosis=marketing_diagnosis.main:main"]},
)
