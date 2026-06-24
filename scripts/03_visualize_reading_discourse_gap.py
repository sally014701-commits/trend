"""
Visualize semantic gaps between YouTube reading discourse keywords and news trend language.

Run:
    python scripts/03_visualize_reading_discourse_gap.py

Inputs:
    data/04_analysis/youtube_to_news_semantic_gap.csv
    data/04_analysis/news_to_youtube_semantic_gap.csv

Outputs:
    data/05_figures/reading_discourse_relation_distribution.png
    data/05_figures/reading_discourse_top15_semantic_gaps.png
    data/05_figures/reading_discourse_top15_semantic_near.png
    data/05_figures/reading_discourse_similarity_distribution.png
    data/04_analysis/reading_discourse_semantic_visual_summary.csv
"""

from __future__ import annotations

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".codex_deps" / "matplotlib"))

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager, rcParams


ANALYSIS_DIR = ROOT / "data" / "04_analysis"
FIGURE_DIR = ROOT / "data" / "05_figures"

YOUTUBE_TO_NEWS_CSV = ANALYSIS_DIR / "youtube_to_news_semantic_gap.csv"
NEWS_TO_YOUTUBE_CSV = ANALYSIS_DIR / "news_to_youtube_semantic_gap.csv"
SUMMARY_CSV = ANALYSIS_DIR / "reading_discourse_semantic_visual_summary.csv"

RELATION_DISTRIBUTION_PNG = FIGURE_DIR / "reading_discourse_relation_distribution.png"
TOP_GAPS_PNG = FIGURE_DIR / "reading_discourse_top15_semantic_gaps.png"
TOP_NEAR_PNG = FIGURE_DIR / "reading_discourse_top15_semantic_near.png"
SIMILARITY_DISTRIBUTION_PNG = FIGURE_DIR / "reading_discourse_similarity_distribution.png"

RELATION_ORDER = ["semantic_near", "semantic_bridge", "semantic_gap"]
RELATION_COLORS = {
    "semantic_near": "#2F6B4F",
    "semantic_bridge": "#D59A2B",
    "semantic_gap": "#B84A4A",
}


class MissingColumnsError(ValueError):
    pass


def setup_korean_font() -> None:
    """Use an installed Korean-capable font when available."""
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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def validate_youtube_to_news(df: pd.DataFrame) -> None:
    required = {
        "youtube_keyword",
        "nearest_news_keyword",
        "similarity",
        "relation_type",
        "youtube_core_score",
        "news_core_score",
    }
    missing = required - set(df.columns)
    if missing:
        raise MissingColumnsError(
            f"Missing required columns in {YOUTUBE_TO_NEWS_CSV}: {sorted(missing)}"
        )


def validate_news_to_youtube_reference(df: pd.DataFrame) -> None:
    required = {
        "news_keyword",
        "nearest_youtube_keyword",
        "similarity",
        "relation_type",
        "news_core_score",
        "youtube_core_score",
    }
    missing = required - set(df.columns)
    if missing:
        raise MissingColumnsError(
            f"Missing required columns in {NEWS_TO_YOUTUBE_CSV}: {sorted(missing)}"
        )


def prepare_youtube_to_news(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    prepared["similarity"] = pd.to_numeric(prepared["similarity"], errors="coerce")
    prepared["youtube_core_score"] = pd.to_numeric(
        prepared["youtube_core_score"], errors="coerce"
    )
    prepared["news_core_score"] = pd.to_numeric(
        prepared["news_core_score"], errors="coerce"
    )
    prepared["youtube_keyword"] = prepared["youtube_keyword"].astype(str)
    prepared["nearest_news_keyword"] = prepared["nearest_news_keyword"].astype(str)
    prepared["relation_type"] = prepared["relation_type"].astype(str)
    prepared = prepared.dropna(subset=["similarity"])
    return prepared.reset_index(drop=True)


def save_summary(df: pd.DataFrame) -> None:
    columns = [
        "youtube_keyword",
        "nearest_news_keyword",
        "similarity",
        "relation_type",
        "youtube_core_score",
        "news_core_score",
    ]
    df.loc[:, columns].to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")


def save_current_figure(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()


def plot_relation_distribution(df: pd.DataFrame) -> None:
    counts = df["relation_type"].value_counts().reindex(RELATION_ORDER, fill_value=0)
    colors = [RELATION_COLORS[label] for label in counts.index]

    plt.figure(figsize=(8, 5))
    bars = plt.bar(counts.index, counts.values, color=colors)
    plt.title("Relation Type Distribution in Reading Discourse", pad=14)
    plt.xlabel("relation_type")
    plt.ylabel("keyword pair count")
    plt.grid(axis="y", alpha=0.25)
    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            f"{int(height)}",
            ha="center",
            va="bottom",
        )
    save_current_figure(RELATION_DISTRIBUTION_PNG)


def pair_label(frame: pd.DataFrame) -> pd.Series:
    return frame["youtube_keyword"] + " - " + frame["nearest_news_keyword"]


def plot_horizontal_pairs(df: pd.DataFrame, title: str, path: Path, color: str) -> None:
    plot_df = df.copy()
    plot_df["pair"] = pair_label(plot_df)
    plot_df = plot_df.iloc[::-1]

    height = max(6, 0.42 * len(plot_df) + 1.5)
    plt.figure(figsize=(10, height))
    plt.barh(plot_df["pair"], plot_df["similarity"], color=color)
    plt.title(title, pad=14)
    plt.xlabel("similarity")
    plt.ylabel("youtube_keyword - nearest_news_keyword")
    plt.xlim(0, max(1.0, float(plot_df["similarity"].max()) + 0.05))
    plt.grid(axis="x", alpha=0.25)
    save_current_figure(path)


def plot_top_semantic_gaps(df: pd.DataFrame) -> None:
    gaps = (
        df.loc[df["relation_type"] == "semantic_gap"]
        .sort_values(["similarity", "youtube_keyword"], ascending=[True, True])
        .head(15)
    )
    plot_horizontal_pairs(
        gaps,
        "Top Semantic Gaps in Reading Discourse",
        TOP_GAPS_PNG,
        RELATION_COLORS["semantic_gap"],
    )


def select_top_near(df: pd.DataFrame) -> pd.DataFrame:
    near = df.loc[df["relation_type"] == "semantic_near"].sort_values(
        ["similarity", "youtube_keyword"], ascending=[False, True]
    )
    if len(near) >= 15:
        return near.head(15)

    bridge_needed = 15 - len(near)
    bridge = df.loc[df["relation_type"] == "semantic_bridge"].sort_values(
        ["similarity", "youtube_keyword"], ascending=[False, True]
    )
    return pd.concat([near, bridge.head(bridge_needed)], ignore_index=True)


def plot_top_semantic_near(df: pd.DataFrame) -> None:
    top_near = select_top_near(df)
    plot_horizontal_pairs(
        top_near,
        "Top Semantic Near Pairs between Reading Discourse and News Trends",
        TOP_NEAR_PNG,
        RELATION_COLORS["semantic_near"],
    )


def plot_similarity_distribution(df: pd.DataFrame) -> None:
    plt.figure(figsize=(8, 5))
    plt.hist(df["similarity"], bins=15, color="#4B6F9E", edgecolor="white")
    plt.title("Similarity Distribution in Reading Discourse", pad=14)
    plt.xlabel("similarity")
    plt.ylabel("keyword pair count")
    plt.grid(axis="y", alpha=0.25)
    save_current_figure(SIMILARITY_DISTRIBUTION_PNG)


def main() -> None:
    setup_korean_font()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    youtube_to_news = read_csv(YOUTUBE_TO_NEWS_CSV)
    news_to_youtube = read_csv(NEWS_TO_YOUTUBE_CSV)
    validate_youtube_to_news(youtube_to_news)
    validate_news_to_youtube_reference(news_to_youtube)

    youtube_to_news = prepare_youtube_to_news(youtube_to_news)
    save_summary(youtube_to_news)

    plot_relation_distribution(youtube_to_news)
    plot_top_semantic_gaps(youtube_to_news)
    plot_top_semantic_near(youtube_to_news)
    plot_similarity_distribution(youtube_to_news)

    print("saved:")
    for path in [
        RELATION_DISTRIBUTION_PNG,
        TOP_GAPS_PNG,
        TOP_NEAR_PNG,
        SIMILARITY_DISTRIBUTION_PNG,
        SUMMARY_CSV,
    ]:
        print(f"- {path}")


if __name__ == "__main__":
    main()


