from pymilvus import MilvusClient


MILVUS_URI = "http://122.51.39.141:19530"


def main() -> None:
    client = MilvusClient(uri=MILVUS_URI)
    print(f"Connected to Milvus: {MILVUS_URI}")
    print(f"Databases: {client.list_databases()}")
    print(f"Collections: {client.list_collections()}")


if __name__ == "__main__":
    main()
