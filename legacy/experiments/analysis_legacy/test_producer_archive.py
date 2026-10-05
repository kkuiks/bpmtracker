import unittest

from acquire_producer_archive import parse_listing, selected_members


class ProducerArchiveTests(unittest.TestCase):
    def test_listing_and_exact_selection(self):
        listing = 'archive header\n----------\nPath = Folder\\Drums.mid\nSize = 45\nCRC = 1234\nEncrypted = -\n\nPath = Folder\\Mix.wav\nSize = 200\nEncrypted = -\n'
        rows = parse_listing(listing)
        chosen = selected_members(rows, ['Folder\\Drums.mid'], 100)
        self.assertEqual(chosen[0]['output_name'], 'Drums.mid')
        self.assertEqual(chosen[0]['size'], 45)

    def test_unsafe_or_duplicate_paths_are_rejected(self):
        for name in ('../a.mid', '/a.mid', 'a/../../b.wav'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_listing('----------\nPath = '+name+'\nSize = 1\n')
        with self.assertRaises(ValueError):
            parse_listing('----------\nPath = a.mid\nSize = 1\n\nPath = a.mid\nSize = 2\n')

    def test_no_budget_overrun_collision_or_executable(self):
        rows = [{'name': n, 'output_name': o, 'size': s, 'encrypted': False}
                for n, o, s in [('a.mid', 'a.mid', 10), ('nested/a.mid', 'a.mid', 10),
                                ('run.exe', 'run.exe', 1), ('listing.txt', 'listing.txt', 1)]]
        for names, budget in [(['a.mid'], 9), (['a.mid', 'nested/a.mid'], 100),
                              (['run.exe'], 100), (['listing.txt'], 100), (['missing.wav'], 100)]:
            with self.subTest(names=names), self.assertRaises(ValueError):
                selected_members(rows, names, budget)


if __name__ == '__main__':
    unittest.main()
