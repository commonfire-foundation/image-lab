import unittest

from image_lab_ui.naming import suggest_names


class NamingTests(unittest.TestCase):
    def image(self, **changes):
        return dict(dict(analyzed=True, name='DSC_1234.JPG',
                         caption='A misty pine forest beside a mountain lake',
                         tags=['pine forest', 'mountain lake', 'fog'],
                         mood='quiet, peaceful', medium='photography'), **changes)

    def test_five_distinct_names_from_metadata_keep_extension(self):
        names = suggest_names(self.image())
        self.assertEqual(len(names), 5)
        self.assertEqual(len({item['name'] for item in names}), 5)
        self.assertEqual(names[0]['name'], 'misty-pine-forest-beside-mountain-lake.JPG')
        self.assertTrue(all(item['name'].endswith('.JPG') for item in names))
        self.assertEqual(names, suggest_names(self.image()))

    def test_missing_or_sparse_data_does_not_pad_with_invented_names(self):
        self.assertEqual(suggest_names({}), [])
        self.assertEqual(suggest_names(self.image(analyzed=False)), [])
        self.assertEqual(suggest_names(self.image(caption='', tags=[])), [])
        names = suggest_names(self.image(caption='Forest', tags=['forest'], mood='', medium=''))
        self.assertEqual(names, [{'style': 'Descriptive', 'name': 'forest.JPG'}])

    def test_unsafe_punctuation_reserved_names_and_length(self):
        names = suggest_names(self.image(caption='../CON', tags=['../CON'], mood='', medium=''))
        self.assertEqual(names[0]['name'], 'image-con.JPG')
        for entry in suggest_names(self.image(caption='湖' * 200, tags=['hello / world: ?'])):
            self.assertLessEqual(len(entry['name'].encode('utf-8')), 104)
            self.assertNotRegex(entry['name'], r'[/\\:?]')

    def test_malformed_optional_values_and_extensionless_name(self):
        names = suggest_names(self.image(name='photo', caption=None, tags=['forest', None], mood=None, medium=None))
        self.assertEqual(names, [{'style': 'Descriptive', 'name': 'forest'}])


if __name__ == '__main__':
    unittest.main()
