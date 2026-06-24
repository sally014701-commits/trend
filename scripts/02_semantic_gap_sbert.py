"""
KoSentenceBERT semantic gap analysis between news-only and YouTube-only keywords.

Run:
    python scripts/02_semantic_gap_sbert.py

Required packages:
    pandas
    numpy
    sentence-transformers
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer


MODEL_NAME = "snunlp/KR-SBERT-V40K-klueNLI-augSTS"

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = ROOT / "data" / "04_analysis"
INPUT_CSV = ANALYSIS_DIR / "keyword_overlap_result.csv"

NEWS_TO_YOUTUBE_CSV = ANALYSIS_DIR / "news_to_youtube_semantic_gap.csv"
YOUTUBE_TO_NEWS_CSV = ANALYSIS_DIR / "youtube_to_news_semantic_gap.csv"
SUMMARY_JSON = ANALYSIS_DIR / "semantic_gap_summary.json"


def relation_type(similarity: float) -> str:
    if similarity >= 0.55:
        return "semantic_near"
    if similarity >= 0.40:
        return "semantic_bridge"
    return "semantic_gap"


def load_keywords() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    required = {"keyword", "group", "news_core_score", "youtube_core_score"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {INPUT_CSV}: {sorted(missing)}")

    news_only = df.loc[df["group"] == "news_only", ["keyword", "news_core_score"]].copy()
    youtube_only = df.loc[
        df["group"] == "youtube_only", ["keyword", "youtube_core_score"]
    ].copy()

    news_only["keyword"] = news_only["keyword"].astype(str)
    youtube_only["keyword"] = youtube_only["keyword"].astype(str)
    news_only["news_core_score"] = pd.to_numeric(
        news_only["news_core_score"], errors="coerce"
    )
    youtube_only["youtube_core_score"] = pd.to_numeric(
        youtube_only["youtube_core_score"], errors="coerce"
    )

    news_only = news_only.dropna(subset=["keyword"]).drop_duplicates("keyword")
    youtube_only = youtube_only.dropna(subset=["keyword"]).drop_duplicates("keyword")

    if news_only.empty or youtube_only.empty:
        raise ValueError(
            "Both news_only and youtube_only keyword groups must contain at least one row."
        )

    return news_only.reset_index(drop=True), youtube_only.reset_index(drop=True)


def embed_keywords(model: SentenceTransformer, keywords: list[str]) -> np.ndarray:
    return model.encode(
        keywords,
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )


def build_similarity_outputs(
    news_only: pd.DataFrame,
    youtube_only: pd.DataFrame,
    similarity_matrix: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    news_best_youtube_idx = similarity_matrix.argmax(axis=1)
    news_best_similarity = similarity_matrix[
        np.arange(similarity_matrix.shape[0]), news_best_youtube_idx
    ]

    news_to_youtube_rows = []
    for news_idx, youtube_idx in enumerate(news_best_youtube_idx):
        similarity = float(news_best_similarity[news_idx])
        news_row = news_only.iloc[news_idx]
        youtube_row = youtube_only.iloc[youtube_idx]
        news_to_youtube_rows.append(
            {
                "news_keyword": news_row["keyword"],
                "nearest_youtube_keyword": youtube_row["keyword"],
                "similarity": similarity,
                "relation_type": relation_type(similarity),
                "news_core_score": news_row["news_core_score"],
                "youtube_core_score": youtube_row["youtube_core_score"],
            }
        )

    youtube_best_news_idx = similarity_matrix.argmax(axis=0)
    youtube_best_similarity = similarity_matrix[
        youtube_best_news_idx, np.arange(similarity_matrix.shape[1])
    ]

    youtube_to_news_rows = []
    for youtube_idx, news_idx in enumerate(youtube_best_news_idx):
        similarity = float(youtube_best_similarity[youtube_idx])
        youtube_row = youtube_only.iloc[youtube_idx]
        news_row = news_only.iloc[news_idx]
        youtube_to_news_rows.append(
            {
                "youtube_keyword": youtube_row["keyword"],
                "nearest_news_keyword": news_row["keyword"],
                "similarity": similarity,
                "relation_type": relation_type(similarity),
                "youtube_core_score": youtube_row["youtube_core_score"],
                "news_core_score": news_row["news_core_score"],
            }
        )

    news_to_youtube = pd.DataFrame(news_to_youtube_rows).sort_values(
        ["similarity", "news_keyword"],
        ascending=[False, True],
        kind="mergesort",
    )
    youtube_to_news = pd.DataFrame(youtube_to_news_rows).sort_values(
        ["similarity", "youtube_keyword"],
        ascending=[False, True],
        kind="mergesort",
    )
    return news_to_youtube, youtube_to_news


def build_summary(
    news_to_youtube: pd.DataFrame,
    youtube_to_news: pd.DataFrame,
    news_only_count: int,
    youtube_only_count: int,
) -> dict:
    combined = pd.concat(
        [
            news_to_youtube.assign(direction="news_to_youtube").rename(
                columns={
                    "news_keyword": "source_keyword",
                    "nearest_youtube_keyword": "nearest_keyword",
                }
            ),
            youtube_to_news.assign(direction="youtube_to_news").rename(
                columns={
                    "youtube_keyword": "source_keyword",
                    "nearest_news_keyword": "nearest_keyword",
                }
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    relation_counts = combined["relation_type"].value_counts().to_dict()
    examples_cols = [
        "direction",
        "source_keyword",
        "nearest_keyword",
        "similarity",
        "relation_type",
    ]

    lowest = (
        combined.sort_values(["similarity", "source_keyword"], ascending=[True, True])
        .head(10)[examples_cols]
        .to_dict("records")
    )
    highest = (
        combined.sort_values(["similarity", "source_keyword"], ascending=[False, True])
        .head(10)[examples_cols]
        .to_dict("records")
    )

    return {
        "model_name": MODEL_NAME,
        "news_only_count": int(news_only_count),
        "youtube_only_count": int(youtube_only_count),
        "semantic_near_count": int(relation_counts.get("semantic_near", 0)),
        "semantic_bridge_count": int(relation_counts.get("semantic_bridge", 0)),
        "semantic_gap_count": int(relation_counts.get("semantic_gap", 0)),
        "average_similarity": float(combined["similarity"].mean()),
        "lowest_similarity_examples_top10": lowest,
        "highest_similarity_examples_top10": highest,
    }


def main() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    news_only, youtube_only = load_keywords()
    print(f"news_only keywords: {len(news_only)}")
    print(f"youtube_only keywords: {len(youtube_only)}")
    print(f"loading model: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)
    news_embeddings = embed_keywords(model, news_only["keyword"].tolist())
    youtube_embeddings = embed_keywords(model, youtube_only["keyword"].tolist())

    similarity_matrix = news_embeddings @ youtube_embeddings.T
    news_to_youtube, youtube_to_news = build_similarity_outputs(
        news_only,
        youtube_only,
        similarity_matrix,
    )
    summary = build_summary(
        news_to_youtube,
        youtube_to_news,
        len(news_only),
        len(youtube_only),
    )

    news_to_youtube.to_csv(NEWS_TO_YOUTUBE_CSV, index=False, encoding="utf-8-sig")
    youtube_to_news.to_csv(YOUTUBE_TO_NEWS_CSV, index=False, encoding="utf-8-sig")
    SUMMARY_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("saved:")
    print(f"- {NEWS_TO_YOUTUBE_CSV}")
    print(f"- {YOUTUBE_TO_NEWS_CSV}")
    print(f"- {SUMMARY_JSON}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
