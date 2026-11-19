# Automated Spectrum Acquisition with Weather Logging

`controller.py` takes back-to-back gamma spectra with ORTEC MAESTRO (5 minutes each by default) for a run length you choose. Each time a spectrum is saved, it records the time and the current weather conditions.

## Requirements

- Windows laptop with ORTEC MAESTRO installed and the detector/MCA connected
- Python 3.8 or newer (standard library only, nothing to `pip install`)
- An internet connection for weather data (optional: spectra are still saved without it)

## Quick start

1. Connect the detector and MCA, and confirm that MAESTRO sees them (set the high voltage, gain, etc. as usual).
2. **Close MAESTRO.** The script opens it.
3. Open a terminal in this folder and run:

   ```
   python controller.py --test-weather     # confirm that weather data works
   python controller.py --hours 24         # 5-min spectra for 24 hours
   ```

4. Leave the laptop running. Disable sleep and hibernate in Windows power settings.

## Options

| Option | Default | Description |
|---|---|---|
| `--hours H` / `--minutes M` / `--count N` | (required) | Total run length, or the exact number of spectra |
| `--acq S` | `300` | Seconds per spectrum (real/clock time) |
| `--interval S` | same as `--acq` | Seconds between the starts of consecutive spectra. Set it larger than `--acq` to leave idle time between spectra. |
| `--detector N` | `1` | MAESTRO detector/MCB number |
| `--maestro PATH` | auto-detected | Full path to `MCA32.exe` if auto-detect fails |
| `--no-launch` | off | Only write the `.JOB` file and log spectra. You start the job in MAESTRO yourself. |
| `--test-weather` | | Print the current weather and exit |

Examples:

```
python controller.py --minutes 90
python controller.py --count 12
python controller.py --hours 6 --interval 600        # 5-min spectrum every 10 min
python controller.py --hours 1 --no-launch           # run the job from MAESTRO manually
```

## Output

Each run creates its own folder:

```
data/run_YYYYMMDD_HHMMSS/
├── acquire.JOB      # the MAESTRO job file that was run
├── spec_001.Chn     # spectra (ORTEC .Chn format, opens in MAESTRO)
├── spec_002.Chn
├── ...
├── run_log.csv      # one row per spectrum
└── run_info.json    # run settings and weather at the start of the run
```

### `run_log.csv` columns

| Column | Meaning |
|---|---|
| `index`, `file` | Spectrum number and file name |
| `saved_at` | Computer time when the spectrum was detected as saved |
| `acq_start` | Acquisition start time, read from the .Chn header |
| `real_time_s`, `live_time_s`, `dead_time_pct` | Timing from the MCA |
| `channels`, `total_counts`, `count_rate_cps` | Spectrum summary (the rate is total counts divided by live time) |
| `temperature_2m` | Air temperature (°C) |
| `relative_humidity_2m` | Relative humidity (%) |
| `surface_pressure`, `pressure_msl` | Station and sea-level pressure (hPa) |
| `precipitation`, `rain` | Precipitation (mm) |
| `cloud_cover` | Cloud cover (%) |
| `wind_speed_10m`, `wind_direction_10m` | Wind (km/h, degrees) |
| `weather_code` | WMO weather code |
| `weather_obs_time` | Timestamp of the weather observation |
| `weather_error` | Blank unless the weather request failed |

## How it works

MAESTRO has no live control interface from Python, so the script uses MAESTRO's built-in job files:

1. It writes `acquire.JOB`, which loops `CLEAR → START → WAIT → SAVE spec_???.Chn` N times, using a preset real time.
2. It starts MAESTRO with that job file.
3. It checks the run folder every 2 seconds. When a new `.Chn` file appears and has finished writing, the script reads the header and fetches the current weather from [Open-Meteo](https://open-meteo.com/) (free, no API key). Then it adds a row to `run_log.csv`.

Weather is fetched for Urbana-Champaign, IL. For a different location, edit `LATITUDE` and `LONGITUDE` near the top of `controller.py`.

## Notes and limitations

- **Stopping early:** Ctrl+C only stops the logging. You also have to cancel the job in MAESTRO (Services → Job Control) or close MAESTRO. Spectra that were already saved are kept and logged.
- **999 spectra maximum per run**, because of MAESTRO's `???` file numbering. At 5 minutes per spectrum that is about 83 hours. Split longer measurements into several runs.
- **Weather resolution:** Open-Meteo's "current" values update about every 15 minutes, so a few consecutive 5-minute spectra may share the same reading.
- **Real time vs. live time:** the presets use real time so that spectra line up with clock time. Correct the count rates for dead time with `live_time_s`, as `count_rate_cps` already does.
- **If MAESTRO doesn't launch or doesn't run the job:** use `--maestro` with the correct path to `MCA32.exe`, or use `--no-launch` and run `acquire.JOB` from MAESTRO's Services → Job Control.
- **OneDrive:** if this folder syncs to OneDrive, consider pausing sync during long runs, or move the folder outside OneDrive to avoid file-lock problems.
