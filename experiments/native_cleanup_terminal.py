"""Opt-in lifecycle observation; completion never cancels a budget failure."""
from copy import deepcopy


def observe_final(outcome, params, *, thread_id, turn_id):
    if params.get('threadId') != thread_id or params.get('turnId') != turn_id:
        return False
    item=params.get('item',{})
    if item.get('type') != 'agentMessage' or item.get('phase') != 'final_answer':
        return False
    if not isinstance(item.get('id'),str) or not item['id']:
        return False
    finals=outcome.setdefault('finals',[])
    if not any(saved.get('id') == item['id'] for saved in finals):
        finals.append(deepcopy(item))
    return True


def observe(outcome, params, *, thread_id, turn_id):
    turn=params.get('turn',{})
    if params.get('threadId')!=thread_id or turn.get('id')!=turn_id:
        return False
    status=turn.get('status')
    if status not in ('completed','interrupted','failed'):
        return False
    outcome['completed']=status=='completed'
    outcome['native_terminal_status']=status
    if status!='completed' and outcome.get('failure') is None:
        outcome['failure']='native_turn_'+status
    return True
