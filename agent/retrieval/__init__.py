"""Retrieval — one module per source, unified via search_all().

Topic-pack-driven: which sources run is read from the per-topic TOML.
Adding a new topic = adding a new TOML; adding a new source = adding a new
file and registering it. No source-specific logic in the universal core.
"""

from agent.retrieval.base import PaperHit
from agent.retrieval.pubmed import PubMedSource
from agent.retrieval.unified import available_sources, register, search_all

__all__ = [
    "PaperHit",
    "PubMedSource",
    "available_sources",
    "register",
    "search_all",
]
