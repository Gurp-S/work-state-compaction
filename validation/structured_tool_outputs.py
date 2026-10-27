"""Bounded exact JSON-string transport unwrapping for offline audits only."""
import json
from blackbox_recovery_case import decoded_objects


def decoded_transport_objects(value):
    yield from decoded_objects(value)
    seen=set()
    def walk(node,depth=0):
        if depth>8:return
        if isinstance(node,dict):
            for child in node.values():yield from walk(child,depth+1)
        elif isinstance(node,list):
            for child in node:yield from walk(child,depth+1)
        elif isinstance(node,str) and len(node)<=2*1024*1024 and node not in seen:
            seen.add(node)
            try:parsed=json.loads(node)
            except (ValueError,RecursionError):return
            yield from decoded_objects(parsed)
            yield from walk(parsed,depth+1)
    yield from walk(value)
