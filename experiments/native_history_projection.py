"""Rebuild effective item values without modifying historical observations."""
from copy import deepcopy


def project_items(rows):
    items = []
    for row in rows:
        if row['type'] == 'response_item':
            items.append(row['payload'])
        elif row['type'] == 'compacted':
            items = list(row['payload']['replacement_history'])
    # Copy only surviving values; earlier windows may contain large discarded
    # tool outputs. The intermediate list never aliases a source-owned list.
    return deepcopy(items)
