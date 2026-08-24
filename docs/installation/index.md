# Installation

PATARI is designed to run on Windows, macOS and Linux, without external dependencies or complex installation procedures.

## Option A: Standalone executable (recommended for clinical use)

No Python, no terminal, no admin rights required.

1. Download the executable for your operating system from the
   [latest release](https://github.com/Mo-Sc/PATARI/releases).
2. Unpack the downloaded archive and run the `patari-v` file.
3. **On First run only** — your operating system may warn that the app is unverified, since it isn't signed:
      - **Windows**: click **More info** → **Run anyway**.
      - **macOS**: open **System Settings** → **Privacy & Security**, scroll to Security, then click
        **Open Anyway** next to the "patari was blocked" message.
4. On first launch, PATARI downloads its remaining dependencies — make sure your computer is connected to the
   internet. This can take a few minutes.
5. Once set up, PATARI launches automatically. On later runs, just open the same `patari-v` file again.

!!! note
    Pretrained segmentation models are downloaded automatically the first time you run segmentation (see
    [Segmentation](../user-guide/segmentation.md)) — this also requires an internet connection.

    [DeepMB](../developer-guide/data-and-integrations.md#deepmb-reconstruction) reconstruction weights are available
    from the original authors upon reasonable request and don't come with PATARI by default. If you've been
    provided a download link, they will be downloaded automatically on first run of the reconstruction adapter as
    well.

## Option B: From source (recommended for development)

```bash
git clone git@github.com:Mo-Sc/PATARI.git
cd PATARI
pip install -e .
```

Then launch PATARI either via its installed entry point:

```bash
patari
```

or as a module:

```bash
python -m patari.launcher
```

See [Contributing](../developer-guide/contributing.md) for detailed information.

## Uninstalling

To remove PATARI from your computer:

- **Windows**: run `UNINSTALL_WINDOWS.bat`, included next to `patari.exe` in your release download. It runs
  `patari.exe self remove` for you — no manual command needed.
- **macOS**: open Terminal (`Cmd + Space`, then type `Terminal`), drag and drop the `patari-v...` file into the
  Terminal window, type ` self remove` (don't forget the leading space), then press Enter.

You successfully removed PATARI from your system.

You can delete the downloaded executable/folder. PATARI also stores your configuration, presets, downloaded models, and
logs in a `.patari` folder in your home directory. Remove it too if you want a completely clean uninstall (or reset your user settings). See
[Configuration](../configuration/index.md) for more information on the `.patari` folder.
