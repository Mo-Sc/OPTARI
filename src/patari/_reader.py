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
            "name": "Reconstruction" if i != 0 else "Ultrasound",
            "scale": recon_scale if i != 0 else us_scale,
            "metadata": {"wavelengths": wavelengths} if i != 0 else {},
        }
        for i, img in enumerate(img_data)
    ]

    return [
        (img, kw, lt) for img, kw, lt in zip(img_data, img_kwargs, layer_types)
    ]

    # return [(recon_np, add_kwargs, layer_type)]
