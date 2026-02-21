#!/usr/bin/env python3
"""
Build product taxonomy from raw SKU descriptions:
1. Clean descriptions (strip colours, quantities, pack sizes)
2. Embed unique descriptions using a local sentence transformer model
3. Cluster embeddings with k-means to group similar products
4. Label each cluster with a short human-friendly category name
5. Persist category assignments to dim_product with a taxonomy version tag
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
import re

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize

from backend.app.agents.base import build_llm
from backend.app.core.config import get_settings
from backend.app.core.database import initialize_schema
from backend.app.core.logging import configure_logging, get_logger
from langchain_core.messages import HumanMessage, SystemMessage

configure_logging()
logger = get_logger(__name__)


def clean_description(desc: str) -> str:
    """Remove quantities, colors, pack sizes from description."""
    desc = desc.upper().strip()
    desc = re.sub(r"\b\d+\s?(PK|PACK|SET|PIECE|PC|CM|MM|G|KG|ML|L)\b", "", desc)
    desc = re.sub(r"\b(RED|BLUE|GREEN|YELLOW|PINK|BLACK|WHITE|GOLD|SILVER|CREAM|GREY|GRAY)\b", "", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc


def label_cluster(llm, descriptions: list[str], cluster_id: int) -> str:
    """Ask the language model to assign a short category name to a cluster of product descriptions."""
    sample = descriptions[:20]
    prompt = (
        f"These product descriptions belong to cluster {cluster_id}:\n"
        + "\n".join(f"  - {d}" for d in sample)
        + "\n\nProvide a short (2-4 words), human-friendly category name for this cluster. "
        "Return ONLY the category name, nothing else."
    )
    response = llm.invoke([
        SystemMessage(content="You are a retail product categorization expert."),
        HumanMessage(content=prompt),
    ])
    return response.content.strip().title()


def main(n_clusters: int = 30, taxonomy_version: str = "v1") -> None:
    settings = get_settings()
    db_path = str(settings.duckdb_path)

    conn = duckdb.connect(db_path)
    initialize_schema(conn)

    # Load unique stock codes + descriptions
    rows = conn.execute(
        "SELECT DISTINCT stock_code, description FROM fact_sales WHERE description != ''"
    ).fetchall()
    conn.close()

    if not rows:
        logger.error("taxonomy.no_data", hint="Run ingest.py first")
        return

    df = pd.DataFrame(rows, columns=["stock_code", "description"])
    df["clean_desc"] = df["description"].apply(clean_description)

    unique_descs = df["clean_desc"].unique().tolist()
    logger.info("taxonomy.embedding", n_descriptions=len(unique_descs))

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(settings.embedding_model)
    embeddings = model.encode(unique_descs, show_progress_bar=True, batch_size=64)
    embeddings_norm = normalize(embeddings)

    # Cluster
    n_clusters = min(n_clusters, len(unique_descs))
    logger.info("taxonomy.clustering", n_clusters=n_clusters)
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(embeddings_norm)

    desc_to_cluster = dict(zip(unique_descs, labels.tolist()))
    df["cluster_id"] = df["clean_desc"].map(desc_to_cluster)

    # Label clusters
    llm = build_llm(settings)
    cluster_labels: dict[int, str] = {}
    for cid in range(n_clusters):
        cluster_descs = df[df["cluster_id"] == cid]["description"].tolist()
        label = label_cluster(llm, cluster_descs, cid)
        cluster_labels[cid] = label
        logger.info("taxonomy.cluster_labeled", cluster_id=cid, label=label)

    df["category_name"] = df["cluster_id"].map(cluster_labels)
    df["category_id"] = df["cluster_id"]
    df["taxonomy_version"] = taxonomy_version
    df["canonical_description"] = df["clean_desc"]

    # Persist to dim_product
    conn = duckdb.connect(db_path)
    conn.execute("DELETE FROM dim_product")
    dim_df = df[["stock_code", "canonical_description", "category_id", "category_name",
                 "cluster_id", "taxonomy_version"]].drop_duplicates("stock_code")
    conn.execute("INSERT INTO dim_product SELECT * FROM dim_df")
    count = conn.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0]
    conn.close()

    logger.info("taxonomy.done", rows=count, version=taxonomy_version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build product taxonomy")
    parser.add_argument("--n_clusters", type=int, default=30)
    parser.add_argument("--version", type=str, default="v1")
    args = parser.parse_args()
    main(args.n_clusters, args.version)
