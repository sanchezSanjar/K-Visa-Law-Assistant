import unittest

from kvisa.evaluate import first_hit_rank, is_expected, summarize
from kvisa.search import BM25, rrf, tokenize


class SearchTests(unittest.TestCase):
    def test_tokenize_korean_pairs_and_visa_codes(self):
        tokens = tokenize("유학(D-2) 체류")
        self.assertIn("d-2", tokens)
        self.assertIn("유학", tokens)
        self.assertIn("체류", tokens)

    def test_bm25_ranks_matching_text_first(self):
        bm25 = BM25(["체류기간 연장허가", "외국인등록 신청", "난민인정 신청"])
        self.assertEqual(bm25.search("체류기간을 연장하려면", k=1)[0][0], 0)

    def test_rrf_rewards_agreement(self):
        fused = rrf([(1, 9.0), (2, 8.0)], [(2, 0.9), (3, 0.8)], k=3)
        self.assertEqual(fused[0][0], 2)

    def test_expected_matching(self):
        self.assertTrue(is_expected("immigration_act:25", ["immigration_act:25"]))
        self.assertTrue(is_expected("immigration_rules:9-5#2", ["immigration_rules:9-5"]))
        self.assertFalse(is_expected("immigration_act:2", ["immigration_act:25"]))
        self.assertTrue(is_expected("immigration_decree:table02#2", ["immigration_decree:table02=D-2"]))
        self.assertFalse(is_expected("immigration_decree:table02#1", ["immigration_decree:table02=D-2"]))

    def test_metrics(self):
        ranks = [first_hit_rank(["a", "b"], ["b"]), first_hit_rank(["a"], ["a"]), first_hit_rank(["x"], ["y"])]
        self.assertEqual(ranks, [2, 1, None])
        self.assertEqual(summarize(ranks)["hit@4"], round(2 / 3, 3))


if __name__ == "__main__":
    unittest.main()
