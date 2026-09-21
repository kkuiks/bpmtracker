import io
import unittest
import zipfile

from acquire_groove_corpus import RemoteZip, select_rows


class Response(io.BytesIO):
    def __init__(self, data, status, headers):
        super().__init__(data)
        self.status, self.headers = status, headers


class RemoteArchiveTests(unittest.TestCase):
    def archive(self):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('unused.wav', b'other material'*5000)
            archive.writestr('chosen.wav', bytes(range(256))*100)
        return memory.getvalue()

    def opener(self, data, wrong_range=False, truncate=False):
        def open_request(request, timeout):
            if request.get_method() == 'HEAD':
                return Response(b'', 200, {'Content-Length': str(len(data)), 'ETag': 'fixed'})
            start, end = map(int, request.get_header('Range').split('=')[1].split('-'))
            self.assertEqual(request.get_header('If-match'), 'fixed')
            return Response(data[start:end+1-(1 if truncate else 0)], 206,
                {'ETag': 'fixed', 'Content-Range': 'wrong' if wrong_range else f'bytes {start}-{end}/{len(data)}'})
        return open_request

    def test_selected_compressed_member_matches_original(self):
        data = self.archive()
        remote = RemoteZip('https://example.org/public.zip', opener=self.opener(data))
        with zipfile.ZipFile(remote) as archive:
            self.assertEqual(archive.read('chosen.wav'), bytes(range(256))*100)
        self.assertTrue(remote.ranges)

    def test_ignored_range_truncation_and_budget_are_rejected(self):
        data = self.archive()
        for wrong, truncated in ((True, False), (False, True)):
            with self.subTest(wrong=wrong, truncated=truncated):
                remote = RemoteZip('https://example.org/public.zip', opener=self.opener(data, wrong, truncated))
                with self.assertRaises(ValueError):
                    remote.read(10)
        remote = RemoteZip('https://example.org/public.zip', byte_budget=9, opener=self.opener(data))
        with self.assertRaises(ValueError):
            remote.read(10)

    def test_selection_is_order_independent_and_balances_performers(self):
        rows = [dict(id=f'{d}/{i}', drummer=d, audio_filename=f'{d}{i}.wav',
                     beat_type='beat', duration='40', time_signature='4-4', style='rock')
                for d in ('a', 'b', 'c') for i in range(4)]
        selected = select_rows(rows, 6)
        self.assertEqual(selected, select_rows(rows[::-1], 6))
        self.assertEqual({r['drummer'] for r in selected[:3]}, {'a', 'b', 'c'})
        for d in ('a', 'b', 'c'):
            self.assertEqual(sum(r['drummer'] == d for r in selected), 2)
        with self.assertRaises(ValueError):
            select_rows(rows, 7)


if __name__ == '__main__':
    unittest.main()
