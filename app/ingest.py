"""Build the index: download PDFs → chunk → embed → write to Qdrant.

docker compose run --rm api python -m app.ingest
"""

import argparse
import time

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from pypdf import PdfReader

from app.config import settings
from app.corpus import DOCS, download
from app.parsing import make_splitter, parse_document
from app.vectorstore import get_embeddings


def load_documents() -> list[Document]:
    splitter = make_splitter(settings.chunk_size, settings.chunk_overlap)
    documents = []
    for spec in DOCS:
        reader = PdfReader(settings.data_dir / spec.filename)
        pages = [page.extract_text() or "" for page in reader.pages]
        chunks = parse_document(pages, spec, splitter)
        print(f"{spec.title}：{len(reader.pages)} 頁 → {len(chunks)} 個 chunk")
        documents.extend(chunks)
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="重新下載 PDF（官方更新版本時使用）")
    args = parser.parse_args()

    download(settings.data_dir, force=args.refresh)
    documents = load_documents()

    print(f"以 {settings.embedding_model} 計算 embedding（首次執行會下載模型）…")
    started = time.perf_counter()
    # force_recreate rebuilds the whole collection each run, so re-running never duplicates data.
    QdrantVectorStore.from_documents(
        documents,
        get_embeddings(),
        url=settings.qdrant_url,
        collection_name=settings.collection,
        force_recreate=True,
    )
    print(f"完成：{len(documents)} 個 chunk 寫入 {settings.collection}（{time.perf_counter() - started:.0f} 秒）")


if __name__ == "__main__":
    main()
