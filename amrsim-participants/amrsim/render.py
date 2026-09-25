"""PNG of a run from its JSONL log: map, true path, pose estimate, pedestrians, episodes.

matplotlib is optional: it is imported inside render_log(); without it the
command prints how to plot the log with ten lines of code and exits with 2.
"""
import json
from pathlib import Path

from amrsim.util import AmrsimError

HOWTO = """matplotlib is not installed: python -m pip install matplotlib
or plot the log yourself (docs/DATA.md section 7.1), for example:
  import json, matplotlib.pyplot as plt
  rec = [json.loads(l) for l in open("out/01.jsonl")]
  t = [r for r in rec if r["type"] == "tick"]
  plt.plot([r["x"] for r in t], [r["y"] for r in t], label="truth")
  pe = [r["pe"] for r in t if r["pe"]]
  plt.plot([p[0] for p in pe], [p[1] for p in pe], "--", label="pose_est")
  plt.axis("equal"); plt.legend(); plt.savefig("out/01.png")"""


def load_log(path):
    p = Path(path)
    if not p.is_file():
        raise AmrsimError("file not found: %s" % p)
    recs = []
    try:
        with p.open(encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                if line.strip():
                    try:
                        r = json.loads(line)
                    except ValueError:
                        raise AmrsimError("%s:%d: not a JSON line" % (p, i))
                    if not isinstance(r, dict):
                        raise AmrsimError("%s:%d: not a JSON object" % (p, i))
                    recs.append(r)
    except UnicodeDecodeError:
        raise AmrsimError("not UTF-8 text: %s" % p)
    except OSError as e:
        raise AmrsimError("cannot read %s: %s" % (p, e.strerror))
    if not recs or recs[0].get("type") != "header":
        raise AmrsimError("%s: not an amrsim run log (no header)" % p)
    return recs


def render_log(log_path, png_path):
    recs = load_log(log_path)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Polygon
    except ImportError:
        raise AmrsimError(HOWTO, code=2)
    from amrsim.scoring import score_records
    hdr = recs[0]
    ticks = [r for r in recs if r.get("type") == "tick"]
    fig, ax = plt.subplots(figsize=(12, 9), dpi=110)
    mp = hdr.get("map")
    if mp:
        for poly in mp.get("drivable", []):
            ax.add_patch(Polygon(poly, closed=True, facecolor="#e6e6e6", edgecolor="none", zorder=0))
        colors = {"gnss_shadow": "#8fb3ff", "speed_limit": "#ffe08a", "forbidden": "#ff9c9c",
                  "people_area": "#b9e6b9"}
        for z in mp.get("zones", []):
            ax.add_patch(Polygon(z["polygon"], closed=True, facecolor=colors.get(z["type"], "#dddddd"),
                                 alpha=0.35, edgecolor="none", zorder=1))
        for b in mp.get("buildings", []):
            ax.add_patch(Polygon(b["polygon"], closed=True, facecolor="#555555", edgecolor="#333333", zorder=2))
        for name, p in mp.get("points", {}).items():
            ax.plot(p["x"], p["y"], "k^", zorder=6)
            ax.annotate(name, (p["x"], p["y"]), textcoords="offset points", xytext=(4, 4), fontsize=8)
    for pt in hdr.get("map_patches", []):
        if pt.get("op") == "add":
            ax.add_patch(Polygon(pt["polygon"], closed=True, facecolor="#d62728", edgecolor="#d62728",
                                 lw=1.5, alpha=0.8, zorder=3))
    for ev in hdr.get("events", []):
        if ev.get("type") == "object_dropped":
            ax.add_patch(Circle((ev["x"], ev["y"]), ev["r"], color="#d62728", zorder=3))
    if ticks:
        ax.plot([r["x"] for r in ticks], [r["y"] for r in ticks], "-", color="#1f77b4", lw=1.6,
                label="truth", zorder=5)
        pe = [r["pe"] for r in ticks if r.get("pe")]
        if pe:
            ax.plot([p[0] for p in pe], [p[1] for p in pe], "--", color="#ff7f0e", lw=1.0,
                    label="pose_est", zorder=5)
        px, py = [], []
        for r in ticks[::5]:
            for x, y in r.get("peds", []):
                px.append(x)
                py.append(y)
        if px:
            ax.scatter(px, py, s=2, color="#2ca02c", label="pedestrians", zorder=4)
    try:
        sc = score_records(recs)
        title = "%s seed %s: total %.2f" % (hdr.get("scenario"), hdr.get("seed"), sc["total"])
        for e in sc["episodes"]:
            ax.plot(e["x"], e["y"], "x", color="#d62728", ms=8, mew=2, zorder=7)
            ax.annotate(e["type"], (e["x"], e["y"]), textcoords="offset points", xytext=(4, -10),
                        fontsize=7, color="#d62728")
    except (ValueError, KeyError, TypeError):
        title = "%s seed %s (log incomplete)" % (hdr.get("scenario"), hdr.get("seed"))
    ax.set_title(title)
    ax.set_aspect("equal")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper right", fontsize=8)
    ax.set_xlabel("x, m")
    ax.set_ylabel("y, m")
    out = Path(png_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, format="png", bbox_inches="tight")  # exactly the given path, always PNG
    except OSError as e:
        raise AmrsimError("cannot write %s: %s" % (out, e.strerror))
    finally:
        plt.close(fig)
    return out
