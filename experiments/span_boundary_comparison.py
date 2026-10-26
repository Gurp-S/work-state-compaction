"""Audit source equivalence independently of each arm's span partitions."""
from copy import deepcopy
from native_evidence import digest, read


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify_contrast(requests, schemas):
    normalized, counts, source_indexes = {}, {}, {}
    for mode in ("fixed", "word"):
        value = deepcopy(requests[mode])
        material = value["material"]
        counts[mode] = sum(len(event["spans"]) for event in material["events"])
        for event in material["events"]:
            spans = event.pop("spans")
            text = "".join(span["text"] for span in spans)
            require(event["public_text_characters"] in (None, len(text)), "span_contrast_character_loss")
            previous_end = 0
            for span in spans:
                alias, start, end, _ = span["ref"].split(":")
                start, end = int(start), int(end)
                require(alias == event["id"] and start == previous_end and
                        end - start == len(span["text"]) and 0 < end-start <= 1024,
                        "span_contrast_partition_invalid")
                previous_end = end
            event["text"] = text
        for entry in material["source_catalog"]:
            entry.pop("span_file")
            entry.pop("span_file_sha256")
        archive = material.pop("archive")
        material["archive"] = {k: v for k, v in archive.items()
                               if k not in {"catalog", "catalog_sha256", "source_index"}}
        index = read(archive["source_index"])
        # Paths vary because the span files differ; exact source hashes do not.
        source_indexes[mode] = {key: {k: v for k, v in locator.items()
            if k not in {"file_path", "readable_path"}} for key, locator in index.items()}
        normalized[mode] = value
    require(normalized["fixed"] == normalized["word"], "span_contrast_nonpartition_request_difference")
    require(source_indexes["fixed"] == source_indexes["word"], "span_contrast_source_archive_difference")
    normalized_schemas = deepcopy(schemas)
    for schema in normalized_schemas.values():
        schema["properties"]["span_refs"]["items"].pop("enum")
    require(normalized_schemas["fixed"] == normalized_schemas["word"], "span_contrast_schema_structure_difference")
    return {"same_original_text_order_and_metadata": True, "same_source_archive_hashes": True,
            "same_schema_except_reference_values": True, "normalized_request_sha256": digest(normalized["fixed"]),
            "inline_span_counts": counts, "changed": "span partitions, references, and matching cold span archive paths"}
