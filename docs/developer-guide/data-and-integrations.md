# Data & Integrations

PATARI does not implement its own file I/O. Everything goes through a custom [PATATO fork](https://github.com/Mo-Sc/patato), and `src/patari/patato_bridge.py` converts PATATO objects into napari layers and back.

## Supported input formats

| Source | Detected by | Reader |
| --- | --- | --- |
| iThera MSOT Acuity | a `*.msot` file inside the scan folder | `patato.iTheraMSOT` |
| iThera MSOT Frontier | TODO | TODO |
| PATATO HDF5 | a `raw_data` dataset | `patato.io.hdf.hdf5_interface.HDF5Reader` |
| IPASC HDF5 | a `binary_time_series_data` dataset and a `meta_data` group | `patato.io.ipasc.read_ipasc.IPASCInterface` |


An IPASC file contains raw time series only, so it opens with no layers in the viewer until you run a
reconstruction.

## Notes on the IPASC format

The [IPASC data format](https://www.ipasc.science) is two things:

**The container** is intended for raw time series data. The paper states that it "does not yet
support the inclusion of data from bimodal systems, such as combined photoacoustic and ultrasound systems". Reconstructions, Annotations, etc are out of scope.
So the primary PATARI export uses a custom schema, inspired by PATATO's HDF5 files.

**The metadata dictionary** is independent, and PATARI adopts it. Every PATARI HDF5 file carries
an `/ipasc` group holding `meta_data` and `meta_data_device` in the layout IPASC defines, written under IPASC tag
names in IPASC units.

We implemented [pacfish](https://pacfish.readthedocs.io), for the tag
definitions, the device metadata structure, the file I/O and the quality-control checkers.

Unit conversions are done in `patato.io.ipasc.conversions`:

| Quantity | PATATO | IPASC |
| --- | --- | --- |
| Wavelengths | nm | m |
| Acquisition times | seconds on the .NET epoch (like in ithera files) | seconds since the Unix epoch |
| Temperature | degrees Celsius | kelvin |
| Detector positions | m | m |

A field with no counterpart in the vendor data is left
absent.

Present, because the source records them: `encoding`, `compression`, `data_type`, `dimensionality`,
`sizes`, `ad_sampling_rate`, `acquisition_wavelengths`, `measurement_timestamps`, `speed_of_sound`,
`temperature_control`, and per-element `detector_position`. Values are checked with
the pacfish `ConsistencyChecker`.

Absent, because no supported format records them:

- `pulse_energy`, `time_gain_compensation`, `element_dependent_gain`, `frequency_domain_filter`, and all
  illumination element geometry.
- `scanning_method`, `measurements_per_image` and `acoustic_coupling_agent`. 
- `measurement_spatial_poses`. Maybe PATATO scanner z position?
- The device `field_of_view`. IPASC defines it as the volume the device can detect,. But ithera scanners only contain  `<FIELD-OF-VIEW>` per reconstruction, and
  `<ULTRA-SOUND-FIELD-OF-VIEW>` for the ultrasound image. 

### UUIDs
No ithera device parameter follows IPASC's required UUID structure. But they contain the records `DeviceSN`, `TransducerSN`, `LaserSN`, `DAQ_MACaddress` and `SW_Version` in the scan node. The PATATO fork reads them into a dictionary (`ReaderInterface.get_device_info`), stores it in the `device_info` root attribute. 
So our IPASC layer hashes the `DeviceSN` and `DAQ_MACaddress` into a version 5 UUID as device `unique_identifier`.

The data `uuid` is a generated value, since it should identify the file being written rather than anything about the
source.
