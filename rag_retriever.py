import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from dotenv import dotenv_values
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from rag_pinecone import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ENV_PATH,
    DEFAULT_TOP_K,
    embed_documents,
    load_documents,
)

DATA_DIR = Path("/root/maria-helena/data")
LOCAL_RAG_DIR = DATA_DIR / "local_rag"
DEFAULT_FAISS_INDEX = LOCAL_RAG_DIR / "index.faiss"
DEFAULT_SQLITE_DB = LOCAL_RAG_DIR / "metadata.sqlite3"


def _ensure_local_rag_store(sqlite_db: Path) -> sqlite3.Connection:
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_docs (
            id TEXT PRIMARY KEY,
            source TEXT,
            type TEXT,
            time TEXT,
            title TEXT,
            text TEXT
        )
        """
    )
    conn.commit()
    return conn


def index_local_faiss(
    data_dir: Path,
    embedding_model: str,
    faiss_index_path: Path,
    sqlite_db: Path,
) -> dict[str, Any]:
    docs = load_documents(data_dir)
    vectors = embed_documents(embedding_model, docs)
    if not vectors:
        return {"indexed_docs": 0, "note": "no documents"}

    dim = len(vectors[0]["values"])
    matrix = np.array([item["values"] for item in vectors], dtype=np.float32)
    index = faiss.IndexFlatIP(dim)
    index.add(matrix)
    faiss_index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(faiss_index_path))

    conn = _ensure_local_rag_store(sqlite_db)
    conn.execute("DELETE FROM rag_docs")
    for item in vectors:
        meta = item.get("metadata", {})
        conn.execute(
            """
            INSERT OR REPLACE INTO rag_docs(id, source, type, time, title, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                str(meta.get("source") or ""),
                str(meta.get("type") or ""),
                str(meta.get("time") or ""),
                str(meta.get("title") or ""),
                str(meta.get("text") or ""),
            ),
        )
    conn.commit()
    conn.close()

    with (faiss_index_path.parent / "ids.json").open("w", encoding="utf-8") as fp:
        json.dump([item["id"] for item in vectors], fp, ensure_ascii=False)

    return {"indexed_docs": len(vectors), "dimension": dim}


def query_local_faiss(
    query_text: str,
    embedding_model: str,
    top_k: int,
    faiss_index_path: Path,
    sqlite_db: Path,
) -> dict[str, Any]:
    if not faiss_index_path.exists():
        raise ValueError(f"FAISS index não encontrado: {faiss_index_path}")

    ids_path = faiss_index_path.parent / "ids.json"
    if not ids_path.exists():
        raise ValueError(f"Arquivo ids.json não encontrado: {ids_path}")

    with ids_path.open("r", encoding="utf-8") as fp:
        ids = json.load(fp)
    if not isinstance(ids, list):
        raise ValueError("ids.json inválido")

    model = SentenceTransformer(embedding_model)
    qv = model.encode([query_text], normalize_embeddings=True)
    qv = np.array(qv, dtype=np.float32)

    index = faiss.read_index(str(faiss_index_path))
    scores, indices = index.search(qv, top_k)

    conn = sqlite3.connect(sqlite_db)
    results = []
    for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
        if idx < 0 or idx >= len(ids):
            continue
        doc_id = ids[idx]
        row = conn.execute(
            "SELECT id, source, type, time, title, text FROM rag_docs WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if not row:
            continue
        results.append(
            {
                "score": score,
                "id": row[0],
                "metadata": {
                    "source": row[1],
                    "type": row[2],
                    "time": row[3],
                    "title": row[4],
                },
                "text": row[5],
            }
        )
    conn.close()
    return {"matches": results}


def query_pinecone(
    cfg: dict[str, Any],
    query_text: str,
    embedding_model: str,
    top_k: int,
    index_name: str | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    api_key = (cfg.get("PINECONE_API_KEY") or "").strip()
    idx_name = index_name or (cfg.get("PINECONE_INDEX_NAME") or "").strip()
    ns = namespace or (cfg.get("PINECONE_NAMESPACE") or "default").strip()
    if not api_key:
        raise ValueError("PINECONE_API_KEY ausente")
    if not idx_name:
        raise ValueError("PINECONE_INDEX_NAME ausente")

    model = SentenceTransformer(embedding_model)
    vector = model.encode([query_text], normalize_embeddings=True)[0].tolist()
    pc = Pinecone(api_key=api_key)
    index = pc.Index(idx_name)
    response = index.query(vector=vector, top_k=top_k, namespace=ns, include_metadata=True)
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retriever com fallback Pinecone -> FAISS/SQLite para Maria Helena."
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--faiss-index", type=Path, default=DEFAULT_FAISS_INDEX)
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_DB)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("index-local", help="Indexa documentos locais em FAISS/SQLite")

    query_parser = subparsers.add_parser("query", help="Consulta com fallback")
    query_parser.add_argument("--text", type=str, required=True)
    query_parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    query_parser.add_argument("--prefer", type=str, choices=("pinecone", "faiss"), default="pinecone")
    query_parser.add_argument("--index-name", type=str, default="")
    query_parser.add_argument("--namespace", type=str, default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = dotenv_values(args.env_file)

    if args.command == "index-local":
        result = index_local_faiss(
            data_dir=args.data_dir,
            embedding_model=args.embedding_model,
            faiss_index_path=args.faiss_index,
            sqlite_db=args.sqlite_db,
        )
        print("✅ Index local atualizado.")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.command == "query":
        last_error = None
        if args.prefer == "pinecone":
            try:
                pinecone_result = query_pinecone(
                    cfg=cfg,
                    query_text=args.text,
                    embedding_model=args.embedding_model,
                    top_k=args.top_k,
                    index_name=args.index_name or None,
                    namespace=args.namespace or None,
                )
                print("✅ Query via Pinecone")
                print(json.dumps(pinecone_result, ensure_ascii=False, indent=2, default=str))
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                print(f"⚠️ Pinecone indisponível, fallback para FAISS: {exc}")

        try:
            local_result = query_local_faiss(
                query_text=args.text,
                embedding_model=args.embedding_model,
                top_k=args.top_k,
                faiss_index_path=args.faiss_index,
                sqlite_db=args.sqlite_db,
            )
            print("✅ Query via FAISS/SQLite")
            print(json.dumps(local_result, ensure_ascii=False, indent=2, default=str))
            return
        except Exception as exc:  # noqa: BLE001
            if last_error:
                raise ValueError(
                    f"Pinecone falhou: {last_error}. Fallback FAISS também falhou: {exc}"
                ) from exc
            raise


if __name__ == "__main__":
    main()
