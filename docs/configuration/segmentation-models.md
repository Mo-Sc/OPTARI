# Segmentation Models

The segmentation model registry (`~/.optari/config/segmentation_models.json`) declares every model OPTARI can run,
independent of the segmentation preset. See [Segmentation](../user-guide/segmentation.md) for the workflow and [Data & Integrations](../developer-guide/data-and-integrations.md) for the adapter pattern behind it.

## Registry format

```json title="segmentation_models.json"
{
  "models": [
    {
      "adapter_class": "UKErUSSegAdapter",
      "id": "c_unet_gastrocnemius-transverse",
      "filename": "c_unet_ta_20260928_gastrocnemius.onnx",
      "description": "trained on all MSOT2 samples, structural loss weight: 0.0",
      "input_height": 224,
      "input_width": 224,
      "class_names": {
        "0": "background",
        "1": "Haut",
        "2": "Faszie1",
        "3": "Muskel1",
        "4": "Muskel2",
        "5": "Membran",
        "7": "Vorlaufstrecke",
        "8": "SAT",
        "9": "Gel"
      },
      "default_class": "Muskel1",
      "postprocessing_config": {
        "keep_largest_per_class": [1, 3, 7, 8],
        "combine_class_groups": [[2, 6]],
        "remove_small_objects_config": [[1, 50], [3, 50], [4, 50], [7, 50], [8, 50], [9, 50], [2, 25]]
      },
      "url": "https://link.to/modelfile.onnx"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | Unique model identifier, referenced by segmentation presets (`model_id`) and by `segmentation.default_model` in `config.json`. |
| `adapter_class` | Name of the `ModelAdapterBase` subclass implementing this model's pre/postprocessing. |
| `filename` | ONNX weights filename, expected under `~/.optari/models/`. |
| `input_height` / `input_width` | Expected input frame size for the model. |
| `class_names` | Class-id → name map for the model's segmentation output. |
| `default_class` | Class selected by default in the Segmentation dock. |
| `postprocessing_config` | Postprocessing steps for the mask. Integers refer to class IDs: keep only the largest connected component per class, merge specific class groups, and remove small objects below a pixel threshold. |
| `url` |  Model download URL. If the weights file is missing locally, OPTARI tries to download it from here on first use. |

## Pretrained models

OPTARI comes with pretrained models for common clinical examination sites. The weights are not bundled with the
installer but are download automatically into `~/.optari/models/` the first time a given model is used, keeping
the base installation small. **Settings → Models** shows whether a given model's weights are already
installed.

## Adding a custom model

See [Extending OPTARI](../developer-guide/data-and-integrations.md#segmentation-models) in the developer guide.

<!-- 1. Implement a `ModelAdapterBase` subclass (`preprocess()` → `infer()` → `postprocess()`) if your model needs
   different pre/postprocessing than the existing adapters — otherwise reuse an existing `adapter_class`.
2. Add an entry to `segmentation_models.json` with a unique `id`, the weights filename, and class metadata.
3. Place the `.onnx` weights file in `~/.optari/models/`, or provide a `url` for automatic download.

No changes to any controller should be required. The registry is the only thing OPTARI reads to discover available
models. -->