import unittest

from kvisa.answer import NOT_FOUND, build_context, cited_numbers, is_refusal, question_language

PIECE = {"law_ko": "출입국관리법", "label": "제31조", "title": "외국인등록", "text": "외국인이 입국한 날부터 90일...",
         "text_en": "An alien who intends to stay longer than 90 days..."}


class AnswerTests(unittest.TestCase):
    def test_question_language(self):
        self.assertEqual(question_language("외국인등록은 언제 하나요?"), "ko")
        self.assertEqual(question_language("When must I register?"), "en")
        self.assertEqual(question_language("F-5 비자 조건 알려주세요"), "ko")

    def test_cited_numbers_ignores_unknown_sources(self):
        self.assertEqual(cited_numbers("90일 이내입니다 [1]. 예외도 있습니다 [3][1] [9].", 4), [1, 3])

    def test_cited_numbers_reads_written_out_citations(self):
        self.assertEqual(cited_numbers("[자료] 1번 [안내서]에서 명시하고 있습니다. 자료 2의 표에 따르면", 4), [1, 2])

    def test_context_numbers_pieces_and_adds_english_for_english_questions(self):
        korean = build_context([PIECE], "ko")
        self.assertTrue(korean.startswith("[1] 출입국관리법 제31조(외국인등록)"))
        self.assertNotIn("English translation", korean)
        self.assertIn("English translation", build_context([PIECE], "en"))

    def test_refusal_detection(self):
        self.assertTrue(is_refusal(NOT_FOUND["ko"]))
        self.assertTrue(is_refusal(NOT_FOUND["en"]))
        self.assertFalse(is_refusal("입국한 날부터 90일 이내에 외국인등록을 해야 합니다 [1]."))


if __name__ == "__main__":
    unittest.main()
