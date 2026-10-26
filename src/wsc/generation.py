"""Optional JSON command transport; no embedded model, prompt, retry or scheduler."""
from dataclasses import fields
from pathlib import Path
import json
import tempfile

from .contracts import Selection, Understanding, encode, require
from .excerpts import Excerpt
from .generation_boundary import decode_response, run_command


def string_list(value):
    require(isinstance(value, (list, tuple)) and all(isinstance(x, str) and x for x in value),
            "source_reference_list_invalid")
    return tuple(value)


def selection_from_json(value):
    require(isinstance(value, dict) and set(value) <= {f.name for f in fields(Selection)},
            "selection_shape_invalid")
    records = value.get("new_understandings", [])
    require(isinstance(records, list), "understanding_list_invalid")
    parsed = []
    for record in records:
        require(isinstance(record, dict) and set(record) <= {f.name for f in fields(Understanding)}
                and {"text", "kind"} <= set(record), "understanding_shape_invalid")
        record = {**record, "sources": string_list(record.get("sources", []))}
        parsed.append(Understanding(**record))
    clues = value.get("clues", [])
    require(isinstance(clues, list), "clue_list_invalid")
    excerpts = value.get("excerpts", [])
    require(isinstance(excerpts, list), "excerpt_list_invalid")
    for item in excerpts:
        require(isinstance(item, dict) and set(item) <= {f.name for f in fields(Excerpt)} and
                {"key", "source_id", "path", "start", "end", "text_sha256"} <= item.keys(),
                "excerpt_shape_invalid")
    return Selection(source_ids=string_list(value.get("source_ids", [])),
                     understanding_refs=string_list(value.get("understanding_refs", [])),
                     new_understandings=tuple(parsed), clues=tuple(clues),
                     excerpts=tuple(Excerpt(**item) for item in excerpts))


class JsonCommandGenerator:
    """stdin: public material JSON; stdout: {selection, usage}.

    argv is an explicitly supplied local program, run without a shell. Its model
    credentials, prompt and usage reporting remain the caller's responsibility.
    stdout/stderr are temporary files, never unbounded in-memory pipes or model
    error messages. All failures are recorded by WSC.generate as real attempts.
    """
    def __init__(self, argv, *, cwd=None, timeout=120, max_output_bytes=1048576):
        self.argv = string_list(argv)
        require(bool(self.argv) and timeout > 0 and max_output_bytes > 0, "generation_command_invalid")
        self.cwd, self.timeout, self.max_output_bytes = cwd, timeout, max_output_bytes

    def __call__(self, material):
        with tempfile.TemporaryDirectory(prefix="wsc-generation-") as temp:
            root = Path(temp)
            source, output, error = root / "input.json", root / "output.json", root / "error.txt"
            source.write_text(encode(material), encoding="utf-8")
            with source.open("rb") as stdin, output.open("wb") as stdout, error.open("wb") as stderr:
                outcome = run_command(self.argv, cwd=self.cwd, stdin=stdin, stdout=stdout,
                                         stderr=stderr, shell=False, timeout=self.timeout, check=False)
            require(outcome.returncode == 0, "generation_command_failed")
            require(output.stat().st_size <= self.max_output_bytes, "generation_output_budget_exhausted")
            value = json.loads(output.read_text(encoding="utf-8"))
            return decode_response(value, selection_from_json)
