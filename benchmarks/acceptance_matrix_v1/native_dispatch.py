"""One receipt-bound stage through existing native sessions. No CLI dispatch.

The caller owns experiment admission and a factory which opens/imports the
sealed material and attaches matrix_import_proof. This bridge never retries.
"""
from hashlib import sha256
from pathlib import Path


def execute_bound_stage(ledger, run_id, phase_id, limits, open_session, request, destination, *, output_schema=None):
    binding = ledger.runs[run_id]['spec']['binding']
    required = {'workspace', 'model', 'effort', 'history_sha256', 'request_sha256'}
    if not required <= set(binding) or sha256(request.encode('utf-8')).hexdigest() != binding['request_sha256']:
        raise ValueError('matrix_native_request_binding_invalid')
    grant = ledger.reserve(run_id, phase_id, limits)
    ticket, session, observed, outcome, error = grant['ticket'], None, [], None, None
    try:
        session = open_session()
        actual = session.registration
        if (actual.get('model') != binding['model'] or actual.get('effort') != binding['effort']
                or Path(actual['workspace']).resolve() != Path(binding['workspace']).resolve()
                or getattr(session, 'matrix_import_proof', {}).get('imported_items_sha256') != binding['history_sha256']):
            raise ValueError('matrix_native_session_or_history_binding_changed')
        outcome = session.execute_stage(request, destination, ledger.remaining(ticket), observed.append,
                                        output_schema=output_schema)
        if len(observed) != 1 or observed[0] != outcome:
            raise ValueError('matrix_native_phase_receipt_not_unique')
    except BaseException as exc:
        error = exc
    finally:
        try:
            if session is not None:
                # Close the private process tree before pipe handles, including
                # timeout/error paths; cleanup is inside the charged interval.
                session.server.owner.close()
                session.close()
        except BaseException as exc:
            if error is None:
                error = exc
        if len(observed) == 1:
            phase = dict(observed[0])
            if error is not None:
                phase['failure'] = str(error)
        else:
            # Ambiguous or absent receipts remain unknown, never free success.
            entries = [entry for value in observed if isinstance(value, dict)
                       for entry in value.get('receipts', {}).get('response_receipts', [])]
            phase = dict(receipts=dict(response_receipts=entries), usage_complete=False,
                         failure=str(error or 'matrix_native_phase_receipt_missing'))
        settled = ledger.settle(ticket, phase)
    if error is not None:
        raise error
    return dict(outcome=outcome, settlement=settled, ticket=ticket)
