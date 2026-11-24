from wsc.csm.cem.producer_binding import outside_pending_scope


def test_partial_overlap_cannot_bypass_pending_binding():
    source = {'user': '明天带桂花味的礼物，借款月底还。'}
    pending = [{'event_id': 'chat/1', 'path': ['user'], 'quote': '明天带桂花味的礼物'}]

    def claim(quote):
        return {'citations': [{'turn': 1, 'field': 'user', 'quote': quote}]}

    overlapping = claim('桂花味的礼物，借款')
    independent = claim('借款月底还')
    assert outside_pending_scope([overlapping, independent], pending, sources={1: source}) == [independent]
