"""Private named acceptance for the strict JSONL continuation study."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


class StrictJSONLTests(unittest.TestCase):
    def parser(self):
        try:
            from wsc.strict_jsonl import parse_strict_rollout
        except ImportError:
            self.fail('strict_jsonl_entry_missing')
        return parse_strict_rollout

    def test_unicode_physical_lines_and_raw_identity(self):
        rows=[{'type':'response_item','payload':{'text':'甲\u2028乙'}},{'type':'event_msg','payload':{'n':10**90}}]
        raw=b'\n'+json.dumps(rows[0],ensure_ascii=False).encode()+b'\n \n'+json.dumps(rows[1]).encode()+b'\n'
        value=self.parser()(raw)
        self.assertEqual(rows,value.rows);self.assertEqual([2,4],value.line_numbers)
        self.assertEqual(sha256(raw).hexdigest(),value.metadata['sha256'])
        self.assertEqual(len(raw),value.metadata['byte_length']);self.assertTrue(value.metadata['parse_complete'])

    def test_duplicate_keys_at_all_object_depths_are_rejected(self):
        parse=self.parser()
        bodies=[b'{"type":"a","type":"a"}',b'{"type":"a","payload":{"x":1,"x":2}}',
                b'{"type":"a","payload":[{"secret-key":1,"secret-key":2}]}',
                b'{"type":"a","payload":{"x":1,"\\u0078":2}}']
        for body in bodies:
            for end in (b'',b'\n'):
                with self.subTest(body=body,end=end), self.assertRaisesRegex(ValueError,r'^rollout_duplicate_key:line=2$'):
                    parse(b'\n'+body+end)

    def test_strings_are_not_recursively_decoded(self):
        row={'type':'reasoning','payload':{'encrypted_content':'{"x":NaN,"x":Infinity}',
                                        'text':'-Infinity 1e9999'}}
        raw=json.dumps(row).encode()
        value=self.parser()(raw)
        self.assertEqual([row],value.rows);self.assertTrue(value.metadata['parse_complete'])

    def test_partial_tail_and_missing_file_observations_remain_distinct(self):
        parse=self.parser();good=b'{"type":"event_msg"}\n'
        for tail in (b'{"type":',b'\xff'):
            value=parse(good+tail)
            self.assertEqual([{'type':'event_msg'}],value.rows)
            self.assertEqual('incomplete_or_invalid',value.metadata['tail_status'])
            self.assertFalse(value.metadata['parse_complete'])
            self.assertEqual(sha256(good+tail).hexdigest(),value.metadata['sha256'])
        value=parse(b'',exists=False)
        self.assertFalse(value.metadata['exists']);self.assertFalse(value.metadata['parse_complete'])

    def test_invalid_interior_and_record_shapes_are_rejected(self):
        parse=self.parser()
        for raw in (b'\xff\n{"type":"ok"}\n',b'not-json\n{"type":"ok"}\n',b'[]',b'{"type":1}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse(raw)

    def test_nonfinite_values_and_overflow_numbers_are_rejected(self):
        parse=self.parser()
        for number in (b'NaN',b'Infinity',b'-Infinity',b'1e9999',b'-1e9999'):
            with self.subTest(number=number),self.assertRaisesRegex(ValueError,r'^rollout_nonfinite_number:line=2$'):
                parse(b'\n{"type":"event_msg","payload":[{"n":'+number+b'}]}\n')

    def test_complete_unterminated_nonfinite_tail_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,r'^rollout_nonfinite_number:line=1$'):
            self.parser()(b'{"type":"event_msg","payload":NaN}')

    def test_finite_numbers_keep_integer_precision_and_float_values(self):
        row={'type':'event_msg','payload':[10**120,1.25,0,-42,True,None,'NaN']}
        value=self.parser()(json.dumps(row).encode())
        self.assertEqual([row],value.rows)
        self.assertIs(type(value.rows[0]['payload'][0]),int)

    def test_line_budget_is_bytes_and_includes_cr_but_excludes_lf(self):
        parse=self.parser();raw='{"type":"事件"}\r'.encode()
        self.assertTrue(parse(raw+b'\n',max_line_bytes=len(raw)).metadata['parse_complete'])
        with self.assertRaisesRegex(ValueError,r'^rollout_line_budget_exhausted:line=2$'):
            parse(b'\n'+raw+b'\n',max_line_bytes=len(raw)-1)
        with self.assertRaisesRegex(ValueError,r'^rollout_line_budget_exhausted:line=1$'):
            parse(b' '*8+b'\n',max_line_bytes=7)

    def test_oversized_invalid_line_is_rejected_before_decoding(self):
        with self.assertRaisesRegex(ValueError,r'^rollout_line_budget_exhausted:line=1$'):
            self.parser()(b'\xff'*8,max_line_bytes=7)

    def test_default_unlimited_and_invalid_budget_values(self):
        parse=self.parser();raw=b'{"type":"ok"}\n'
        self.assertEqual(parse(raw).rows,parse(raw,max_line_bytes=None).rows)
        for limit in (True,False,0,-1,1.5,'8'):
            with self.subTest(limit=limit),self.assertRaisesRegex(ValueError,r'^rollout_line_budget_invalid$'):
                parse(raw,max_line_bytes=limit)


if __name__=='__main__':unittest.main()
