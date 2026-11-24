"""Opt-in publication of literal user observations with their historical scope."""
import json


def offer_user_observation_answer(question, retrieval, read_original):
    offered = {}
    accepted = set()
    for item in retrieval.state_items:
        for citation in item.get('citations', ()):
            turn, quote = citation['turn'], citation['quote']
            if (citation['field'] != 'user' or turn not in retrieval.used_turns
                    or not quote.strip() or len(quote) > 320 or (turn, quote) in accepted):
                continue
            source = read_original(turn)
            if quote not in source['user']:
                raise ValueError('observation_answer_quote_mismatch')
            accepted.add((turn, quote))
            offered[f's{len(offered)}'] = f"第{turn}轮用户原话（{source['time']}）：{quote}"
            if len(offered) == 12:
                break
        if len(offered) == 12:
            break
    return offered, json.dumps({'question': question, 'state_choices': offered,
                                'response_schema': {'state_refs': 'zero to four distinct keys from state_choices'}},
                               ensure_ascii=False)
