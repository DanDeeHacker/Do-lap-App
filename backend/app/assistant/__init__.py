"""Physio AI Assistant — the runner-facing chat and its knowledge base.

knowledge.py  evidence cards, literature summaries, app guide and full texts:
              storage sync, PDF ingestion, hybrid search (BM25 + embeddings)
gate.py       fixed safety replies and scope checks that run before any model
selector.py   intent, topics and the runner-data slices a question needs
facts.py      the runner facts packet for the chat (engine output only)
validate.py   checks a model answer against facts, sources and the engine
service.py    the pipeline: gate → selector → facts + retrieval → model → validator
"""
