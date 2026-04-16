import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_ENV_PATH = Path("/root/maria-helena/.env")
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384
DEFAULT_METRIC = "cosine"
DEFAULT_TOP_K = 5

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

    query_parser = subparsers.add_parser("query", help="Consulta contexto no Pinecone")
    query_parser.add_argument("--question", type=str, default="")
    query_parser.add_argument("--text", type=str, default="")
    query_parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    query_parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    query_parser.add_argument("--index-name", type=str, default="")
    query_parser.add_argument("--namespace", type=str, default="")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = dotenv_values(args.env_file)

    pinecone_api_key = (cfg.get("PINECONE_API_KEY") or "").strip()
    if not pinecone_api_key:
        raise ValueError("PINECONE_API_KEY não encontrado no .env")

    index_name = getattr(args, "index_name", "") or (cfg.get("PINECONE_INDEX_NAME") or "").strip()
    namespace = getattr(args, "namespace", "") or (cfg.get("PINECONE_NAMESPACE") or "maria-helena").strip()
    if not index_name:
        raise ValueError("Defina PINECONE_INDEX_NAME no .env ou --index-name")

    pc = Pinecone(api_key=pinecone_api_key)

    if args.command == "index":
        docs = load_documents(args.data_dir)
        print(f"Documentos carregados: {len(docs)}")
        vectors = embed_documents(args.embedding_model, docs)
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

    if args.command == "query":
        question = (args.question or args.text or "").strip()
        if not question:
            raise ValueError("Informe a pergunta com --question ou --text")
        response = run_query(
            pc=pc,
            index_name=index_name,
            namespace=namespace,
            model_name=args.embedding_model,
            question=question,
            top_k=args.top_k,
        )
        print("✅ Resultado da consulta RAG:")
        print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
        return


if __name__ == "__main__":
    main()
