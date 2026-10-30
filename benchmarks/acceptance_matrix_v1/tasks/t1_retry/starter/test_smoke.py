import unittest
from retry_client import run_batch


class RetrySmoke(unittest.TestCase):
    def test_rate_limit_retries_with_one_based_attempt(self):
        seen = []
        def send(job, attempt):
            seen.append(attempt)
            return {'status': 429 if len(seen) == 1 else 200, 'value': 'accepted'}
        result = run_batch([{'tenant': 'a', 'id': 'one', 'method': 'GET', 'payload': {}}], send)
        self.assertEqual([1, 2], seen)
        self.assertEqual('ok', result[0]['state'])
        self.assertEqual(2, result[0]['attempts'])


if __name__ == '__main__':
    unittest.main()
