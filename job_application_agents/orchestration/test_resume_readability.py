import unittest
from job_application_agents.resume_readability import readable_latex, validate_pdf_xml


class ReadabilityTests(unittest.TestCase):
    def test_small_template_commands_are_overridden_before_body(self):
        source = readable_latex(r'\documentclass{article}\begin{document}Text\end{document}')
        self.assertLess(source.index(r'\renewcommand{\small}'), source.index(r'\begin{document}'))
        self.assertIn(r'\fontsize{10}{12}', source)
        with self.assertRaises(ValueError):
            readable_latex('No document')

    def test_actual_pdf_size_and_page_gate(self):
        xml = '<pdf2xml><page width="595" height="842"><fontspec id="0" size="10"/><text font="0" left="40" top="40" width="100" height="12">Readable</text></page></pdf2xml>'
        validate_pdf_xml(xml)
        for bad in (xml.replace('size="10"', 'size="9"'), xml.replace('</pdf2xml>', '<page/></pdf2xml>'), '<pdf2xml><page/></pdf2xml>'):
            with self.assertRaises(ValueError):
                validate_pdf_xml(bad)

        for bad in (xml.replace('width="595"', 'width="612"'),
                    xml.replace('left="40"', 'left="510"'),
                    xml.replace('top="40"', 'top="830"')):
            with self.assertRaises(ValueError):
                validate_pdf_xml(bad)


if __name__ == '__main__':
    unittest.main()
