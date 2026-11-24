import unittest

from app.transliteration import transliterate_urdu


class TestTransliteration(unittest.TestCase):
    def test_preserves_original_urdu(self):
        text = "واہ اے ابرِ کرم زور برسنا تیرا"
        result = transliterate_urdu(text)
        self.assertEqual(result["original_urdu"], text)

    def test_generates_roman_urdu(self):
        result = transliterate_urdu("واہ اے ابرِ کرم زور برسنا تیرا")
        self.assertTrue(result["roman_urdu"])
        self.assertIn("wah", result["roman_urdu"])

    def test_marks_output_for_review(self):
        result = transliterate_urdu("تیرا دربارِ اعلیٰ")
        self.assertEqual(result["review_status"], "needs_review")

    def test_empty_text(self):
        result = transliterate_urdu("")
        self.assertEqual(result["original_urdu"], "")
        self.assertEqual(result["normalized_urdu"], "")
        self.assertEqual(result["roman_urdu"], "")
        self.assertEqual(result["review_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
