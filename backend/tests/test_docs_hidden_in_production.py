"""Interactive API docs are served everywhere except production."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.docs import docs_urls


@pytest.mark.parametrize("environment", ["production", "Production", " PRODUCTION "])
def test_production_serves_no_docs_or_schema(environment):
    assert docs_urls(environment) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


@pytest.mark.parametrize("environment", [None, "", "development", "staging"])
def test_other_environments_keep_the_defaults(environment):
    assert docs_urls(environment) == {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


def test_fastapi_honours_the_production_settings():
    # The kwargs must be the ones FastAPI accepts; a wrong name would still
    # pass the two assertions above but serve the docs anyway.
    prod = TestClient(FastAPI(**docs_urls("production")))
    dev = TestClient(FastAPI(**docs_urls("development")))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert prod.get(path).status_code == 404, path
        assert dev.get(path).status_code == 200, path
