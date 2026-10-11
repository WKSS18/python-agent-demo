import json
import unicodedata
from pathlib import Path

from fastembed import TextEmbedding
from pymilvus import MilvusClient
from pypdf import PdfReader
from unstructured.chunking.title import chunk_by_title
from unstructured.partition.text import partition_text


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
MILVUS_URI = "http://122.51.39.141:19530"
COLLECTION_NAME = "resume_unstructured_chunks"
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"


def element_record(element: object) -> dict[str, object]:
    metadata = element.metadata.to_dict()
    return {
        "type": element.category,
        "text": str(element),
        "page_number": metadata.get("page_number"),
        "filename": metadata.get("filename"),
    }


def main() -> None:
    pdf_files = sorted(DATA_DIR.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in {DATA_DIR}")

    pdf_path = pdf_files[0]
    OUTPUT_DIR.mkdir(exist_ok=True)

    elements = []
    reader = PdfReader(pdf_path)
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = unicodedata.normalize("NFKC", page.extract_text() or "")
        page_elements = partition_text(text=page_text)
        for element in page_elements:
            element.metadata.page_number = page_number
            element.metadata.filename = pdf_path.name
        elements.extend(page_elements)

    chunks = chunk_by_title(
        elements,
        max_characters=800,
        new_after_n_chars=600,
        combine_text_under_n_chars=120,
        multipage_sections=False,
    )

    element_records = [element_record(element) for element in elements]
    chunk_records = [
        {
            "chunk_id": index,
            "type": chunk.category,
            "text": str(chunk),
            "page_number": chunk.metadata.page_number,
            "filename": chunk.metadata.filename,
            "character_count": len(str(chunk)),
        }
        for index, chunk in enumerate(chunks, start=1)
    ]

    embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL)
    vectors = [vector.tolist() for vector in embedding_model.embed([str(chunk) for chunk in chunks])]
    if not vectors:
        raise RuntimeError("No chunks were generated from the PDF")

    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(collection_name=COLLECTION_NAME):
        client.drop_collection(collection_name=COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        dimension=len(vectors[0]),
        metric_type="COSINE",
    )

    entities = [
        {
            "id": record["chunk_id"],
            "vector": vector,
            "text": record["text"],
            "source": record["filename"],
            "page_number": record["page_number"] or 0,
            "chunk_index": record["chunk_id"],
            "character_count": record["character_count"],
        }
        for record, vector in zip(chunk_records, vectors, strict=True)
    ]
    insert_result = client.insert(collection_name=COLLECTION_NAME, data=entities)

    json_path = OUTPUT_DIR / "unstructured_chunks.json"
    json_path.write_text(
        json.dumps(
            {
                "source": pdf_path.name,
                "element_count": len(element_records),
                "chunk_count": len(chunk_records),
                "elements": element_records,
                "chunks": chunk_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    preview_path = OUTPUT_DIR / "unstructured_preview.md"
    preview_lines = [
        f"# Unstructured 切片预览：{pdf_path.name}",
        "",
        f"- 原始元素数：{len(element_records)}",
        f"- 最终切片数：{len(chunk_records)}",
        "",
    ]
    for chunk in chunk_records:
        preview_lines.extend(
            [
                f"## Chunk {chunk['chunk_id']} | 第 {chunk['page_number']} 页 | {chunk['character_count']} 字符",
                "",
                chunk["text"],
                "",
                "---",
                "",
            ]
        )
    preview_path.write_text("\n".join(preview_lines), encoding="utf-8")

    print(f"Source: {pdf_path}")
    print(f"Elements: {len(element_records)}")
    print(f"Chunks: {len(chunk_records)}")
    print(f"JSON: {json_path}")
    print(f"Preview: {preview_path}")
    print(f"Milvus: {MILVUS_URI}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Inserted: {insert_result['insert_count']}")


if __name__ == "__main__":
    main()
