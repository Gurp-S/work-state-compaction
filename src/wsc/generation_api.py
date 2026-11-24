"""One construction and conformance path for generators.

Callers used to import three modules and pick an implementation by hand, so the
choice leaked into host code and every new generator had to re-establish the
same contract. `build_generator` is the single entry point; `check_generator`
asserts the port contract on the value a generator actually returns, which is
the part a type annotation alone cannot enforce at runtime.
"""
from .contracts import Generated, require

KINDS = ('json-command',)


def build_generator(kind, *args, **options):
    if kind == 'json-command':
        from .generation import JsonCommandGenerator
        return JsonCommandGenerator(*args, **options)
    raise ValueError('generation_kind_unknown')


def check_generator(generator, material):
    """Run one generation and require the declared port result."""
    result = generator(material)
    require(isinstance(result, Generated), 'generation_response_invalid')
    return result
