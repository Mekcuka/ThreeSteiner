"""FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from network_planner import __version__
from network_planner.api.routes import router

app = FastAPI(
    title="Steiner Network Planner",
    version=__version__,
    description="Euclidean Steiner tree over terminals (start/end roles).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
