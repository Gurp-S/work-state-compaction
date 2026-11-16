"""Cache identity follows authoritative content, never aggregate row counters."""
from ..contracts import digest


def database_key(db) -> tuple:
    row = next(row for row in db.execute("PRAGMA database_list") if row["name"] == "main")
    binding = db.execute("SELECT value FROM meta WHERE key = 'binding'").fetchone()
    return row["file"], None if binding is None else binding[0]


def embedder_key(embedder) -> dict:
    # Read configuration, not properties such as FastEmbedder.model (which loads a model).
    configuration = vars(embedder)
    return {"type": type(embedder).__module__ + "." + type(embedder).__qualname__,
            "configuration": {name: configuration[name] for name in
                              ("dim", "ngrams", "model", "model_name", "url")
                              if name in configuration}}


def content_signature(rows, embedder) -> str:
    return digest({"rows": rows, "embedder": embedder_key(embedder)})
