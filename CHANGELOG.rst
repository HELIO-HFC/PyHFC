hfcViewer CHANGELOG
-------------------


Version 0.3.0
=============
* Rename the Python package to ``pyhfc`` (the viewer command is still ``hfcviewer``)
* Package the viewer with a pyproject.toml (uv), with a ``hfcviewer`` command
* Support Python 3.12, 3.13 and 3.14, update the dependencies
* New HQI client in the ``pyhfc.api`` sub-package, usable on its own:
  ``HQIClient`` wrapping all the HQI methods (``SQLSelect``, ``Query``,
  ``TimeQuery``, ``getTableNames``, ``getTableFields``), helpers (``nearest``,
  ``previous``, ``next``, ``features``, ``quicklook``), conditions built from
  mappings, typed values, access to the VOTable document and to dictionaries,
  pandas/astropy conversions, and explicit errors (``HQIError``)
* Bundle the XML schema imported by the HQI WSDL, which can not be downloaded
  on Linux (incomplete certificate chain of www.helio-vo.eu)
* Adapt the SQL queries to the PostgreSQL backend of the HFC
* Fix the compatibility with recent numpy, scipy and matplotlib versions
* Fix the data set given on the command line being ignored
* Cache the feature data, and fix the colors by tracking
* Add unit tests (pytest), ruff, mypy and pre-commit configurations
* Add GitLab CI and GitHub Actions pipelines, with test coverage (pytest-cov)
* Publish the package on PyPI (trusted publishing) when a release tag is pushed
  on master, from the GitLab CI and GitHub Actions pipelines
* Add CI status, coverage, Python versions and licence badges to the README
* Distribute under the EUPL-1.2 licence

Version 0.2
===========
* Adapt for Python 3.X
* Add requirements.txt
* Add logging and setup_logging.py modules

Version 0.1
===========
* First release
