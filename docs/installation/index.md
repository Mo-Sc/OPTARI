# Installation

OPTARI is designed to run on Windows, macOS and Linux, without external dependencies or complex installation procedures.

## Option A: Standalone executable (recommended for clinical use)

No Python, no terminal, no admin rights required.

1. Download the executable for your operating system:

    <!-- TODO: replace with the release download links -->
    [:fontawesome-brands-apple: macOS (Apple Silicon)](#){ .md-button }
    [:fontawesome-brands-windows: Windows](#){ .md-button }
    [:fontawesome-brands-linux: Linux](#){ .md-button }

    Older versions are listed on the [releases page](https://github.com/Mo-Sc/OPTARI/releases).

2. Unpack the downloaded archive and run the `optari-v` file.
3. **On First run only** — your operating system may warn that the app is unverified, since it isn't signed:
      - **Windows**: click **More info** → **Run anyway**.
      - **macOS**: open **System Settings** → **Privacy & Security**, scroll to Security, then click
        **Open Anyway** next to the "optari was blocked" message.
      - **Linux**: Run `chmod +x optari-v...` in the terminal to make the file executable.
4. On first launch, OPTARI downloads its remaining dependencies — make sure your computer is connected to the
   internet. **This can take a few minutes**.
5. Once set up, OPTARI launches automatically. On later runs, just open the same `optari-v` file again.

!!! note
    Pretrained segmentation models are downloaded automatically the first time you run segmentation (see
    [Segmentation](../user-guide/segmentation.md)) — this also requires an internet connection.

    [DeepMB](../developer-guide/data-and-integrations.md#deepmb-reconstruction) reconstruction weights are available
    from the original authors upon reasonable request and don't come with OPTARI by default. If you've been
    provided a download link, they will be downloaded automatically on first run of the reconstruction adapter as
    well.

## Option B: From source (recommended for development)

Installing from source into a Python 3.12 environment (the PATATO binaries OPTARI depends on are only available for 3.12):

```bash
git clone git@github.com:Mo-Sc/OPTARI.git
cd OPTARI
pip install -e .
```

Then launch OPTARI either via its installed entry point:

```bash
optari
```

or as a module:

```bash
python -m optari.launcher
```

See [Contributing](../developer-guide/contributing.md) for detailed information.

## Uninstalling

To remove OPTARI from your computer:

- **Windows**: run `UNINSTALL_WINDOWS.bat`, included next to `optari.exe` in your release download. It runs
  `optari.exe self remove` for you — no manual command needed.
- **macOS**: open Terminal (`Cmd + Space`, then type `Terminal`), drag and drop the `optari-v...` file into the
  Terminal window, type ` self remove` (don't forget the leading space), then press Enter.
- **Linux**: in a terminal next to the file, run `./optari-v... self remove` (with the full file name).

You successfully removed OPTARI from your system.

You can delete the downloaded executable/folder. OPTARI also stores your configuration, presets, downloaded models, and
logs in a `.optari` folder in your home directory. Remove it too if you want a completely clean uninstall (or reset your user settings). See
[Configuration](../configuration/index.md) for more information on the `.optari` folder.
