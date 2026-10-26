"""Mechanical control declarations shared by invalidation and view retention."""


def is_control_source(row):
    # Kind labels alone do not declare control; roles and the explicit flag do.
    # Event ingestion validates both fields before this rule is used.
    return row.get("control") is True or row.get("role") in {"system", "developer", "user"}
