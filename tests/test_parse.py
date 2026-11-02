import json
import unittest

from kvisa.config import ARTICLES
from kvisa.parse import KO_ARTICLE, article_label, clean, join_lines, split_long


class ParseTests(unittest.TestCase):
    def test_article_heading(self):
        match = KO_ARTICLE.match("제25조의2(결혼이민자 등에 대한 특칙) ① 법무부장관은")
        self.assertEqual(match.group(1, 2, 3), ("25", "2", "결혼이민자 등에 대한 특칙"))
        self.assertIsNone(KO_ARTICLE.match("제2조제1호에 따른 외국인"))  # a reference, not a heading

    def test_labels(self):
        self.assertEqual(article_label(25, 2, "ko"), "제25조의2")
        self.assertEqual(article_label(25, 0, "en"), "Article 25")

    def test_join_keeps_items_on_own_lines(self):
        text = join_lines(["제5조(요건) 다음 요건을 갖추어", "야 한다.", "1. 5년 이상 거주할 것", "2. 성년일 것"])
        self.assertEqual(text, "제5조(요건) 다음 요건을 갖추어야 한다.\n1. 5년 이상 거주할 것\n2. 성년일 것")

    def test_clean_removes_amendment_notes(self):
        self.assertEqual(clean("허가를 받아야 한다. <개정 2020. 6. 9.>\n[전문개정 2010. 5. 14.]"),
                         "허가를 받아야 한다.")

    def test_split_long_repeats_header(self):
        text = "제1조(목적) ① " + "가" * 1000 + " ② " + "나" * 1000
        parts = split_long(text, "제1조(목적)")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[1].startswith("제1조(목적) ②"))

    def test_parsed_data(self):
        records = [json.loads(line) for line in ARTICLES.open(encoding="utf-8")]
        ids = {record["id"] for record in records}
        self.assertEqual(len(ids), len(records))
        self.assertIn("immigration_act:25", ids)
        self.assertTrue(any("D-2" in record.get("codes", []) for record in records))
        self.assertLessEqual(max(len(record["text"]) for record in records), 2000)


if __name__ == "__main__":
    unittest.main()
