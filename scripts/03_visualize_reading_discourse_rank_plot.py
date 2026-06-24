"""
Reclassify reading discourse semantic similarity by quantiles and draw one rank plot.

Run:
    python scripts/03_visualize_reading_discourse_rank_plot.py

Inputs:
    data/04_analysis/youtube_to_news_semantic_gap.csv

Outputs:
    data/04_analysis/reading_discourse_semantic_quantile_result.csv
    data/05_figures/reading_discourse_similarity_rank_plot.png
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".codex_deps" / "matplotlib"))

try:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, rcParams
except ModuleNotFoundError:
    plt = None
    font_manager = None
    rcParams = None


ANALYSIS_DIR = ROOT / "data" / "04_analysis"
FIGURE_DIR = ROOT / "data" / "05_figures"

INPUT_CSV = ANALYSIS_DIR / "youtube_to_news_semantic_gap.csv"
OUTPUT_CSV = ANALYSIS_DIR / "reading_discourse_semantic_quantile_result.csv"
OUTPUT_PNG = FIGURE_DIR / "reading_discourse_similarity_rank_plot.png"

COLORS = {
    "relative_semantic_gap": "#B84A4A",
    "relative_semantic_bridge": "#D59A2B",
    "relative_semantic_near": "#2F6B4F",
}


def setup_korean_font() -> None:
    if plt is None:
        return
    candidates = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
        "Noto Sans CJK JP",
    ]
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in candidates:
        if font_name in installed:
            rcParams["font.family"] = font_name
            break
    rcParams["axes.unicode_minus"] = False


def classify_by_quantile(similarity: float, q25: float, q75: float) -> str:
    if similarity <= q25:
        return "relative_semantic_gap"
    if similarity >= q75:
        return "relative_semantic_near"
    return "relative_semantic_bridge"


def load_and_prepare() -> tuple[pd.DataFrame, float, float]:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    required = [
        "youtube_keyword",
        "nearest_news_keyword",
        "similarity",
        "youtube_core_score",
        "news_core_score",
    ]
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {INPUT_CSV}: {sorted(missing)}")

    prepared = df.loc[:, required].copy()
    prepared["similarity"] = pd.to_numeric(prepared["similarity"], errors="coerce")
    prepared["youtube_core_score"] = pd.to_numeric(
        prepared["youtube_core_score"], errors="coerce"
    )
    prepared["news_core_score"] = pd.to_numeric(
        prepared["news_core_score"], errors="coerce"
    )
    prepared = prepared.dropna(subset=["similarity"]).sort_values(
        ["similarity", "youtube_keyword", "nearest_news_keyword"],
        ascending=[True, True, True],
        kind="mergesort",
    )

    q25 = float(prepared["similarity"].quantile(0.25))
    q75 = float(prepared["similarity"].quantile(0.75))
    prepared.insert(0, "rank", range(1, len(prepared) + 1))
    prepared["quantile_relation_type"] = prepared["similarity"].apply(
        lambda value: classify_by_quantile(float(value), q25, q75)
    )

    output_columns = [
        "rank",
        "youtube_keyword",
        "nearest_news_keyword",
        "similarity",
        "quantile_relation_type",
        "youtube_core_score",
        "news_core_score",
    ]
    return prepared.loc[:, output_columns].reset_index(drop=True), q25, q75


def plot_with_matplotlib(df: pd.DataFrame, q25: float, q75: float) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.axhspan(df["similarity"].min(), q25, color=COLORS["relative_semantic_gap"], alpha=0.08, label="lower 25%")
    ax.axhspan(q25, q75, color=COLORS["relative_semantic_bridge"], alpha=0.08, label="middle 50%")
    ax.axhspan(q75, df["similarity"].max(), color=COLORS["relative_semantic_near"], alpha=0.08, label="upper 25%")
    ax.scatter(df["rank"], df["similarity"], c=df["quantile_relation_type"].map(COLORS), s=34, alpha=0.9)
    ax.axhline(q25, color=COLORS["relative_semantic_gap"], linestyle="--", linewidth=1.3)
    ax.axhline(q75, color=COLORS["relative_semantic_near"], linestyle="--", linewidth=1.3)
    ax.text(df["rank"].max(), q25, f" Q25={q25:.4f}", va="bottom", ha="right")
    ax.text(df["rank"].max(), q75, f" Q75={q75:.4f}", va="bottom", ha="right")
    ax.set_title("Ranked Similarity between Reading Discourse and News Trend Language", pad=14)
    ax.set_xlabel("rank")
    ax.set_ylabel("similarity")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_PNG, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def blend(base: tuple[int, int, int], overlay: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return tuple(round(base[i] * (1 - alpha) + overlay[i] * alpha) for i in range(3))


def plot_with_pil(df: pd.DataFrame, q25: float, q75: float) -> None:
    width, height = 1800, 900
    margin_left, margin_right, margin_top, margin_bottom = 140, 80, 110, 120
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    white = (255, 255, 255)
    grid = (220, 220, 220)
    axis = (60, 60, 60)

    img = Image.new("RGB", (width, height), white)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    min_sim = float(df["similarity"].min())
    max_sim = float(df["similarity"].max())
    sim_pad = (max_sim - min_sim) * 0.05 or 0.01
    y_min = min_sim - sim_pad
    y_max = max_sim + sim_pad

    def x_pos(rank: float) -> int:
        return int(margin_left + (rank - 1) / max(1, len(df) - 1) * plot_w)

    def y_pos(sim: float) -> int:
        return int(margin_top + (y_max - sim) / (y_max - y_min) * plot_h)

    zones = [
        (y_min, q25, "relative_semantic_gap", "lower 25%"),
        (q25, q75, "relative_semantic_bridge", "middle 50%"),
        (q75, y_max, "relative_semantic_near", "upper 25%"),
    ]
    for low, high, key, label in zones:
        y_top, y_bottom = y_pos(high), y_pos(low)
        fill = blend(white, hex_to_rgb(COLORS[key]), 0.10)
        draw.rectangle([margin_left, y_top, margin_left + plot_w, y_bottom], fill=fill)

    for i in range(6):
        sim = y_min + (y_max - y_min) * i / 5
        y = y_pos(sim)
        draw.line([margin_left, y, margin_left + plot_w, y], fill=grid, width=1)
        draw.text((20, y - 7), f"{sim:.2f}", fill=axis, font=font)

    draw.rectangle([margin_left, margin_top, margin_left + plot_w, margin_top + plot_h], outline=axis, width=2)
    for value, color, label in [
        (q25, COLORS["relative_semantic_gap"], f"Q25={q25:.4f}"),
        (q75, COLORS["relative_semantic_near"], f"Q75={q75:.4f}"),
    ]:
        y = y_pos(value)
        rgb = hex_to_rgb(color)
        for offset in range(0, plot_w, 18):
            draw.line([margin_left + offset, y, min(margin_left + offset + 9, margin_left + plot_w), y], fill=rgb, width=3)
        draw.text((margin_left + plot_w - 120, y - 20), label, fill=rgb, font=font)

    for row in df.itertuples(index=False):
        x = x_pos(row.rank)
        y = y_pos(row.similarity)
        rgb = hex_to_rgb(COLORS[row.quantile_relation_type])
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=rgb, outline=white)

    title = "Ranked Similarity between Reading Discourse and News Trend Language"
    draw.text((margin_left, 40), title, fill=(20, 20, 20), font=font)
    draw.text((margin_left + plot_w // 2 - 20, height - 55), "rank", fill=axis, font=font)
    draw.text((25, margin_top - 25), "similarity", fill=axis, font=font)

    legend_x = margin_left + plot_w - 260
    legend_y = margin_top + plot_h - 85
    for idx, (key, label) in enumerate([
        ("relative_semantic_gap", "lower 25%"),
        ("relative_semantic_bridge", "middle 50%"),
        ("relative_semantic_near", "upper 25%"),
    ]):
        y = legend_y + idx * 24
        draw.rectangle([legend_x, y, legend_x + 14, y + 14], fill=hex_to_rgb(COLORS[key]))
        draw.text((legend_x + 22, y), label, fill=axis, font=font)

    img.save(OUTPUT_PNG)


def plot_rank_similarity(df: pd.DataFrame, q25: float, q75: float) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    if plt is not None:
        plot_with_matplotlib(df, q25, q75)
    else:
        plot_with_pil(df, q25, q75)


def print_results(df: pd.DataFrame, q25: float, q75: float) -> None:
    print(f"Q25: {q25:.6f}")
    print(f"Q75: {q75:.6f}")

    display_columns = [
        "rank",
        "youtube_keyword",
        "nearest_news_keyword",
        "similarity",
        "quantile_relation_type",
        "youtube_core_score",
        "news_core_score",
    ]

    print("\n[similarity 낮은 순 Top 20]")
    print(df.head(20).loc[:, display_columns].to_string(index=False))

    print("\n[similarity 높은 순 Top 20]")
    print(
        df.sort_values(["similarity", "rank"], ascending=[False, True])
        .head(20)
        .loc[:, display_columns]
        .to_string(index=False)
    )

    print("\n[quantile_relation_type별 개수]")
    print(df["quantile_relation_type"].value_counts().to_string())


def main() -> None:
    setup_korean_font()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    result, q25, q75 = load_and_prepare()
    result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    plot_rank_similarity(result, q25, q75)
    print_results(result, q25, q75)

    print("\nsaved:")
    print(f"- {OUTPUT_CSV}")
    print(f"- {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
