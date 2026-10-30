"""Opt-in host timing wrappers. No admission, retries, prompts or result edits."""


class MeasuredHandler:
    def __init__(self, handler, timing):
        self.handler, self.timing = handler, timing

    def __getattr__(self, name):
        return getattr(self.handler, name)

    def handle(self, *args, **kwargs):
        return self.timing.call('wsc.recovery_callback', self.handler.handle, *args, **kwargs)


class MeasuredSession:
    """Wrap once before constructing the receiver; preserve live underlying state."""
    def __init__(self, session, timing):
        self.session, self.timing = session, timing

    def __getattr__(self, name):
        return getattr(self.session, name)

    def __setattr__(self, name, value):
        if name in {'session', 'timing'}:
            object.__setattr__(self, name, value)
        else:
            setattr(self.session, name, value)

    def __delattr__(self, name):
        if name in {'session', 'timing'}:
            raise AttributeError(name)
        delattr(self.session, name)

    def execute_stage(self, request, destination, limits, record_phase, *, compact=False,
                      output_schema=None, tool_handler=None):
        if tool_handler is not None:
            tool_handler = MeasuredHandler(tool_handler, self.timing)
        return self.timing.call('native.compaction' if compact else 'native.task_stage',
            self.session.execute_stage, request, destination, limits, record_phase,
            compact=compact, output_schema=output_schema, tool_handler=tool_handler)

    def close(self):
        return self.timing.call('host.session_close', self.session.close)


def measured_provider(provider, timing):
    """Pass this callback to the existing provider gate; auth stays in provider."""
    def dispatch(raw):
        return timing.call('provider.http', provider, raw)
    return dispatch


def open_measured_session(factory, timing, *args, **kwargs):
    return MeasuredSession(timing.call('host.session_open', factory, *args, **kwargs), timing)
