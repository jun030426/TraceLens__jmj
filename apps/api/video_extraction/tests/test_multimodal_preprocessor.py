"""Unit tests for Multimodal Preprocessor (Step 1 Optimization).

Tests project-tailored preprocessing across all 6 modalities:
1. PPT 2D visual layout vs XML Z-order ordering
2. PDF 2-column gutter detection vs 1-column layout sorting
3. PDF Exam question set boundary parsing (1 Question = 1 Set)
4. Audio Whisper initial_prompt technical keyword harvesting
5. Video consecutive identical frame deduplication into intervals
6. Code snippet AST integrity verification and dummy wrapping
"""
import unittest
from video_extraction.pipeline.multimodal_preprocessor import (
    detect_columns_and_sort_blocks,
    parse_exam_question_sets,
    build_whisper_initial_prompt,
    deduplicate_consecutive_frames,
    verify_code_snippet_integrity,
    PREPROCESSOR_POLICY
)


class TestMultimodalPreprocessor(unittest.TestCase):

    def test_single_column_line_grouping_sort(self):
        # 1-column page with line height variations (within 15px)
        blocks = [
            {'id': 'b3', 'text': '세 번째 단락', 'bbox': [302, 50, 350, 600]},
            {'id': 'b1_title', 'text': '강의 제목', 'bbox': [50, 50, 90, 800]},
            {'id': 'b2_sub', 'text': '부제목', 'bbox': [110, 50, 145, 500]},
            {'id': 'b2_date', 'text': '2026.11.03', 'bbox': [112, 600, 144, 800]},
        ]
        sorted_blocks = detect_columns_and_sort_blocks(blocks, page_width=1000)
        ids = [b['id'] for b in sorted_blocks]
        # Title first, then same line b2_sub and b2_date (sorted by x), then b3
        self.assertEqual(ids, ['b1_title', 'b2_sub', 'b2_date', 'b3'])

    def test_two_column_gutter_detection_and_reading_order(self):
        # 2-column layout (e.g. university exam or double-column lecture notes)
        # Left column: x ~ 50..450. Right column: x ~ 550..950. Spanning header: x ~ 50..950.
        blocks = [
            # Top banner header spanning across center
            {'id': 'header', 'text': '2026년 2학기 객체지향프로그래밍 기말시험', 'bbox': [30, 50, 80, 950]},
            
            # Left column: Question 1 and Question 2
            {'id': 'q1', 'text': '1. 자바 가상머신(JVM)의 역할에 대해 서술하시오.', 'bbox': [120, 50, 180, 450]},
            {'id': 'q2', 'text': '2. 가비지 컬렉터의 동작 원리를 고르시오.', 'bbox': [220, 50, 280, 450]},
            
            # Right column: Question 3 and Question 4
            # Notice Y coordinates: Q3 is vertically higher than Q2, but on the right column!
            {'id': 'q3', 'text': '3. 다형성(Polymorphism) 구현 사례를 제시하시오.', 'bbox': [130, 550, 190, 950]},
            {'id': 'q4', 'text': '4. 다음 중 Interface의 특징으로 알맞은 것은?', 'bbox': [230, 550, 290, 950]},
        ]

        sorted_blocks = detect_columns_and_sort_blocks(blocks, page_width=1000)
        ids = [b['id'] for b in sorted_blocks]
        
        # Human reading order MUST be:
        # Header -> Left Col (q1, q2) -> Right Col (q3, q4)
        # Naive Y-sort would have done: header -> q1 -> q3 -> q2 -> q4 (interleaving left and right!)
        self.assertEqual(ids, ['header', 'q1', 'q2', 'q3', 'q4'])

    def test_parse_exam_question_sets_with_options_and_code(self):
        # Exam blocks containing question numbers, code, and multiple choice options
        blocks = [
            {'id': 'header', 'text': '자바 프로그래밍 중간고사 기출문제', 'bbox': [50, 50, 90, 950]},
            {'id': 'q1_stem', 'text': '1. 다음 코드의 실행 결과로 올바른 것은?', 'bbox': [120, 50, 150, 450]},
            {'id': 'q1_code', 'text': '```java\nint x = 5;\nSystem.out.println(x++);\n```', 'bbox': [160, 50, 220, 450]},
            {'id': 'q1_opt1', 'text': '① 5', 'bbox': [230, 50, 250, 200]},
            {'id': 'q1_opt2', 'text': '② 6', 'bbox': [230, 220, 250, 400]},
            {'id': 'q1_opt3', 'text': '③ compile error', 'bbox': [260, 50, 280, 200]},
            {'id': 'q1_opt4', 'text': '④ runtime exception', 'bbox': [260, 220, 280, 400]},
            {'id': 'q2_stem', 'text': '2. 다음 중 객체지향 4대 특징이 아닌 것은?', 'bbox': [320, 50, 350, 450]},
            {'id': 'q2_opt1', 'text': '① 캡슐화', 'bbox': [360, 50, 380, 200]},
            {'id': 'q2_opt2', 'text': '② 다형성', 'bbox': [360, 220, 380, 400]},
            {'id': 'q2_opt3', 'text': '③ 상속성', 'bbox': [390, 50, 410, 200]},
            {'id': 'q2_opt4', 'text': '④ 컴파일 최적화', 'bbox': [390, 220, 410, 400]},
        ]

        qsets = parse_exam_question_sets(blocks)
        # Header + 2 questions = 3 sets total
        self.assertEqual(len(qsets), 3)

        # Question 1 verification
        q1 = qsets[1]
        self.assertTrue(q1['is_exam_question'])
        self.assertIn('1. 다음 코드의 실행 결과로 올바른 것은?', q1['stem'])
        self.assertEqual(len(q1['options']), 4)
        self.assertIn('① 5', q1['options'][0])
        self.assertEqual(len(q1['code_snippets']), 1)
        self.assertIn('int x = 5;', q1['code_snippets'][0])
        # Full text keeps stem + code + options indivisible
        self.assertIn('1. 다음 코드의 실행 결과로 올바른 것은?', q1['question_text'])
        self.assertIn('int x = 5;', q1['question_text'])
        self.assertIn('① 5', q1['question_text'])
        self.assertIn('④ runtime exception', q1['question_text'])

        # Question 2 verification
        q2 = qsets[2]
        self.assertTrue(q2['is_exam_question'])
        self.assertIn('2. 다음 중 객체지향 4대 특징이 아닌 것은?', q2['stem'])
        self.assertEqual(len(q2['options']), 4)
        self.assertIn('④ 컴파일 최적화', q2['options'][3])

    def test_build_whisper_initial_prompt(self):
        texts = [
            "자바 객체지향 프로그래밍 Polymorphism 다형성과 상속 Inheritance 설명",
            "Stack 자료구조는 LIFO 방식으로 동작하며 Queue는 FIFO 방식으로 동작합니다.",
            "Polymorphism 다형성 오버라이딩 Overriding 가상 메서드 테이블 VTable",
            "Stack push pop peek 연산의 시간 복잡도는 O(1) 입니다."
        ]
        prompt = build_whisper_initial_prompt(texts, max_prompt_length=150)
        self.assertTrue(len(prompt) <= 150)
        # Polymorphism, Stack, LIFO, Queue, 다형성과, Inheritance should appear
        self.assertIn("Polymorphism", prompt)
        self.assertIn("Stack", prompt)
        # Common stop words like '합니다', '입니다' must be excluded
        self.assertNotIn("입니다", prompt)
        self.assertNotIn("합니다", prompt)

    def test_deduplicate_consecutive_frames(self):
        # Simulate video frames sampled at 5-second intervals on a lecture slide
        frames = [
            {'id': 'f1', 'time_seconds': 0.0, 'image_sha256': 'hash_slide1', 'observed_text': 'Java Basic'},
            {'id': 'f2', 'time_seconds': 5.0, 'image_sha256': 'hash_slide1', 'observed_text': 'Java Basic'},
            {'id': 'f3', 'time_seconds': 10.0, 'image_sha256': 'hash_slide1', 'observed_text': 'Java Basic'},
            {'id': 'f4', 'time_seconds': 15.0, 'image_sha256': 'hash_slide1', 'observed_text': 'Java Basic'},
            # Slide changes at t=35.0
            {'id': 'f5', 'time_seconds': 35.0, 'image_sha256': 'hash_slide2', 'observed_text': 'Polymorphism'},
            {'id': 'f6', 'time_seconds': 40.0, 'image_sha256': 'hash_slide2', 'observed_text': 'Polymorphism'},
        ]

        deduped = deduplicate_consecutive_frames(frames, max_gap_seconds=10.0)
        self.assertEqual(len(deduped), 2)
        
        # Cluster 1: t=0.0 ~ 15.0
        c1 = deduped[0]
        self.assertEqual(c1['id'], 'f1')
        self.assertEqual(c1['sample_frame_count'], 4)
        self.assertEqual(c1['time_interval']['start_seconds'], 0.0)
        self.assertEqual(c1['time_interval']['end_seconds'], 15.0)

        # Cluster 2: t=35.0 ~ 40.0
        c2 = deduped[1]
        self.assertEqual(c2['id'], 'f5')
        self.assertEqual(c2['sample_frame_count'], 2)
        self.assertEqual(c2['time_interval']['start_seconds'], 35.0)
        self.assertEqual(c2['time_interval']['end_seconds'], 40.0)

    def test_verify_code_snippet_integrity(self):
        # 1. Balanced Java code
        java_ok = """
        public class Calculator {
            public int add(int a, int b) {
                return a + b;
            }
        }
        """
        res_java = verify_code_snippet_integrity(java_ok, language='java')
        self.assertTrue(res_java['valid'])
        self.assertEqual(res_java['reason'], 'brackets_balanced')

        # 2. Unbalanced brackets Java code
        java_broken = """
        public class Calculator {
            public int add(int a, int b) {
                return a + b;
        }
        """
        res_broken = verify_code_snippet_integrity(java_broken, language='java')
        self.assertFalse(res_broken['valid'])
        self.assertTrue(res_broken['reason'].startswith('unclosed_bracket'))

        # 3. Python fragment requiring wrapper
        python_snippet = "return x * 2"
        res_py = verify_code_snippet_integrity(python_snippet, language='python')
        self.assertTrue(res_py['valid'])
        self.assertTrue(res_py['wrapped'])

        # 4. Empty code
        res_empty = verify_code_snippet_integrity("", language='java')
        self.assertFalse(res_empty['valid'])
        self.assertEqual(res_empty['reason'], 'empty_code')


if __name__ == '__main__':
    unittest.main()

