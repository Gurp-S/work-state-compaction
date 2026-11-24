"""Local CSM CLI. Reads and writes one memory namespace, prints JSON only."""
import argparse
import json
from pathlib import Path

from ..contracts import WSCError
from .contracts import CSMError, Event, MemoryCandidate, MemoryQuery
from .service import CSM
from .store import CsmStore


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def events_from_json(document) -> list[Event]:
    items = document["events"] if isinstance(document, dict) else document
    return [Event(id=item["id"], source_type=item.get("source_type", "unknown"),
                  payload=item.get("payload"), source_ref=item.get("source_ref"),
                  observed_at=item.get("observed_at"), metadata=item.get("metadata"))
            for item in items]


def candidates_from_json(document) -> list[MemoryCandidate]:
    items = document["candidates"] if isinstance(document, dict) else document
    return [MemoryCandidate(**item) for item in items]


def parser():
    p = argparse.ArgumentParser(prog="csm", description="CSM stateful semantic memory")
    p.add_argument("--db", required=True)
    p.add_argument("--namespace", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--input", required=True)
    remember = sub.add_parser("remember")
    remember.add_argument("--input", required=True)
    remember.add_argument("--producer", default="model")
    q = sub.add_parser("query")
    q.add_argument("--entity")
    q.add_argument("--slot")
    q.add_argument("--topic", action="append", default=[])
    q.add_argument("--scope")
    q.add_argument("--scope-chain", action="store_true")
    q.add_argument("--history", action="store_true")
    q.add_argument("--valid-at")
    q.add_argument("--at-commit")
    q.add_argument("--text")
    q.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("search")
    s.add_argument("--text", required=True)
    s.add_argument("--until")
    s.add_argument("--entity")
    s.add_argument("--scope")
    s.add_argument("--scope-chain", action="store_true")
    s.add_argument("--at-commit")
    s.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show")
    show.add_argument("--memory", required=True)
    show.add_argument("--history", action="store_true")
    history = sub.add_parser("timeline")
    history.add_argument("--memory", required=True)
    history.add_argument("--start")
    history.add_argument("--end")
    enrich = sub.add_parser("enrich")
    enrich.add_argument("--memory", required=True)
    enrich.add_argument("--topic", action="append", required=True)
    props = sub.add_parser("properties")
    props.add_argument("--entity", required=True)
    alias = sub.add_parser("alias")
    alias.add_argument("--property", required=True)
    alias.add_argument("--name", required=True)
    context = sub.add_parser("context")
    context.add_argument("--entity")
    context.add_argument("--slot")
    context.add_argument("--scope")
    context.add_argument("--scope-chain", action="store_true")
    context.add_argument("--valid-at")
    context.add_argument("--at-commit")
    context.add_argument("--text")
    context.add_argument("--max-chars", type=int, default=4000)
    context.add_argument("--max-items", type=int, default=20)
    sub.add_parser("consolidate")
    sub.add_parser("rebuild")
    sub.add_parser("status")
    return p


def run(args, core: CSM):
    if args.command == "ingest":
        return core.ingest(events_from_json(load(args.input)))
    if args.command == "remember":
        return core.remember(candidates_from_json(load(args.input)), producer=args.producer)
    if args.command == "query":
        return core.query(MemoryQuery(entity=args.entity, slot=args.slot,
                                      topics=tuple(args.topic), scope=args.scope,
                                      scope_chain=args.scope_chain, valid_at=args.valid_at,
                                      at_commit=args.at_commit, include_history=args.history,
                                      text=args.text, limit=args.limit))
    if args.command == "search":
        return core.search(args.text, limit=args.limit, entity=args.entity,
                           scope=args.scope, scope_chain=args.scope_chain,
                           at_commit=args.at_commit,
                           window=(None, args.until) if args.until else None)
    if args.command == "show":
        return core.memory(args.memory, history=args.history)
    if args.command == "timeline":
        return core.timeline(args.memory, start=args.start, end=args.end)
    if args.command == "enrich":
        return core.enrich(args.memory, topics=tuple(args.topic))
    if args.command == "properties":
        return core.properties(args.entity)
    if args.command == "alias":
        return core.alias_property(args.property, args.name)
    if args.command == "context":
        packet = (core.search(args.text, limit=args.max_items, scope=args.scope,
                              scope_chain=args.scope_chain) if args.text
                  else core.query(MemoryQuery(entity=args.entity, slot=args.slot,
                                              scope=args.scope, scope_chain=args.scope_chain,
                                              valid_at=args.valid_at, at_commit=args.at_commit,
                                              limit=args.max_items)))
        return core.context(packet, max_chars=args.max_chars, max_items=args.max_items)
    if args.command == "consolidate":
        return core.consolidate()
    if args.command == "rebuild":
        return core.rebuild()
    if args.command == "status":
        return core.status()
    raise ValueError(f"unknown command: {args.command}")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        core = CSM(CsmStore(args.db, namespace=args.namespace))
        print(json.dumps(run(args, core), ensure_ascii=False, indent=2))
        return 0
    except (CSMError, WSCError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
