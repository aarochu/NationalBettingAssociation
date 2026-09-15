"""Shared Elasticsearch client helper. Every ingest script imports from here
so credentials are configured in exactly one place.
"""
import os

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()


def get_client() -> Elasticsearch:
    endpoint = os.environ.get("ELASTIC_ENDPOINT")
    api_key = os.environ.get("ELASTIC_API_KEY")

    if not endpoint or not api_key:
        raise RuntimeError(
            "ELASTIC_ENDPOINT / ELASTIC_API_KEY not set. Copy .env.example to "
            ".env and fill in your Elastic Cloud Serverless connection details."
        )

    return Elasticsearch(endpoint, api_key=api_key)
