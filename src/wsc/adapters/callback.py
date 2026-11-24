"""An explicit integration seam owned by the host runtime."""
from ..contracts import require


class CallbackHost:
    """commit performs capacity, permission, binding and idle checks atomically
    with installation; it persists the receipt and is idempotent by operation ID.
    No receipt is invented here. An adapter without these host guarantees cannot
    use installation.
    """
    def __init__(self, *, commit):
        require(callable(commit), "host_callbacks_missing")
        self._commit = commit

    def install(self, package):
        return self._commit(package)