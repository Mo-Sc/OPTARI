"""
This module is an example of a barebones numpy reader plugin for napari.

It implements the Reader specification, but your plugin may choose to
implement multiple readers or even other plugin contributions. see:
https://napari.org/stable/plugins/building_a_plugin/guides.html#readers
"""

import numpy as np
import patato as pat


def napari_get_reader(path):
    """A basic implementation of a Reader contribution.

    Parameters
    ----------
    path : str or list of str
        Path to file, or list of paths.

    Returns
    -------
    function or None
        If the path is a recognized format, return a function that accepts the
        same path or list of paths, and returns a list of layer data tuples.
    """
    if isinstance(path, list):
        # reader plugins may be handed single path, or a list of paths.
        # if it is a list, it is assumed to be an image stack...
        # so we are only going to look at the first file.
        path = path[0]

    if path.endswith(".npy"):
        return sample_reader_function
    elif path.endswith(".hdf5"):
        return patato_reader_function
    else:
        return None


def sample_reader_function(path):
    """Take a path or list of paths and return a list of LayerData tuples.

    Readers are expected to return data as a list of tuples, where each tuple
    is (data, [add_kwargs, [layer_type]]), "add_kwargs" and "layer_type" are
    both optional.

    Parameters
    ----------
    path : str or list of str
        Path to file, or list of paths.

    Returns
    -------
    layer_data : list of tuples
        A list of LayerData tuples where each tuple in the list contains
        (data, metadata, layer_type), where data is a numpy array, metadata is
        a dict of keyword arguments for the corresponding viewer.add_* method
        in napari, and layer_type is a lower-case string naming the type of
        layer. Both "meta", and "layer_type" are optional. napari will
        default to layer_type=="image" if not provided
    """
    # handle both a string and a list of strings
    paths = [path] if isinstance(path, str) else path
    # load all files into array
    arrays = [np.load(_path) for _path in paths]
    # stack arrays into single array
    data = np.squeeze(np.stack(arrays))

    # optional kwargs for the corresponding viewer.add_* method
    add_kwargs = {}

    layer_type = "image"  # optional, default is "image"
    return [(data, add_kwargs, layer_type)]


def patato_reader_function(path):
    """
    NAPARI compatible reader for PATATO HDF5 files.

    Take a path or list of paths and return a list of LayerData tuples.

    Readers are expected to return data as a list of tuples, where each tuple
    is (data, [add_kwargs, [layer_type]]), "add_kwargs" and "layer_type" are
    both optional.

    Parameters
    ----------
    path : str or list of str
        Path to file, or list of paths.

    Returns
    -------
    layer_data : list of tuples
        A list of LayerData tuples where each tuple in the list contains
        (data, metadata, layer_type), where data is a numpy array, metadata is
        a dict of keyword arguments for the corresponding viewer.add_* method
        in napari, and layer_type is a lower-case string naming the type of
        layer. Both "meta", and "layer_type" are optional. napari will
        default to layer_type=="image" if not provided
    """

    print(f"Loading PATATO HDF5 file: {path}")

    pa_data = pat.PAData.from_hdf5(path)
    recon = pa_data.get_scan_reconstructions()[
        "iThera BP-40mm(res:100μm)", "0"
    ]
    us = pa_data.get_ultrasound()
    wavelengths = [int(w) for w in pa_data.get_wavelengths()]

    assert recon.shape[1] == len(
        wavelengths
    ), "Shape of wavelength dim in reconstruction does not match number of recorded wavelengths."

    recon_scale = (1, 0.1, 0.1)
    us_scale = (1, 0.19, 0.19)

    data = [us, recon]
    layer_types = ["image", "image"]

    img_data = [np.flip(np.array(d.da[:, :, :, 0, :]), axis=-2) for d in data]

    # contrast_limits_per_wav = [
    #     [
    #         int(np.percentile(img_data[0][:, w, :, :], 1)),
    #         int(np.percentile(img_data[0][:, w, :, :], 99)),
    #     ]
    #     for w in range(len(wavelengths))
    # ]
    # doesnt work here. check: https://napari.org/dev/howtos/layers/image.html

    img_kwargs = [
        {
            # "contrast_limits": contrast_limits_per_wav,  # todo: does that work?
            "colormap": "viridis" if i != 0 else "gray",
            "name": "Recon" if i != 0 else "US",
            "scale": recon_scale if i != 0 else us_scale,
            "metadata": {"wavelengths": wavelengths} if i != 0 else {},
        }
        for i, img in enumerate(img_data)
    ]

    return [
        (img, kw, lt) for img, kw, lt in zip(img_data, img_kwargs, layer_types)
    ]


def patari_reader_function_all(path):
    """
    Reader for PATARI Plugin, returns all datasets fully loaded

    Sparse reconstructions are zero-padded to match ultrasound frames.
    This is not the most memory efficient, but simpler for napari alignment.

    Take a path or list of paths and return a list of LayerData tuples.

    Readers are expected to return data as a list of tuples, where each tuple
    is (data, [add_kwargs, [layer_type]]), "add_kwargs" and "layer_type" are
    both optional.

    Parameters
    ----------
    path : str or list of str
        Path to file, or list of paths.

    Returns
    -------
    layer_data : list of tuples
        A list of LayerData tuples where each tuple in the list contains
        (data, metadata, layer_type), where data is a numpy array, metadata is
        a dict of keyword arguments for the corresponding viewer.add_* method
        in napari, and layer_type is a lower-case string naming the type of
        layer. Both "meta", and "layer_type" are optional. napari will
        default to layer_type=="image" if not provided
    """

    recon_scale = (1, 0.1, 0.1)
    us_scale = (1, 0.19, 0.19)

    print(f"Loading PATATO HDF5 file: {path}")

    res = []

    pa_data = pat.PAData.from_hdf5(path)
    timestamps = np.array(pa_data.get_timestamps())

    # --- add ultrasound ---
    us_img = pa_data.get_ultrasound()
    us_img = np.flip(np.array(us_img.da[:, :, :, 0, :]), axis=-2)
    n_acq_frames = us_img.shape[0]

    us_kwargs = {
        "colormap": "gray",
        "name": "US",
        "scale": us_scale,
        "metadata": {
            "type": "us",
            "timestamps": timestamps,
        },
    }
    res.append((us_img, us_kwargs, "image"))

    # --- add reconstructions ---

    recons = pa_data.get_scan_reconstructions()
    wavelengths = [int(w) for w in pa_data.get_wavelengths()]

    for (recon_name, idx), recon in recons.items():

        recon_raw = np.flip(np.array(recon.da[:, :, :, 0, :]), axis=-2)

        # which frame was reconstructed is stored ambiguously
        frames_info = recon.da.attrs.get("frame", None)
        if frames_info is None:
            # assume all frames reconstructed
            recon_frame_list = list(range(recon_raw.shape[0]))
        elif isinstance(frames_info, (np.int64, float, int)):
            recon_frame_list = [int(frames_info)]
        elif isinstance(frames_info, (list, np.ndarray)):
            recon_frame_list = [int(f) for f in frames_info]
        else:
            raise ValueError(
                "Reconstruction 'frame' attribute has unsupported type."
            )

        # ----------------------------
        # ZERO-PAD TO ULTRASOUND FRAMES
        # ----------------------------
        # recon_raw shape: (N_recon, W, Y, X)
        # target shape:    (N_acq,   W, Y, X)

        recon_img = np.zeros(
            (n_acq_frames, *recon_raw.shape[1:]),
            dtype=recon_raw.dtype,
        )

        for i, acq_frame in enumerate(recon_frame_list):
            if acq_frame < 0 or acq_frame >= n_acq_frames:
                raise IndexError(
                    f"Reconstruction frame {acq_frame} out of bounds "
                    f"(0, {n_acq_frames - 1})"
                )
            recon_img[acq_frame] = recon_raw[i]

        # recon_img = np.flip(np.array(recon.da[:, :, :, 0, :]), axis=-2)

        # # which frame was reconstructed is stored ambigiously
        # frames_info = recon.da.attrs.get("frame", None)
        # if frames_info is None:
        #     # if no info, assume all frames
        #     recon_frame_list = range(recon_img.shape[0])
        # elif isinstance(frames_info, (np.int64, float, int)):
        #     # single frame
        #     recon_frame_list = [int(frames_info)]
        # elif isinstance(frames_info, (list, np.ndarray)):
        #     # in the future, we should store this as list
        #     recon_frame_list = [int(f) for f in frames_info]
        # else:
        #     raise ValueError(
        #         "Reconstruction 'frame' attribute has unsupported type."
        #     )
        recon_kwargs = {
            "colormap": "viridis",
            "name": f"Recon: {recon_name}_{idx}",
            "scale": recon_scale,
            "metadata": {
                "type": "pa",
                "wavelengths": wavelengths,
                "timestamps": timestamps,
                "frames": recon_frame_list,
            },
        }

        res.append((recon_img, recon_kwargs, "image"))

    # --- add unmixed images ---
    # TODO

    return res


def patari_reader_function_lazy(path):
    """
    Reader for PATARI Plugin. Returns default dataset and recons for lazy loading

    Take a path or list of paths and return a list of LayerData tuples.

    Readers are expected to return data as a list of tuples, where each tuple
    is (data, [add_kwargs, [layer_type]]), "add_kwargs" and "layer_type" are
    both optional.

    Parameters
    ----------
    path : str or list of str
        Path to file, or list of paths.

    Returns
    -------
    layer_data : list of tuples
        A list of LayerData tuples where each tuple in the list contains
        (data, metadata, layer_type), where data is a numpy array, metadata is
        a dict of keyword arguments for the corresponding viewer.add_* method
        in napari, and layer_type is a lower-case string naming the type of
        layer. Both "meta", and "layer_type" are optional. napari will
        default to layer_type=="image" if not provided
    """

    recon_scale = (1, 0.1, 0.1)
    us_scale = (1, 0.19, 0.19)

    print(f"Loading PATATO HDF5 file: {path}")

    res = []

    pa_data = pat.PAData.from_hdf5(path)

    # --- add ultrasound ---
    us_img = pa_data.get_ultrasound()
    us_img = np.flip(np.array(us_img.da[:, :, :, 0, :]), axis=-2)

    us_kwargs = {
        "colormap": "gray",
        "name": "US",
        "scale": us_scale,
        "metadata": {},
    }
    res.append((us_img, us_kwargs, "image"))

    # --- add reconstructions ---

    # --- add reconstructions but load only the first one ---

    recons = pa_data.get_scan_reconstructions()
    wavelengths = [int(w) for w in pa_data.get_wavelengths()]

    # convert keys to nicer strings
    available_names = [f"{name}_{idx}" for (name, idx) in recons.keys()]

    # pick first recon as default
    first_key = list(recons.keys())[0]
    first_name = f"{first_key[0]}_{first_key[1]}"
    first_obj = recons[first_key]  # object, NOT yet a NumPy array
    first_img = np.flip(np.array(first_obj.da[:, :, :, 0, :]), axis=-2)

    recon_kwargs = {
        "colormap": "viridis",
        "name": "Recon",
        "scale": recon_scale,
        "metadata": {
            "wavelengths": wavelengths,
            "available_recons": available_names,  # names for dropdown
            "recon_objects": recons,  # raw recon objects for lazy loading
            "current_recon": first_name,  # for widget
        },
    }

    res.append((first_img, recon_kwargs, "image"))

    # --- add unmixed images ---
    # TODO

    return res
