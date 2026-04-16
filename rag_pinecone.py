import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from dotenv import dotenv_values
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_ENV_PATH = Path("/root/maria-helena/.env")
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384
DEFAULT_METRIC = "cosine"
DEFAULT_TOP_K = 5
DEFAULT_FAISS_INDEX_PATH = DATA_DIR / "rag_faiss.index"
DEFAULT_FAISS_SQLITE_PATH = DATA_DIR / "rag_faiss.sqlite"

STRUCTURED_FILES = (
    "gate_report.json",
    "holdout_metrics.json",
    "purged_walkforward_metrics.json",
    "robustness_grid_summary.json",
    "risk_execution_metrics.json",
    "walkforward_backtest_metrics.json",
    "xauusd_candles_summary.json",
    "xauusd_feature_table_meta.json",
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _stringify(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _pinecone_index_names(pc: Pinecone) -> list[str]:
    listing = pc.list_indexes()
    if hasattr(listing, "names"):
        return list(listing.names())
    if isinstance(listing, list):
        names: list[str] = []
        for item in listing:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    names.append(name)
            else:
                name = getattr(item, "name", None)
                if isinstance(name, str):
                    names.append(name)
        return names
    return []


def _parse_benzinga_docs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _load_json(path)
    if not isinstance(payload, list):
        return []

    docs: list[dict[str, Any]] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("headline") or "Sem título"
        summary = item.get("summary") or item.get("teaser") or ""
        keywords = item.get("matched_keywords") or []
        created = item.get("created") or item.get("updated") or item.get("date")
        text = (
            f"[BENZINGA]\n"
            f"title: {title}\n"
            f"time: {created}\n"
            f"keywords: {keywords}\n"
            f"summary: {summary}\n"
            f"raw: {_stringify(item)}"
        )
        doc_id = f"benzinga-{idx}-{_hash_text(title + str(created))[:12]}"
        docs.append(
            {
                "id": doc_id,
                "text": text,
                "metadata": {
                    "source": "benzinga_relevant_news.json",
                    "type": "news",
                    "time": str(created or ""),
                    "title": str(title)[:120],
                },
            }
        )
    return docs


def _parse_structured_docs(data_dir: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for filename in STRUCTURED_FILES:
        path = data_dir / filename
        if not path.exists():
            continue
        try:
            payload = _load_json(path)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Falha lendo {path}: {exc}")
            continue
        text = f"[{filename}]\n{_stringify(payload)}"
        doc_id = f"metrics-{filename.replace('.', '-')}"
        docs.append(
            {
                "id": doc_id,
                "text": text,
                "metadata": {"source": filename, "type": "metrics"},
            }
        )
    return docs


def load_documents(data_dir: Path) -> list[dict[str, Any]]:
    documents = []
    documents.extend(_parse_structured_docs(data_dir))
    documents.extend(_parse_benzinga_docs(data_dir / "benzinga_relevant_news.json"))
    return documents


def embed_documents(model_name: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not docs:
        return []
    model = SentenceTransformer(model_name)
    vectors = model.encode(
        [doc["text"] for doc in docs],
        normalize_embeddings=True,
    )
    items: list[dict[str, Any]] = []
    for doc, vector in zip(docs, vectors):
        items.append(
            {
                "id": doc["id"],
                "values": vector.tolist(),
                "metadata": {
                    **doc["metadata"],
                    "text": doc["text"][:3500],
                },
            }
        )
    return items


def ensure_index(
    pc: Pinecone,
    index_name: str,
    dimension: int,
    metric: str,
    cloud: str,
    region: str,
) -> None:
    names = _pinecone_index_names(pc)
    if index_name in names:
        description = pc.describe_index(index_name)
        existing_dimension = None
        if isinstance(description, dict):
            existing_dimension = description.get("dimension")
        else:
            existing_dimension = getattr(description, "dimension", None)
        if existing_dimension and int(existing_dimension) != dimension:
            raise ValueError(
                f"Index {index_name} já existe com dimensão {existing_dimension}, "
                f"mas embeddings usam dimensão {dimension}."
            )
        return

    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric=metric,
        spec=ServerlessSpec(cloud=cloud, region=region),
    )
    print(f"✅ Index criado: {index_name} ({dimension}d, {metric})")


def upsert_vectors(
    pc: Pinecone,
    index_name: str,
    namespace: str,
    vectors: list[dict[str, Any]],
    batch_size: int = 100,
) -> None:
    if not vectors:
        print("⚠️ Nenhum vetor para indexar.")
        return
    index = pc.Index(index_name)
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start : start + batch_size]
        index.upsert(vectors=batch, namespace=namespace)
    print(f"✅ Upsert concluído: {len(vectors)} vetores no namespace '{namespace}'")


def run_query(
    pc: Pinecone,
    index_name: str,
    namespace: str,
    model_name: str,
    question: str,
    top_k: int,
) -> dict[str, Any]:
    model = SentenceTransformer(model_name)
    vector = model.encode([question], normalize_embeddings=True)[0].tolist()
    index = pc.Index(index_name)
    response = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    return response


def _faiss_init(index_path: Path, dimension: int) -> faiss.IndexFlatIP:
    if index_path.exists():
        return faiss.read_index(str(index_path))
    return faiss.IndexFlatIP(dimension)


def _faiss_prepare_sqlite(sqlite_path: Path) -> sqlite3.Connection:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_docs (
            vector_id INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            source TEXT,
            doc_type TEXT,
            metadata_json TEXT,
            text TEXT
        )
        """
    )
    conn.commit()
    return conn


def _upsert_faiss(
    vectors: list[dict[str, Any]],
    index_path: Path,
    sqlite_path: Path,
    dimension: int,
) -> None:
    if not vectors:
        print("⚠️ Nenhum vetor para indexar no fallback FAISS.")
        return
    index = _faiss_init(index_path, dimension=dimension)
    conn = _faiss_prepare_sqlite(sqlite_path)

    for item in vectors:
        vector = np.array(item["values"], dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != dimension:
            raise ValueError(
                f"Dimensão FAISS incompatível: vetor {vector.shape[1]} != {dimension}"
            )
        next_id = index.ntotal
        index.add(vector)
        metadata = item.get("metadata", {})
        conn.execute(
            """
            INSERT OR REPLACE INTO rag_docs(vector_id, doc_id, source, doc_type, metadata_json, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(next_id),
                str(item["id"]),
                str(metadata.get("source", "")),
                str(metadata.get("type", "")),
                json.dumps(metadata, ensure_ascii=False),
                str(metadata.get("text", "")),
            ),
        )

    conn.commit()
    conn.close()
    faiss.write_index(index, str(index_path))
    print(f"✅ FAISS fallback salvo em {index_path}")
    print(f"✅ Metadata fallback salva em {sqlite_path}")


def _query_faiss(
    question: str,
    model_name: str,
    top_k: int,
    index_path: Path,
    sqlite_path: Path,
) -> dict[str, Any]:
    if not index_path.exists() or not sqlite_path.exists():
        raise ValueError(
            f"Fallback FAISS indisponível. Index: {index_path} | SQLite: {sqlite_path}"
        )
    index = faiss.read_index(str(index_path))
    model = SentenceTransformer(model_name)
    query_vector = model.encode([question], normalize_embeddings=True)
    query_vector = np.array(query_vector, dtype=np.float32)
    distances, indices = index.search(query_vector, top_k)

    conn = sqlite3.connect(sqlite_path)
    results = []
    for score, idx in zip(distances[0], indices[0]):
        if int(idx) < 0:
            continue
        row = conn.execute(
            "SELECT doc_id, source, doc_type, metadata_json, text FROM rag_docs WHERE vector_id = ?",
            (int(idx),),
        ).fetchone()
        if not row:
            continue
        doc_id, source, doc_type, metadata_json, text = row
        try:
            metadata = json.loads(metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        results.append(
            {
                "id": doc_id,
                "score": float(score),
                "source": source,
                "type": doc_type,
                "metadata": metadata,
                "text": text,
            }
        )
    conn.close()
    return {"matches": results}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Pinecone para contexto institucional do Maria Helena.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Indexa contexto local no Pinecone")
    index_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    index_parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    index_parser.add_argument("--dimension", type=int, default=DEFAULT_DIMENSION)
    index_parser.add_argument("--metric", type=str, default=DEFAULT_METRIC)
    index_parser.add_argument("--cloud", type=str, default="aws")
    index_parser.add_argument("--region", type=str, default="us-east-1")
    index_parser.add_argument("--index-name", type=str, default="")
    index_parser.add_argument("--namespace", type=str, default="")
    index_parser.add_argument("--store", type=str, choices=("pinecone", "faiss", "auto"), default="auto")
    index_parser.add_argument("--faiss-index-path", type=Path, default=DEFAULT_FAISS_INDEX_PATH)
    index_parser.add_argument("--faiss-sqlite-path", type=Path, default=DEFAULT_FAISS_SQLITE_PATH)

    query_parser = subparsers.add_parser("query", help="Consulta contexto no Pinecone")
    query_parser.add_argument("--question", type=str, default="")
    query_parser.add_argument("--text", type=str, default="")
    query_parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    query_parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    query_parser.add_argument("--index-name", type=str, default="")
    query_parser.add_argument("--namespace", type=str, default="")
    query_parser.add_argument("--store", type=str, choices=("pinecone", "faiss", "auto"), default="auto")
    query_parser.add_argument("--faiss-index-path", type=Path, default=DEFAULT_FAISS_INDEX_PATH)
    query_parser.add_argument("--faiss-sqlite-path", type=Path, default=DEFAULT_FAISS_SQLITE_PATH)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = dotenv_values(args.env_file)

    pinecone_api_key = (cfg.get("PINECONE_API_KEY") or "").strip()

    index_name = getattr(args, "index_name", "") or (cfg.get("PINECONE_INDEX_NAME") or "").strip()
    namespace = getattr(args, "namespace", "") or (cfg.get("PINECONE_NAMESPACE") or "maria-helena").strip()
    if args.store in {"pinecone", "auto"} and not index_name and args.store == "pinecone":
        raise ValueError("Defina PINECONE_INDEX_NAME no .env ou --index-name")

    if args.command == "index":
        docs = load_documents(args.data_dir)
        print(f"Documentos carregados: {len(docs)}")
        vectors = embed_documents(args.embedding_model, docs)

        if args.store == "faiss":
            _upsert_faiss(
                vectors=vectors,
                index_path=args.faiss_index_path,
                sqlite_path=args.faiss_sqlite_path,
                dimension=args.dimension,
            )
            return

        if args.store in {"pinecone", "auto"}:
            try:
                if not pinecone_api_key:
                    raise ValueError("PINECONE_API_KEY não encontrado no .env")
                if not index_name:
                    raise ValueError("Defina PINECONE_INDEX_NAME no .env ou --index-name")
                pc = Pinecone(api_key=pinecone_api_key)
                ensure_index(
                    pc=pc,
                    index_name=index_name,
                    dimension=args.dimension,
                    metric=args.metric,
                    cloud=args.cloud,
                    region=args.region,
                )
                upsert_vectors(
                    pc=pc,
                    index_name=index_name,
                    namespace=namespace,
                    vectors=vectors,
                )
                return
            except Exception as exc:  # noqa: BLE001
                if args.store == "pinecone":
                    raise
                print(f"⚠️ Pinecone indisponível, usando fallback FAISS. Motivo: {exc}")
                _upsert_faiss(
                    vectors=vectors,
                    index_path=args.faiss_index_path,
                    sqlite_path=args.faiss_sqlite_path,
                    dimension=args.dimension,
                )
                return
        return

    if args.command == "query":
        question = (args.question or args.text or "").strip()
        if not question:
            raise ValueError("Informe a pergunta com --question ou --text")

        if args.store == "faiss":
            response = _query_faiss(
                question=question,
                model_name=args.embedding_model,
                top_k=args.top_k,
                index_path=args.faiss_index_path,
                sqlite_path=args.faiss_sqlite_path,
            )
            print("✅ Resultado da consulta RAG (FAISS fallback):")
            print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
            return

        if args.store in {"pinecone", "auto"}:
            try:
                if not pinecone_api_key:
                    raise ValueError("PINECONE_API_KEY não encontrado no .env")
                if not index_name:
                    raise ValueError("Defina PINECONE_INDEX_NAME no .env ou --index-name")
                pc = Pinecone(api_key=pinecone_api_key)
                response = run_query(
                    pc=pc,
                    index_name=index_name,
                    namespace=namespace,
                    model_name=args.embedding_model,
                    question=question,
                    top_k=args.top_k,
                )
                print("✅ Resultado da consulta RAG (Pinecone):")
                print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
                return
            except Exception as exc:  # noqa: BLE001
                if args.store == "pinecone":
                    raise
                print(f"⚠️ Pinecone indisponível, usando fallback FAISS. Motivo: {exc}")
                response = _query_faiss(
                    question=question,
                    model_name=args.embedding_model,
                    top_k=args.top_k,
                    index_path=args.faiss_index_path,
                    sqlite_path=args.faiss_sqlite_path,
                )
                print("✅ Resultado da consulta RAG (FAISS fallback):")
                print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
                return

        print("✅ Resultado da consulta RAG:")
        print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
        return


if __name__ == "__main__":
    main()
