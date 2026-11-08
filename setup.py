import os
import setuptools


def read(filename):
    with open(os.path.join(os.path.dirname(__file__), filename), encoding="utf-8") as source:
        return source.read()


setuptools.setup(
    name="self-healing-whois",
    version="0.1.1",
    description="A python-whois fork with validated, LLM-assisted expiration parser repair.",
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP",
        "Programming Language :: Python :: 3",
    ],
    keywords="whois, python",
    author="self-healing-whois contributors; upstream python-whois contributors",
    project_urls={"Upstream": "https://github.com/richardpenman/whois"},
    license="MIT",
    packages=["self_healing_whois"],
    package_dir={"self_healing_whois": "self_healing_whois"},
    package_data={"self_healing_whois": ["healing_corpus.json", "data/public_suffix_list.dat"]},
    install_requires=["python-dateutil"],
    python_requires=">=3.12",
    extras_require={"dev": ["pytest", "build", "twine"]},
    include_package_data=True,
    zip_safe=False,
)
