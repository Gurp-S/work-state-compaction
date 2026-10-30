"""Compatibility entrypoint; task preparation is shared."""
from prepare_matrix_tasks import main

if __name__ == '__main__':
    main(default_tasks=('T1', 'T3'))
