"""
Automated gamma-spectrum acquisition with ORTEC MAESTRO + weather logging.

What it does
------------
1. Builds a MAESTRO .JOB file that, N times in a row:
       CLEAR -> START -> WAIT (preset real time) -> SAVE "spec_###.Chn"
2. Launches MAESTRO with that job file (or you run the job yourself).
3. Watches the output folder. Each time a new .Chn spectrum appears it
   reads the header (start time, real/live time, total counts), fetches
   current weather (Open-Meteo, free, no API key), and appends a row to
   run_log.csv.

Usage examples (run on the lab laptop)
--------------------------------------
    python controller.py --hours 24                 # 5-min spectra for 24 h
    python controller.py --hours 2 --acq 300 --interval 600
    python controller.py --count 12                 # exactly 12 spectra
    python controller.py --hours 1 --no-launch      # write .JOB only; run it
                                                    # from MAESTRO yourself
    python controller.py --test-weather             # check internet/weather

Stop early: cancel the job in MAESTRO (Services > Job Control / Stop), then
Ctrl+C this script. Spectra already saved stay saved and logged.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request

# ---------------------------------------------------------------- settings
# Location used for weather (default: Urbana-Champaign, IL)
LATITUDE = 40.1106
LONGITUDE = -88.2073

# Where MAESTRO usually lives. Override with --maestro "C:\path\MCA32.exe"
MAESTRO_CANDIDATES = [
    r"C:\Program Files (x86)\ORTEC\MAESTRO\MCA32.exe",
    r"C:\Program Files\ORTEC\MAESTRO\MCA32.exe",
    r"C:\MAESTRO\MCA32.exe",
    r"C:\Program Files (x86)\ORTEC\*\MCA32.exe",
    r"C:\Program Files\ORTEC\*\MCA32.exe",
]

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(HERE, "data")

WEATHER_FIELDS = [
    "temperature_2m",          # deg C
    "relative_humidity_2m",    # %
    "surface_pressure",        # hPa  (matters for cosmic/radon background)
    "pressure_msl",            # hPa
    "precipitation",           # mm
    "rain",                    # mm
    "cloud_cover",             # %
    "wind_speed_10m",          # km/h
    "wind_direction_10m",      # deg
    "weather_code",            # WMO code
]


# ---------------------------------------------------------------- weather
def get_weather():
    """Return dict of current conditions; values are '' if the fetch fails."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current={','.join(WEATHER_FIELDS)}&timezone=auto"
    )
    out = {f: "" for f in WEATHER_FIELDS}
    out["weather_obs_time"] = ""
    out["weather_error"] = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lab-daq-script"})
        with urllib.request.urlopen(req, timeout=15) as r:
            cur = json.load(r).get("current", {})
        for f in WEATHER_FIELDS:
            out[f] = cur.get(f, "")
        out["weather_obs_time"] = cur.get("time", "")
    except Exception as e:  # no internet, timeout, etc. -> keep running
        out["weather_error"] = str(e)[:120]
    return out


# ---------------------------------------------------------------- .Chn file
def read_chn(path):
    """Parse an ORTEC .Chn header. Returns dict (start time, real/live s, counts)."""
    with open(path, "rb") as f:
        data = f.read()
    (ftype, mca, seg, secs, real20, live20,
     date, hhmm, offset, nch) = struct.unpack("<hhh2sii8s4shh", data[:32])
    if ftype != -1:
        raise ValueError("not a .Chn file")
    counts = struct.unpack(f"<{nch}i", data[32:32 + 4 * nch])
    # date like b'18NOV261' (last char '1' => 2000s), time b'1405', secs b'07'
    d = date.decode("ascii", "replace")
    try:
        year = (2000 if d[7] == "1" else 1900) + int(d[5:7])
        start = dt.datetime.strptime(
            f"{d[0:2]}{d[2:5].title()}{year} {hhmm.decode()}{secs.decode()}",
            "%d%b%Y %H%M%S")
        start_s = start.isoformat(sep=" ")
    except Exception:
        start_s = ""
    return {
        "acq_start": start_s,
        "real_time_s": real20 * 0.02,
        "live_time_s": live20 * 0.02,
        "dead_time_pct": round(100 * (1 - live20 / real20), 3) if real20 else "",
        "channels": nch,
        "total_counts": sum(counts),
        "count_rate_cps": round(sum(counts) / (live20 * 0.02), 4) if live20 else "",
    }


# ---------------------------------------------------------------- job file
def write_job(path, run_dir, n, acq_s, interval_s, detector):
    lines = [
        f"SET_DETECTOR {detector}",
        "SET_PRESET_CLEAR",
        f"SET_PRESET_REAL {acq_s}",
        f"LOOP {n}",
        "  CLEAR",
        "  START",
        "  WAIT",
        f'  SAVE "{os.path.join(run_dir, "spec_???.Chn")}"',
    ]
    if interval_s > acq_s:  # idle time between spectra
        lines.append(f"  WAIT {interval_s - acq_s}")
    lines.append("END_LOOP")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def find_maestro(user_path):
    if user_path:
        return user_path if os.path.isfile(user_path) else None
    for pat in MAESTRO_CANDIDATES:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    return None


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--hours", type=float, help="total run length in hours")
    g.add_argument("--minutes", type=float, help="total run length in minutes")
    g.add_argument("--count", type=int, help="number of spectra to take")
    p.add_argument("--acq", type=int, default=300, help="seconds per spectrum (real time), default 300")
    p.add_argument("--interval", type=int, default=None,
                   help="seconds between spectrum starts, default = --acq (back-to-back)")
    p.add_argument("--detector", type=int, default=1, help="MAESTRO detector/MCB number, default 1")
    p.add_argument("--maestro", help="full path to MAESTRO executable (MCA32.exe)")
    p.add_argument("--no-launch", action="store_true",
                   help="only write the .JOB file and watch; run the job in MAESTRO yourself")
    p.add_argument("--test-weather", action="store_true", help="print current weather and exit")
    a = p.parse_args()

    if a.test_weather:
        print(json.dumps(get_weather(), indent=2))
        return

    interval = a.interval or a.acq
    if a.count:
        n = a.count
    elif a.hours or a.minutes:
        total_s = (a.hours or 0) * 3600 + (a.minutes or 0) * 60
        n = max(1, int(total_s // interval))
    else:
        p.error("give --hours, --minutes, or --count")
    if n > 999:
        p.error("max 999 spectra per run (MAESTRO ??? numbering); split into several runs")

    run_dir = os.path.join(DATA_ROOT, dt.datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    job_path = os.path.join(run_dir, "acquire.JOB")
    log_path = os.path.join(run_dir, "run_log.csv")
    write_job(job_path, run_dir, n, a.acq, interval, a.detector)

    end_eta = dt.datetime.now() + dt.timedelta(seconds=n * interval)
    print(f"Run folder : {run_dir}")
    print(f"Plan       : {n} spectra x {a.acq} s, one every {interval} s")
    print(f"Expected end ~ {end_eta:%Y-%m-%d %H:%M}")

    # Log conditions at the start of the run
    fields = (["index", "file", "saved_at", "acq_start", "real_time_s", "live_time_s",
               "dead_time_pct", "channels", "total_counts", "count_rate_cps"]
              + WEATHER_FIELDS + ["weather_obs_time", "weather_error"])
    with open(log_path, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()
    w0 = get_weather()
    with open(os.path.join(run_dir, "run_info.json"), "w") as f:
        json.dump({"started": dt.datetime.now().isoformat(), "n_spectra": n,
                   "acq_s": a.acq, "interval_s": interval, "detector": a.detector,
                   "lat": LATITUDE, "lon": LONGITUDE, "weather_at_start": w0}, f, indent=2)
    if w0["weather_error"]:
        print(f"WARNING: weather fetch failed ({w0['weather_error']}). "
              "Spectra will still be saved; weather columns will be blank.")

    proc = None
    if a.no_launch:
        print(f"\nIn MAESTRO: Services > Job Control... and run:\n  {job_path}\n")
    else:
        exe = find_maestro(a.maestro)
        if not exe:
            sys.exit("Could not find MAESTRO (MCA32.exe). Use --maestro PATH or --no-launch.")
        print(f"Launching  : {exe}")
        proc = subprocess.Popen([exe, job_path])

    # Watch for new spectra
    seen, pending = set(), {}
    print("Waiting for spectra... (Ctrl+C to stop watching)\n")
    try:
        while len(seen) < n:
            for path in sorted(glob.glob(os.path.join(run_dir, "*.Chn"))):
                if path in seen:
                    continue
                size = os.path.getsize(path)
                if pending.get(path) != size:   # wait until size is stable
                    pending[path] = size
                    continue
                try:
                    info = read_chn(path)
                except Exception:
                    continue                    # still being written
                seen.add(path)
                row = {"index": len(seen), "file": os.path.basename(path),
                       "saved_at": dt.datetime.now().isoformat(sep=" ", timespec="seconds"),
                       **info, **get_weather()}
                with open(log_path, "a", newline="") as f:
                    csv.DictWriter(f, fieldnames=fields).writerow(row)
                print(f"[{row['saved_at']}] {row['file']}  {info['total_counts']} counts  "
                      f"{info['count_rate_cps']} cps  T={row['temperature_2m']}C  "
                      f"P={row['surface_pressure']}hPa  RH={row['relative_humidity_2m']}%  "
                      f"({len(seen)}/{n})")
            if proc and proc.poll() is not None and len(seen) < n:
                time.sleep(3)  # last file may still be landing
                if not any(pth not in seen for pth in glob.glob(os.path.join(run_dir, "*.Chn"))):
                    print("MAESTRO closed before the run finished.")
                    break
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped watching. (Cancel the job in MAESTRO if it's still running.)")

    print(f"\nDone: {len(seen)} spectra logged to {log_path}")


if __name__ == "__main__":
    main()
