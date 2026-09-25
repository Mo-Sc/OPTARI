# OPToacoustic imaging toolkit based on napARI

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blue)](https://mo-sc.github.io/OPTARI/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

OPTARI is an open-source, GUI-based desktop application for analyzing clinical photoacoustic/optoacoustic (OA) and ultrasound
(US) studies. It is built on [napari](https://napari.org) for visualization and [PATATO](https://github.com/BohndiekLab/patato)
for data I/O and processing. It runs on Windows, macOS, and Linux, and is intended for direct use in
clinical studies without scripting. Scans are read from iThera `.msot`, PATATO HDF5, and
[IPASC](https://www.ipasc.science) HDF5 files.


**Full documentation, inlcuding instructions, sample workflows, and API references: [mo-sc.github.io/OPTARI](https://mo-sc.github.io/OPTARI/)**.

![Demo Layers](docs/assets/screenshots/placeholders/ss_home.png)


## Key features

- Visualize co-registered US + PA scans from different optoacoustic scanners
- Browse multi-subject, multi-scan studies with fast switching and scrolling through frames/wavelengths.
- Draw, edit, and save ROIs, reuse them via a shareable ROI Library.
- Extract ROI intensities, plot ROI intensities over time and wavelength.
- AI-based tissue segmentation with automatic ROI placement.
- Reconstruction and spectral unmixing using PATATO and DeepMB, directly from the GUI.
- Load iThera `.msot`, PATATO HDF5, and IPASC HDF5 scans.
- Export to CSV/XLSX, open HDF5, IPASC raw data, or PNG/TIFF.


## Quickstart

The easiest way to use OPTARI is by using one of the standalone executables: (todo: link to doc about quick installation)

Alternatively, install from source into a Python 3.12 environment (the PATATO binaries OPTARI depends on are only available for 3.12):

```bash
git clone git@github.com:Mo-Sc/OPTARI.git
cd OPTARI
pip install .
optari
```

## For Development

```bash
git clone git@github.com:Mo-Sc/OPTARI.git
cd OPTARI
pip install -e ".[test,docs]"
pytest                     # run tests
```

To build the docs locally:
```
mkdocs build --no-directory-urls --site-dir optari-docs
```

**Note:** OPTARI currently depends on a custom PATATO fork for compatibility fixes and legacy HDF5 support (see `pyproject.toml`). 
 
To contribute to OPTARI, follow [Contributing](https://mo-sc.github.io/OPTARI/developer-guide/contributing/).

If you find a bug, or have a feature request, [file an issue](https://github.com/Mo-Sc/OPTARI/issues) with a detailed description.

## Citing & License


OPTARI is distributed under the [BSD-3-Clause license](https://github.com/Mo-Sc/OPTARI/blob/main/LICENSE).

If OPTARI is useful in your research, please cite the accompanying paper:

TODO: format
    Schillinger, M., Bader, M., Buehler, A., Wachter, F., Breininger, K. *OPTARI: An open-source software
    framework for clinical translation of optoacoustic imaging.* — citation details to be added once
    published.

