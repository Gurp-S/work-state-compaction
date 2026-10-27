"""Project a closed diagnostic allocation onto its unchanged campaign parent."""
from copy import deepcopy
from native_campaign_envelope import qualification_envelope


def close(parent,snapshot,elapsed):
    # Diagnostic limits bound live dispatch. Campaign limits bound carry-forward.
    # Never overwrite the original recorded diagnostic ledger.
    outer=deepcopy(snapshot)
    outer['study']['limits']=deepcopy(parent['remaining_limits'])
    local=qualification_envelope(outer,[],elapsed)
    return dict(remaining_limits=local['remaining_limits'],local_closure=local,
        old_unknowns_preserved=True,historical_uncertainty=bool(parent.get('historical_uncertainty',True)),
        whole_campaign_usage_complete=False,old_evaluation_remains_retired=True,
        diagnostic_limits=deepcopy(snapshot['study']['limits']),
        accounting_scope='Projected campaign closure; diagnostic ledger is unchanged. Withheld allocation is not actual spend.')
