# Automated Spectrum Acquisition with Weather Logging

`controller.py` takes back-to-back gamma spectra with ORTEC MAESTRO (5 minutes each by default) for a run length you choose, up to a week or longer. Each time a spectrum is saved, it records the time and the current weather conditions. The data is sorted into one folder per day: 288 spectra per day at 5 minutes each.

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
   python controller.py --hours 168        # one week: 7 day folders of 288 spectra each
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
| `--no-launch` | off | Only write each day's `.JOB` file and log spectra. You start each day's job in MAESTRO yourself. |
| `--test-weather` | | Print the current weather and exit |

Examples:

```
python controller.py --minutes 90
python controller.py --count 12
python controller.py --hours 6 --interval 600        # 5-min spectrum every 10 min
python controller.py --hours 1 --no-launch           # run the job from MAESTRO manually
```

## Output

Each day of the run gets its own folder inside `data/`, named with the date that day started. A one-week run (`--hours 168`) looks like this:

```
data/
├── 2026-11-20/
│   ├── acquire.JOB      # the MAESTRO job file for this day
│   ├── spec_001.Spe     # spectra (ORTEC ASCII .Spe format, opens in MAESTRO or any text editor)
│   ├── ...
│   ├── spec_288.Spe
│   ├── run_log.csv      # one row per spectrum (288 rows)
│   └── run_info.json    # settings, day number, and weather at the start of the day
├── 2026-11-21/
│   └── ...
└── 2026-11-26/          # 7 folders total
```

- **A "day" is 24 hours from when you start the run** (86400 s ÷ `--interval`, so 288 spectra at 5 minutes). It is not midnight to midnight. A run started at 2 pm fills each folder from 2 pm to 2 pm.
- **If the run length isn't a whole number of days,** the last folder holds only the remaining spectra.
- **Existing data is never overwritten.** If a date folder already contains spectra (for example, you restart on the same day), the new folder is named `2026-11-20_2`, `_3`, and so on.

### `run_log.csv` columns

| Column | Meaning |
|---|---|
| `index`, `file` | Spectrum number and file name |
| `saved_at` | Computer time when the spectrum was detected as saved |
| `acq_start` | Acquisition start time, read from the .Spe file |
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

1. For each day, it creates the day folder and writes an `acquire.JOB` file there. The job loops `CLEAR → START → WAIT → SAVE spec_???.Spe` 288 times (one day's worth), using a preset real time. On every day except the last, it ends with `QUIT` so that MAESTRO closes.
2. It starts MAESTRO with that day's job file.
3. It checks the day folder every 2 seconds. When a new `.Spe` file appears and has finished writing, the script reads it and fetches the current weather from [Open-Meteo](https://open-meteo.com/) (free, no API key). Then it adds a row to that day's `run_log.csv`.
4. When the day's spectra are all in, it waits for MAESTRO to close and starts it again with the next day's job. If MAESTRO hasn't closed within 2 minutes, the script closes it. By then that day's spectra are all saved.

Weather is fetched for Urbana-Champaign, IL. For a different location, edit `LATITUDE` and `LONGITUDE` near the top of `controller.py`.

## Notes and limitations

- **Stopping early:** Ctrl+C only stops the logging. You also have to cancel the job in MAESTRO (Services → Job Control) or close MAESTRO. Spectra that were already saved are kept and logged.
- **Gap between days:** MAESTRO closes and reopens between days, which leaves a short gap in acquisition (a few seconds to about half a minute). Compare `acq_start` times across folders if you need the exact gap.
- **999 spectra maximum per day folder**, because of MAESTRO's `???` file numbering. The total run length has no limit. At the default 5 minutes, a day holds 288. An `--interval` shorter than 87 s would go over the limit, and the script will refuse it.
- **With `--no-launch`,** the script prints each day's job file path and waits for you to run it in MAESTRO. In this mode MAESTRO stays open between days.
- **Weather resolution:** Open-Meteo's "current" values update about every 15 minutes, so a few consecutive 5-minute spectra may share the same reading.
- **Real time vs. live time:** the presets use real time so that spectra line up with clock time. Correct the count rates for dead time with `live_time_s`, as `count_rate_cps` already does.
- **If MAESTRO doesn't launch or doesn't run the job:** use `--maestro` with the correct path to `MCA32.exe`, or use `--no-launch` and run each day's `acquire.JOB` from MAESTRO's Services → Job Control.
- **"Failure in detector function" in a job:** the MCA rejected a job command. Check the detector number (`--detector`). Also make sure the detector isn't already acquiring or locked by another program.
- **OneDrive:** if this folder syncs to OneDrive, consider pausing sync during long runs, or move the folder outside OneDrive to avoid file-lock problems.
