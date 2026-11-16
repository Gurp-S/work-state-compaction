"""Local CSM CLI. Reads and writes one memory namespace, prints JSON only."""
import argparse
import json
from pathlib import Path
import sys

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
    q.add_argument("--context", action="append", default=[])
    q.add_argument("--topic", action="append", default=[])
    q.add_argument("--history", action="store_true")
    q.add_argument("--valid-at")
    q.add_argument("--node")
    q.add_argument("--expand", type=int, default=0)
    q.add_argument("--dependencies", action="store_true")
    q.add_argument("--no-pending", action="store_true")
    q.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show")
    show.add_argument("--memory", required=True)
    show.add_argument("--history", action="store_true")
    listing = sub.add_parser("pending")
    listing.add_argument("--limit", type=int, default=100)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--pending", required=True)
    resolve.add_argument("--context", action="append", default=[])
    resolve.add_argument("--operation", choices=("create", "update"))
    enrich = sub.add_parser("enrich")
    enrich.add_argument("--memory", required=True)
    enrich.add_argument("--topic", action="append", required=True)
    sub.add_parser("rebuild")
    sub.add_parser("status")
    rekey = sub.add_parser("rekey")
    rekey.add_argument("--memory", required=True)
    rekey.add_argument("--context", action="append", required=True)
    rekey.add_argument("--evidence", action="append", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--target", required=True)
    merge.add_argument("--source", required=True)
    merge.add_argument("--evidence", action="append", required=True)
    converge = merge.add_mutually_exclusive_group()
    converge.add_argument("--context", action="append", default=None)
    converge.add_argument("--no-context", action="store_true")
    link = sub.add_parser("link")
    link.add_argument("--kind", required=True)
    link.add_argument("--subject", required=True)
    link.add_argument("--object", required=True)
    link.add_argument("--context", action="append", default=[])
    link.add_argument("--evidence", action="append", required=True)
    link.add_argument("--confirm", action="store_true")
    rels = sub.add_parser("relations")
    rels.add_argument("--ref", required=True)
    rels.add_argument("--all", action="store_true")
    impact = sub.add_parser("impact")
    impact.add_argument("--memory", required=True)
    node = sub.add_parser("node")
    node.add_argument("--name", required=True)
    node.add_argument("--parent")
    node.add_argument("--type", default="organization", choices=("entity", "organization"))
    node.add_argument("--entity-anchor")
    node.add_argument("--scope")
    node.add_argument("--status", choices=("candidate", "active"))
    node.add_argument("--evidence", action="append", default=[])
    mount = sub.add_parser("mount")
    mount.add_argument("--memory", required=True)
    mount.add_argument("--node")
    promote = sub.add_parser("promote")
    promote.add_argument("--node", required=True)
    promote.add_argument("--threshold", type=int, default=2)
    sub.add_parser("tree")
    paths = sub.add_parser("paths")
    paths.add_argument("--memory", required=True)
    sub.add_parser("watermark")
    since = sub.add_parser("since")
    since.add_argument("--source-type", required=True)
    since.add_argument("--limit", type=int, default=100)
    sub.add_parser("proposals")
    apply = sub.add_parser("apply")
    apply.add_argument("--pending", required=True)
    reinterpret = sub.add_parser("reinterpret")
    reinterpret.add_argument("--memory", required=True)
    reinterpret.add_argument("--context", action="append", required=True)
    reinterpret.add_argument("--evidence", action="append", required=True)
    reinterpret.add_argument("--reason", required=True)
    group = sub.add_parser("remember-group")
    group.add_argument("--group", required=True)
    group.add_argument("--input", required=True)
    sub.add_parser("evolve")
    context = sub.add_parser("context")
    context.add_argument("--entity")
    context.add_argument("--slot")
    context.add_argument("--topic", action="append", default=[])
    context.add_argument("--max-chars", type=int, default=4000)
    context.add_argument("--max-items", type=int, default=20)
    scope = sub.add_parser("scope")
    scope.add_argument("--left", required=True)
    scope.add_argument("--right", required=True)
    return p


def run(args, core: CSM):
    if args.command == "ingest":
        return core.ingest(events_from_json(load(args.input)))
    if args.command == "remember":
        return core.remember(candidates_from_json(load(args.input)), producer=args.producer)
    if args.command == "query":
        return core.query(MemoryQuery(entity=args.entity, slot=args.slot,
                                      contexts=tuple(args.context), topics=tuple(args.topic),
                                      node_id=args.node, valid_at=args.valid_at,
                                      expand=args.expand,
                                      include_dependencies=args.dependencies,
                                      include_history=args.history,
                                      include_pending=not args.no_pending,
                                      limit=args.limit))
    if args.command == "show":
        return core.memory(args.memory, history=args.history)
    if args.command == "pending":
        return core.pending(limit=args.limit)
    if args.command == "resolve":
        return core.resolve_pending(args.pending, contexts=tuple(args.context),
                                    operation=args.operation)
    if args.command == "enrich":
        return core.enrich(args.memory, topics=tuple(args.topic))
    if args.command == "rebuild":
        return core.rebuild()
    if args.command == "rekey":
        return core.rekey(args.memory, contexts=tuple(args.context),
                          evidence=tuple(args.evidence))
    if args.command == "merge":
        contexts = () if args.no_context else (tuple(args.context) if args.context else None)
        return core.merge(args.target, args.source, evidence=tuple(args.evidence),
                          contexts=contexts)
    if args.command == "link":
        return core.link(kind=args.kind, subject=args.subject, object=args.object,
                         contexts=tuple(args.context), evidence=tuple(args.evidence),
                         confirmed=args.confirm)
    if args.command == "relations":
        return core.relations(args.ref, confirmed_only=not args.all)
    if args.command == "impact":
        return core.impact(args.memory)
    if args.command == "node":
        return core.create_node(name=args.name, node_type=args.type, parent_id=args.parent,
                                entity_anchor=args.entity_anchor,
                                scope_description=args.scope, status=args.status,
                                evidence=tuple(args.evidence))
    if args.command == "mount":
        return core.mount(args.memory, node_id=args.node)
    if args.command == "promote":
        return core.promote(args.node, threshold=args.threshold)
    if args.command == "tree":
        return core.tree()
    if args.command == "paths":
        return core.paths(args.memory)
    if args.command == "watermark":
        return core.watermark()
    if args.command == "since":
        return core.since(args.source_type, limit=args.limit)
    if args.command == "proposals":
        return core.propose_identity_operations()
    if args.command == "apply":
        return core.apply_proposal(args.pending)
    if args.command == "reinterpret":
        return core.reinterpret(args.memory, contexts=tuple(args.context),
                                evidence=tuple(args.evidence), reason=args.reason)
    if args.command == "remember-group":
        return core.remember_group(candidates_from_json(load(args.input)),
                                   group_id=args.group)
    if args.command == "evolve":
        return core.evolve()
    if args.command == "context":
        return core.assemble(MemoryQuery(entity=args.entity, slot=args.slot,
                                         topics=tuple(args.topic)),
                             max_chars=args.max_chars, max_items=args.max_items)
    if args.command == "scope":
        return core.scope_intersection(args.left, args.right)
    return core.status()


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    core = CSM(CsmStore(args.db, namespace=args.namespace))
    try:
        result = run(args, core)
    except (CSMError, WSCError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
