"""Generate the README's measured production Glance latency chart.

Run from the repository root:
  MPLCONFIGDIR=/private/tmp/caretrace-mpl python scripts/generate_latency_chart.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator


SAMPLES_MS = [
    204.467,
    188.683,
    185.202,
    184.805,
    186.340,
    180.007,
    214.570,
    173.640,
    212.766,
    191.590,
    190.314,
    234.287,
    187.819,
    190.784,
    180.627,
    188.763,
]
TARGET_MS = 300
P50_MS = 188.723
P95_MS = 234.287
OUTPUT = Path("docs/assets/glance-latency.png")


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.labelcolor": "#314842",
            "xtick.color": "#587068",
            "ytick.color": "#587068",
        }
    )
    figure, axis = plt.subplots(figsize=(12, 6.4), dpi=160, facecolor="#fbfcfa")
    axis.set_facecolor("#fbfcfa")
    positions = list(range(1, len(SAMPLES_MS) + 1))

    axis.fill_between(positions, SAMPLES_MS, [150] * len(SAMPLES_MS), color="#d8eee4", alpha=0.8, zorder=1)
    axis.plot(positions, SAMPLES_MS, color="#0c7560", linewidth=2.6, zorder=3)
    axis.scatter(positions, SAMPLES_MS, color="#0c7560", edgecolor="#ffffff", linewidth=1.4, s=64, zorder=4)
    axis.axhline(TARGET_MS, color="#c95c58", linewidth=1.7, linestyle=(0, (5, 4)), zorder=2)
    axis.axhline(P50_MS, color="#8fa79e", linewidth=1.2, linestyle=(0, (2, 3)), zorder=2)

    axis.annotate(
        "300ms target",
        xy=(16.25, TARGET_MS),
        xytext=(16.25, TARGET_MS + 11),
        color="#a64541",
        fontsize=11,
        fontweight="bold",
        ha="right",
    )
    axis.annotate(
        "P50 188.7ms",
        xy=(16.25, P50_MS),
        xytext=(16.25, P50_MS - 16),
        color="#587068",
        fontsize=10,
        ha="right",
    )
    axis.annotate(
        "P95 234.3ms",
        xy=(12, P95_MS),
        xytext=(12.55, 251),
        arrowprops={"arrowstyle": "-", "color": "#0c7560", "lw": 1.3},
        color="#0c7560",
        fontsize=11,
        fontweight="bold",
    )

    axis.set_xlim(0.5, 16.65)
    axis.set_ylim(150, 330)
    axis.set_xticks(positions)
    axis.set_xlabel("Sequential production request", labelpad=14, fontsize=12, fontweight="bold")
    axis.set_ylabel("End-to-end latency (ms)", labelpad=14, fontsize=12, fontweight="bold")
    axis.yaxis.set_major_locator(MultipleLocator(25))
    axis.grid(axis="y", color="#dbe5e0", linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color("#aebfb8")
    axis.set_title("Glance API warm-path latency — Vercel sin1 + Neon Singapore", loc="left", pad=24, fontsize=18)
    figure.text(
        0.125,
        0.89,
        "16 HTTPS requests · 27 Aug 2026 · all responses HTTP 200 · target met",
        color="#587068",
        fontsize=11,
    )
    figure.text(
        0.125,
        0.035,
        "Measured from the development machine against the deployed production endpoint. This is a small warm-path sample, not a load test.",
        color="#587068",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.07, 1, 0.88))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT, facecolor=figure.get_facecolor(), bbox_inches="tight")


if __name__ == "__main__":
    main()
