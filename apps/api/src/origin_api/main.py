"""ASGI entry point: `uvicorn origin_api.main:app`."""

from origin_api.app import create_app

app = create_app()
