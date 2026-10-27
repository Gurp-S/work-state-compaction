"""Closed-pair admission: task failure is data; unavailable service stops dispatch."""


def decide(results, phases, ledger):
    reasons=[]
    codes=[]
    for arm,result in results.items():
        if result.get('cleanup',{}).get('empty_confirmed') is not True:
            reasons.append('process_cleanup_unconfirmed:'+arm)
        if result.get('inference_started') is not True:
            reasons.append('preflight_not_executed:'+arm)
        if result.get('error') or result.get('accounting_mismatch') or result.get('pins_unchanged') is not True:
            reasons.append('infrastructure_or_source_failure:'+arm)
        phase=phases.get(arm,{})
        notices=phase.get('retry_notices',[])
        if notices or 'application_native_provider_error' in str(result.get('failure','')):
            reasons.append('provider_unavailable:'+arm)
        for notice in notices:
            info=notice.get('error',{}).get('codexErrorInfo')
            if isinstance(info,str):codes.append(info)
            elif isinstance(info,dict):codes.extend(info)
    if ledger.get('inflight'):
        reasons.append('inflight_reservation')
    if ledger.get('study',{}).get('uncertain') is not False:
        reasons.append('usage_unknown')
    return dict(admitted=not reasons,reasons=sorted(set(reasons)),provider_codes=sorted(set(codes)))
