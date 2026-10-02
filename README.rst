PyHFC
-----

.. image:: https://github.com/HELIO-HFC/PyHFC/actions/workflows/ci.yml/badge.svg?branch=develop
   :target: https://github.com/HELIO-HFC/PyHFC/actions/workflows/ci.yml?query=branch%3Adevelop
   :alt: CI status

.. image:: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/HELIO-HFC/PyHFC/badges/coverage.json
   :target: https://github.com/HELIO-HFC/PyHFC/actions/workflows/ci.yml?query=branch%3Adevelop
   :alt: Coverage

.. image:: https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue
   :alt: Python versions

.. image:: https://img.shields.io/github/license/HELIO-HFC/PyHFC
   :target: https://github.com/HELIO-HFC/PyHFC/blob/develop/LICENSE
   :alt: License

``pyhfc`` is a Python package for the users of the HELIO Heliophysics Feature
Catalogue (HFC). It provides:

- ``pyhfc.api``, a Python client of the HELIO Query Interface (HQI) of the HFC,
  usable on its own to query the catalogue;
- ``pyhfc.hfcviewer``, a graphical viewer of the HFC observations and features,
  run with the ``hfcviewer`` command;
- ``pyhfc.improlib``, image processing routines (e.g. to decode the chain codes
  of the feature contours).

Visit http://voparis-helio.obspm.fr/hfc-gui/ for more information about the HFC.

PyHFC requires Python 3.12, 3.13 or 3.14 (with Tkinter for the viewer).


INSTALLATION
============

The project is managed with `uv <https://docs.astral.sh/uv/>`_.

To install the ``hfcviewer`` command, run::

    uv tool install .

To use the HQI client in your own project, add it as a dependency, optionally
with the ``pandas`` and/or ``astropy`` extras::

    uv add "pyhfc[pandas,astropy]"

or, with pip::

    pip install "pyhfc[pandas,astropy]"

To use the development version, install it from the ``develop`` branch::

    uv add "pyhfc @ git+https://github.com/HELIO-HFC/PyHFC.git@develop"

To set up a development environment, run::

    uv sync


VIEWER
======

To run the hfcViewer, enter::

    uv run hfcviewer

or, equivalently::

    uv run python -m pyhfc.hfcviewer

By default, the viewer displays the most recent SDO/AIA observation at the
current date and time, with the active regions and the coronal holes detected
on it (note that the HFC has no coronal holes after 2013-10-13). The *Previous*
and *Next* buttons browse the observations of the selected data set, and the
*Latest* button goes back to its most recent observation.

For instance, to display the Meudon H-alpha observation nearest to a date,
with the filaments and the prominences::

    uv run hfcviewer -d 2012-06-01T12:00:00 -o Meudon -i Spectroheliograph -w Halpha -f fi,pr

The features to display are given with ``-f`` (``ar``: active regions, ``ch``:
coronal holes, ``sp``: sunspots, ``rs``: radio sources, ``pr``: prominences,
``fi``: filaments; ``-f ""`` for none).

By default, the contours of a feature are the ones detected at the date closest
to the date t of the displayed observation. A time range dt can be set for each
feature in *Options > Set time ranges*: the contours detected in [t - dt, t + dt]
are then all displayed on the same image, e.g. to follow the evolution of the
active regions. The contours are then colored by tracking by default (a feature
keeps its color from one observation to the other); *Contour colors* allows to
color them by feature again.

The status bar shows two lights telling whether the HQI service (observations
and features) and the server of the quicklook images (FTP) are reachable (green)
or not (red). They are checked every minute, in the background; the interval
can be changed in the *Settings* menu (*Server checks*). The version of pyhfc, at
the right of the status bar, is a link to its PyPI page, and the LIRA logo a link
to the LIRA website. *Help > HFC database content* opens the web page giving the
content of the HFC database (observations and features available).

The quicklook images, and the data returned by the HQI (observations and
features), are kept in a disk cache, so that they are displayed faster the next
times (about 7 times faster for SDO/AIA images). The data of the last 7 days are
cached for one hour only, as the HFC may still complete them, and the most recent
observation (*Latest* button) is always queried. 50 SDO/AIA images with their
active regions take about 50 MB. The cache is stored in the user cache directory
(``~/Library/Caches/pyhfc`` on macOS, ``~/.cache/pyhfc`` on Linux; set the
``PYHFC_CACHE_DIR`` environment variable to use another directory). Its maximum
size is 500 MB by default (about 500 SDO/AIA images): it can be changed, and
the cache emptied, in the *Settings* menu. When the cache is full, the viewer
says it, and the new images and data are no longer cached.

To display help, run::

    uv run hfcviewer --help

Note: some old uv-managed Python builds (e.g. 3.12.12, 3.14.2) cannot load
Tcl/Tk ("Can't find a usable init.tcl"); install a newer patch release with
``uv python install``.


HQI CLIENT
==========

The HFC is queried through the HELIO Query Interface (HQI), a SOAP web service
returning VOTables. ``pyhfc.api.HQIClient`` wraps all its methods:

=====================================  ====================  ================================================
Client method                          HQI method            Description
=====================================  ====================  ================================================
``tables()``                           ``getTableNames``     Names of the tables of the HFC
``fields(table)``                      ``getTableFields``    Names of the fields of a table
``select(table, what, where, ...)``    ``SQLSelect``         SQL query (``WHAT``, ``WHERE``, ``ORDER BY``...)
``time_query(table, start, end)``      ``TimeQuery``         Rows observed between two dates
``query(table, start, end, where)``    ``Query``             Rows observed between two dates, with conditions
``call(method, **params)``             any                   Raw call of any method of the service
=====================================  ====================  ================================================

and adds a few helpers:

- ``nearest(table, date)``, ``previous(table, date)``, ``next(table, date)``:
  the row observed nearest to, before or after a date;
- ``features(feature, start, end)``: the features ("active regions",
  "sunspots", "filaments", "prominences", "coronal holes", "type III"...)
  observed between two dates;
- ``quicklook(row)``: the quicklook image (PIL) of an observation.

The main tables are ``VIEW_OBS_HQI`` (observations), ``VIEW_PP_HQI``
(pre-processed observations), ``VIEW_AR_HQI`` (active regions), ``VIEW_SP_HQI``
(sunspots), ``VIEW_CH_HQI`` (coronal holes), ``VIEW_FIL_HQI`` (filaments),
``VIEW_PRO_HQI`` (prominences), ``VIEW_RS_HQI`` (radio sources), ``VIEW_T2_HQI``
and ``VIEW_T3_HQI`` (type II and III radio bursts), and ``FRC_INFO`` (feature
recognition codes).

Conditions
~~~~~~~~~~

The ``where`` arguments accept either a raw string, or a mapping
``{field: condition}`` (conditions are combined with AND):

=========================  ================================  =========================
Condition                  ``select`` (SQL)                  ``query`` (HQI syntax)
=========================  ================================  =========================
``"SDO"``                  ``OBSERVAT = 'SDO'``              ``OBSERVAT,SDO``
``(10, 50)``               ``AREA BETWEEN 10 AND 50``        ``AREA,10/50``
``(10, None)``             ``AREA >= 10``                    ``AREA,10/``
``["SDO", "SOHO"]``        ``OBSERVAT IN ('SDO', 'SOHO')``   ``OBSERVAT,SDO,SOHO``
``None``                   ``NOAA_NUMBER IS NULL``           (not supported)
=========================  ================================  =========================

Dates can be given as ``datetime`` objects or ISO 8601 strings
(``"2012-06-01"``, ``"2012-06-01T12:00:00"``).

Beware: string comparisons are case-sensitive, and most of the HFC values are
upper-case (``OBSERVAT = 'SDO'``, ``INSTRUME = 'HMI'``, ``TELESCOP = 'CONTINUUM'``...).
Use ``hqi.select(table, what="DISTINCT OBSERVAT, INSTRUME")`` to list them.

Responses
~~~~~~~~~

The query methods return a ``QueryResponse``, which gives access to:

- the rows, as dictionaries ``{FIELD: value}`` (field names are upper-cased):
  iterate on the response, or use ``response.rows``, ``response.first()``,
  ``response[0]``, ``len(response)``;
- the tables (``response.tables``, ``response.table("VIEW_AR_HQI")``), with their
  fields description (``table.fields``: name, datatype, unit, ucd, null value);
- the information returned by the service (``response.status``,
  ``response.query_string``, ``response.info``);
- the original VOTable document (``response.votable``, ``response.save(path)``);
- the whole VOTable as a dictionary (``response.to_dict()``), or as returned by
  the former client (``response.header`` and ``response.tabledata``);
- a pandas DataFrame (``response.to_pandas()``) or an astropy Table
  (``response.to_astropy()``), if pandas or astropy are installed.

By default, the values are converted according to the VOTable datatypes
(``int``, ``float``, ``datetime`` for the dates, ``None`` for the null values).
Use ``HQIClient(typed=False)`` to keep them as strings, as returned by the
service, or ``HQIClient(parse_dates=False)`` to only keep the dates as strings.

The errors raise a ``HQIError``: ``HQIConnectionError`` if the service can not
be reached, ``HQIQueryError`` if the query has failed (e.g. invalid SQL).

Examples
~~~~~~~~

List the tables of the HFC and the fields of a table::

    from pyhfc.api import HQIClient

    hqi = HQIClient()
    print(hqi.tables())
    print(hqi.fields("VIEW_AR_HQI"))

Get the SDO/HMI continuum observation nearest to a date, and save its quicklook image::

    obs = hqi.nearest(
        "VIEW_OBS_HQI",
        "2012-06-01T12:00:00",
        where={"OBSERVAT": "SDO", "INSTRUME": "HMI", "TELESCOP": "CONTINUUM"},
    )
    print(obs["DATE_OBS"], obs["NAXIS1"], obs["CDELT1"], obs["QCLK_FNAME"])
    hqi.quicklook(obs).save("hmi.png")

Get the positions of the NOAA active regions detected on SDO images during a day::

    ars = hqi.select(
        "VIEW_AR_HQI",
        what="DATE_OBS, NOAA_NUMBER, FEAT_HG_LAT_DEG, FEAT_HG_LONG_DEG, FEAT_AREA_DEG2",
        where={
            "OBSERVAT": "SDO",
            "NOAA_NUMBER": (1, None),
            "DATE_OBS": ("2012-06-01", "2012-06-02"),
        },
        order_by="DATE_OBS, NOAA_NUMBER",
    )
    for row in ars:
        print(row["DATE_OBS"], row["NOAA_NUMBER"], row["FEAT_HG_LAT_DEG"], row["FEAT_HG_LONG_DEG"])

Get the sunspots detected on SDO images as a pandas DataFrame::

    spots = hqi.features(
        "sunspots", "2012-06-01T00:00:00", "2012-06-01T12:00:00", where={"OBSERVAT": "SDO"}
    )
    df = spots.to_pandas()
    print(df[["DATE_OBS", "FEAT_X_ARCSEC", "FEAT_Y_ARCSEC", "FEAT_AREA_DEG2"]])

Use the HQI ``Query`` method to get the large active regions (more than 50 square degrees)::

    big = hqi.query(
        "VIEW_AR_HQI",
        "2012-06-01T00:00:00",
        "2012-06-02T00:00:00",
        where={"OBSERVAT": "SDO", "FEAT_AREA_DEG2": (50, None)},
    )
    print({row["NOAA_NUMBER"] for row in big})

Count the type III radio bursts detected in 2010 (SQL functions can be used)::

    count = hqi.select(
        "VIEW_T3_HQI", what="COUNT(*) AS N", where={"DATE_OBS": ("2010-01-01", "2011-01-01")}
    )
    print(count.first()["N"])

Follow the evolution of a tracked filament::

    filament = hqi.features(
        "filaments", "2011-06-01", "2011-06-02", what="TRACK_ID", where="TRACK_ID > 0", limit=1
    ).first()
    track = hqi.select(
        "VIEW_FIL_HQI",
        what="DATE_OBS, FEAT_HG_LAT_DEG, FEAT_HG_LONG_DEG, SKE_LENGTH_DEG",
        where={"TRACK_ID": filament["TRACK_ID"]},
        order_by="DATE_OBS",
    )

Read a large result page by page (``limit`` and ``offset``)::

    offset = 0
    while True:
        page = hqi.select(
            "VIEW_SP_HQI",
            what="DATE_OBS, FEAT_AREA_DEG2",
            where={"DATE_OBS": ("2012-06-01", "2012-06-02")},
            order_by="DATE_OBS",
            limit=1000,
            offset=offset,
        )
        ...  # process page.rows
        if len(page) < 1000:
            break
        offset += 1000

Save the VOTable, or convert it to a dictionary or to an astropy Table::

    response = hqi.select("VIEW_AR_HQI", what="DATE_OBS, R_SUN", limit=3)
    response.save("result.xml")
    data = response.to_dict()  # {"description", "info", "tables": [{"name", "fields", "rows"}]}
    table = response.to_astropy()

Handle the errors::

    from pyhfc.api import HQIError

    try:
        hqi.select("VIEW_AR_HQI", where="NO_SUCH_FIELD = 1")
    except HQIError as err:
        print(err)


DEVELOPMENT
===========

Install the git hooks (ruff, mypy, gitleaks...)::

    uv run pre-commit install

Run the checks and the tests::

    uv run pre-commit run --all-files
    uv run pytest

Tests querying the live HFC web service are deselected by default, run them with::

    uv run pytest -m network

The continuous integration runs the checks and the tests on Python 3.12, 3.13
and 3.14, then builds the package. It is available for GitLab (``.gitlab-ci.yml``)
and GitHub Actions (``.github/workflows/ci.yml``), and is triggered from the web
interface, through the API, or when a tag is pushed. On GitHub, it can be
triggered through the API with a ``workflow_dispatch`` event, or a
``repository_dispatch`` event of type ``ci``::

    gh workflow run ci.yml --ref develop

The development is done on the ``develop`` branch; the ``master`` branch only
receives the tagged releases of the package.

The badges at the top of this file give the status of the last GitHub Actions
run on the ``develop`` branch, the coverage of the tests on this branch, the
tested Python versions and the licence. The coverage badge is updated by the CI runs on
``develop``, which push a ``coverage.json`` file to the ``badges`` branch. The
Python versions of the badge must be the ones of the ``pyproject.toml``
classifiers and of the CI matrices (this is checked by the tests). On GitLab,
the pipeline and coverage badges can be added in *Settings > General > Badges*.


RELEASES
========

The development is done on ``develop``; the ``master`` branch only receives the
releases. To publish a new version of ``pyhfc`` on `PyPI <https://pypi.org/project/pyhfc/>`_:

1. update the version (e.g. ``uv version --bump minor``) and the ``CHANGELOG.rst``
   on ``develop``;
2. merge ``develop`` into ``master``;
3. tag the merge commit on ``master`` with the version, and push the tag::

       git tag v0.3.0
       git push origin v0.3.0

The CI then runs the checks and the tests, builds the package and publishes it
(``publish-pypi`` job). The publication is refused if the tag (``X.Y.Z`` or
``vX.Y.Z``) does not match the version of the package, or if the tagged commit is
not on ``master`` (see ``ci/check-release.sh``). The files already on PyPI are
skipped, so the GitHub and GitLab pipelines can both run on the same tag.

The publication uses the `trusted publishing
<https://docs.pypi.org/trusted-publishers/>`_ of PyPI: no token is stored in the
CI, PyPI trusts the CI pipelines declared for the project. This must be
configured once on PyPI:

- before the first release (the ``pyhfc`` project does not exist yet on PyPI), add
  a *pending publisher* in *Your account > Publishing*, with the project name
  ``pyhfc`` and, for GitHub: owner ``HELIO-HFC`` (the organization, not a user),
  repository ``PyHFC`` (the name only, not its url), workflow ``ci.yml``,
  environment ``pypi``; the first release then creates the project;
- for GitLab, add a publisher in the *Publishing* settings of the ``pyhfc``
  project once it exists (or as the pending publisher, if the first release is
  made from GitLab), with the GitLab namespace and project, the top-level
  pipeline file ``.gitlab-ci.yml`` and the environment ``pypi``.

On GitHub, protection rules (e.g. a required reviewer) can be added to the ``pypi``
environment in *Settings > Environments*, to approve each publication.


LICENSE
=======

PyHFC is distributed under the European Union Public Licence v1.2
(EUPL-1.2), see the ``LICENSE`` file.


CONTACT
=======

xavier.bonnin@obspm.fr
