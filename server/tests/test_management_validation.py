import unittest

from collector.errors import CollectorError
from server.management.service import text


class RegistrationNameTests(unittest.TestCase):
    def test_valid_project_name_and_unicode_names_are_accepted(self):
        for name in ('High Temperature Processing Line','Packaging Line 1','製造ライン 1','Usine Exemple','a'*255):
            with self.subTest(length=len(name)):
                self.assertEqual(text(name,'project name'),name)

    def test_pasted_tabs_and_line_breaks_are_normalized_to_single_line(self):
        for name,expected in (('\r\n  Project Name\r\n','Project Name'),('Project\r\nName','Project Name'),
                              ('High Temperature \r\nProcessing Line','High Temperature Processing Line'),
                              ('Project\tName','Project Name'),('\t'+('a'*255)+'\r\n','a'*255)):
            with self.subTest(length=len(name)):
                self.assertEqual(text(name,'project name'),expected)

    def test_blank_length_and_control_errors_are_distinct(self):
        for name,expected in (('', 'Enter a project name.'),(' \r\n\t ','Enter a project name.'),
                              ('a'*256,'currently 256'),('Project\x00Name','unsupported control character'),
                              ('Project\x1bName','unsupported control character'),('Project\x7fName','unsupported control character')):
            with self.subTest(length=len(name)):
                with self.assertRaisesRegex(CollectorError,expected):text(name,'project name')
