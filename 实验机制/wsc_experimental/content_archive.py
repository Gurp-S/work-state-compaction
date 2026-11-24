"""Opt-in immutable cold objects: atomic no-replace byte publication."""
from pathlib import Path
import os
import tempfile

from wsc.contracts import require


def publish_object(path, payload):
    """Expose only complete bytes; a competing writer can never replace an object."""
    path = Path(path)
    require(not path.is_symlink(), "evidence_path_symlink")
    if path.exists():
        require(path.read_bytes() == payload, "evidence_object_conflict")
        return
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Both names are in the same filesystem. link is an atomic no-replace
            # publication, unlike rename which overwrites on some platforms.
            os.link(temporary, path)
        except FileExistsError:
            require(not path.is_symlink(), "evidence_path_symlink")
            require(path.read_bytes() == payload, "evidence_object_conflict")
    finally:
        temporary.unlink(missing_ok=True)
