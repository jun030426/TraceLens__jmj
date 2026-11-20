"""Unit tests for Unified Multimodal RAG Engine.

Tests all 3 downstream applications powered by the identical RAG core:
1. Grounded Lecture Q&A Chatbot (Multi-turn dialogue & citations)
2. Conceptual Adaptive Quiz Generator (4 choices, explanation, distractor rationales)
3. 30~60s Shorts Video Script Generator (3 acts, visual direction, video timestamps)
"""
import tempfile
import unittest
from pathlib import Path

from rag_mvp.unified_rag import UnifiedMultimodalRAG
from video_extraction.shared.common import save, signature


class TestUnifiedMultimodalRAG(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name)

        # Create sample multimodal chunks
        self.chunks = [
            {
                'id': 'slide_001',
                'title': '다형성과 오버라이딩',
                'slide_number': 1,
                'source_file': 'lecture_ch01.pptx',
                'source_locator': '슬라이드 1',
                'text': '## 다형성과 오버라이딩 (슬라이드 1)\n\n**[교수님 필기 강조 키워드]**: 다형성, 오버라이딩\n\n자바에서 다형성이란 하나의 객체가 여러 가지 형태를 가질 수 있는 성질입니다.\n\n**[강사 음성 해설]**:\n다형성은 객체지향의 꽃입니다. 반드시 시험에 출제되니 오버라이딩과의 관계를 꼭 기억하세요.\n\n```java\n# c1\nclass Animal { void sound() { System.out.println(\"소리\"); } }\n```',
                'concept_ids': ['oop.polymorphism'],
                'emphasized_keywords': ['다형성', '오버라이딩'],
                'time_interval': {'start_seconds': 120.0, 'end_seconds': 180.0}
            },
            {
                'id': 'slide_002',
                'title': '스택(Stack)과 큐(Queue)',
                'slide_number': 2,
                'source_file': 'lecture_ch02.pptx',
                'source_locator': '슬라이드 2',
                'text': '## 스택(Stack)과 큐(Queue) (슬라이드 2)\n\n**[교수님 필기 강조 키워드]**: LIFO, FIFO\n\n스택은 후입선출(LIFO) 구조이며, 큐는 선입선출(FIFO) 구조입니다.\n\n**[강사 음성 해설]**:\n스택의 push와 pop 연산 시간 복잡도는 O(1)입니다.',
                'concept_ids': ['data_structures.stack'],
                'emphasized_keywords': ['LIFO', 'FIFO', '스택'],
                'time_interval': {'start_seconds': 240.0, 'end_seconds': 300.0}
            }
        ]

        # Valid corpus structure
        corpus_data = {
            'version': 1,
            'signature': signature({'version': 1, 'chunks': self.chunks}),
            'chunks': self.chunks,
            'concept_index': {
                'oop.polymorphism': ['slide_001'],
                'data_structures.stack': ['slide_002']
            }
        }
        save(self.out_dir / 'corpus.json', corpus_data)
        self.rag = UnifiedMultimodalRAG(self.out_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_corpus_loading_and_concept_index(self):
        self.assertEqual(len(self.rag.chunks), 2)
        self.assertIn('oop.polymorphism', self.rag.concept_index)
        self.assertIn('data_structures.stack', self.rag.concept_index)

    def test_hybrid_retrieval_with_keyword_and_concept_filter(self):
        # 1. Concept-filtered retrieval
        hits = self.rag.retrieve('후입선출', concept_id='data_structures.stack')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['id'], 'slide_002')

        # 2. General query retrieval
        hits_poly = self.rag.retrieve('다형성')
        self.assertGreaterEqual(len(hits_poly), 1)
        self.assertEqual(hits_poly[0]['id'], 'slide_001')

    def test_multimodal_context_formatting(self):
        hits = self.rag.retrieve('다형성')
        context = self.rag.format_multimodal_context(hits)
        self.assertIn('슬라이드 1', context)
        self.assertIn('[영상 시간: 02:00 ~ 03:00]', context)
        self.assertIn('[교수님 필기 강조 키워드]: 다형성, 오버라이딩', context)
        self.assertIn('강사 음성 해설', context)

    def test_downstream_chatbot_engine(self):
        # Chatbot question answering with citations
        res = self.rag.ask_chat('다형성이란 무엇인가요?')
        self.assertTrue(res['answerable'])
        self.assertIn('다형성', res['reply'])
        self.assertEqual(len(res['citations']), 1)
        self.assertEqual(res['citations'][0]['source_id'], 'slide_001')
        self.assertEqual(res['citations'][0]['locator'], '슬라이드 1')

    def test_beginner_scaffolding_chat_prompt(self):
        # Verify beginner-level scaffolding guidelines in chat prompt
        prompt = self.rag._build_chat_prompt('스택의 pop은 어떻게 구현하나요?', '[슬라이드 3] 스택 pop 연산', history=[
            {'role': 'user', 'content': '스택이 뭐예요?'},
            {'role': 'assistant', 'content': '스택은 접시를 쌓는 것과 같은 LIFO 구조입니다.'}
        ])
        self.assertIn('초심자 학부생', prompt)
        self.assertIn('완성된 정답 코드 통째 복붙 금지', prompt)
        self.assertIn('일상 비유', prompt)
        self.assertIn('교수님 비유 최우선 계승', prompt)
        self.assertIn('AI 초심자 비유 자동 보완', prompt)
        self.assertIn('1번에 딱 1개만 묻는 직관적인 유도 질문', prompt)
        self.assertIn('교수님이 강의에서 사용하신 변수명', prompt)
        self.assertIn('스택이 뭐예요?', prompt)

    def test_professor_analogy_extraction_and_prompting(self):
        # Verify professor analogy metadata extraction
        chunk_springles = {
            'id': 'c-analogy-1',
            'title': '스택 개요',
            'text': '스택은 마치 프링글스 통에서 감자칩을 꺼내는 동작과 같습니다.'
        }
        meta_pringles = UnifiedMultimodalRAG.extract_ds_metadata(chunk_springles)
        self.assertEqual(meta_pringles['professor_analogy'], '프링글스 통')
        self.assertEqual(meta_pringles['data_structure'], 'stack')

        chunk_plates = {
            'id': 'c-analogy-2',
            'title': '스택의 특징',
            'text': '강의 설명: 식당 배식대 접시 쌓기에 비유하여 생각할 수 있습니다.'
        }
        meta_plates = UnifiedMultimodalRAG.extract_ds_metadata(chunk_plates)
        self.assertEqual(meta_plates['professor_analogy'], '접시 쌓기')

        # When no analogy is present in lecture chunk
        chunk_no_analogy = {
            'id': 'c-analogy-3',
            'title': '스택 정의',
            'text': 'LIFO(Last In First Out) 순서로 동작하는 선형 자료구조이다.'
        }
        meta_none = UnifiedMultimodalRAG.extract_ds_metadata(chunk_no_analogy)
        self.assertIsNone(meta_none['professor_analogy'])

        # Context formatting contains professor analogy when available
        chunk_springles['ds_metadata'] = meta_pringles
        formatted = self.rag.format_multimodal_context([chunk_springles])
        self.assertIn('교수님 비유: 프링글스 통', formatted)

    def test_downstream_quiz_engine(self):
        # 4-choice conceptual quiz generation
        quiz = self.rag.generate_quiz('다형성')
        self.assertTrue(quiz['success'])
        self.assertIn('다형성', quiz['question_stem'])
        self.assertEqual(len(quiz['options']), 4)
        self.assertEqual(quiz['correct_index'], 0)
        self.assertIn('슬라이드 1', quiz['source_locator'])
        self.assertTrue(len(quiz['distractor_rationales']) >= 3)

    def test_downstream_shorts_script_engine(self):
        # 30~60s short-form video script generation with video timestamps
        shorts = self.rag.generate_shorts_script('다형성', target_seconds=60)
        self.assertTrue(shorts['success'])
        self.assertIn('다형성', shorts['title'])
        self.assertEqual(shorts['target_seconds'], 60)
        self.assertEqual(shorts['original_video_timestamp'], '02:00 ~ 03:00')
        self.assertEqual(len(shorts['acts']), 3)

        # Hook (0~5s)
        act_hook = shorts['acts'][0]
        self.assertEqual(act_hook['act'], 'Hook')
        self.assertIn('다형성', act_hook['visual_direction'])

        # Body (5~45s)
        act_body = shorts['acts'][1]
        self.assertEqual(act_body['act'], 'Body')

        # Outro (45~60s)
        act_outro = shorts['acts'][2]
        self.assertEqual(act_outro['act'], 'Outro')
        self.assertIn('02:00 ~ 03:00', act_outro['narration'])

        # Render HTML test
        html_out = self.out_dir / 'test_shorts.html'
        content = self.rag.render_shorts_html(shorts, html_out)
        self.assertTrue(html_out.exists())
        self.assertIn('숏츠 영상 대본', content)
        self.assertIn('02:00 ~ 03:00', content)

    def test_shorts_candidate_scoring_triangulation(self):
        # slide_001 has:
        # - Speech: 60s (120~180s)
        # - Ink: 2 keywords ('다형성', '오버라이딩') -> 80 pts
        # - PPT: code block + text -> text + 30 code pts
        metrics_001 = self.rag.score_chunk_for_shorts(self.chunks[0], max_duration=60.0)
        self.assertEqual(metrics_001['speech_score'], 100.0)  # 60s / 60s * 100
        self.assertEqual(metrics_001['ink_score'], 80.0)      # 2 keywords
        self.assertTrue(metrics_001['has_code'])
        self.assertGreaterEqual(metrics_001['ppt_score'], 50.0)
        self.assertGreaterEqual(metrics_001['total_score'], 75.0)  # Gold tier

        # Create a bare slide (short speech, no ink, little text)
        bare_chunk = {
            'id': 'slide_bare',
            'title': '강의 공지사항',
            'slide_number': 3,
            'text': '## 공지사항\n\n과제는 다음 주까지 제출하세요.',
            'time_interval': {'start_seconds': 0.0, 'end_seconds': 5.0},
            'emphasized_keywords': []
        }
        metrics_bare = self.rag.score_chunk_for_shorts(bare_chunk, max_duration=60.0)
        self.assertLess(metrics_bare['speech_score'], 15.0)
        self.assertEqual(metrics_bare['ink_score'], 0.0)
        self.assertFalse(metrics_bare['has_code'])
        self.assertLess(metrics_bare['total_score'], 30.0)  # Filtered out!

    def test_extract_shorts_candidates_ranking_and_filtering(self):
        candidates = self.rag.extract_shorts_candidates(min_score=65.0, top_n=5)
        self.assertTrue(len(candidates) >= 1)
        # Top candidate should be slide_001 (has code, high speech, and 2 ink keywords)
        top_cand = candidates[0]
        self.assertEqual(top_cand['id'], 'slide_001')
        self.assertEqual(top_cand['tier'], 'Gold')
        self.assertIn('다형성', top_cand['recommended_hook'])

        # Auto generation using None topic
        auto_script = self.rag.generate_shorts_script()
        self.assertTrue(auto_script['success'])
        self.assertIn('다형성', auto_script['title'])
        self.assertEqual(auto_script['source_id'], 'slide_001')

    def test_multi_slide_concept_bundling(self):
        # Create a corpus where slides 2 and 3 share concept 'data_structures.stack'
        multi_chunks = [
            {
                'id': 'slide_002',
                'title': '스택(Stack)의 기본 개념',
                'slide_number': 2,
                'source_file': 'lecture_ch02.pptx',
                'source_locator': '슬라이드 2',
                'text': '## 스택의 기본 개념 (슬라이드 2)\n\n스택은 후입선출(LIFO) 자료구조입니다.',
                'concept_ids': ['data_structures.stack'],
                'emphasized_keywords': ['LIFO'],
                'time_interval': {'start_seconds': 100.0, 'end_seconds': 140.0}
            },
            {
                'id': 'slide_003',
                'title': '스택(Stack) 연산 및 코드 구현',
                'slide_number': 3,
                'source_file': 'lecture_ch02.pptx',
                'source_locator': '슬라이드 3',
                'text': '## 스택 연산 (슬라이드 3)\n\nPush와 Pop 연산이 일어납니다.\n```python\nstack.append(1)\n```',
                'concept_ids': ['data_structures.stack'],
                'emphasized_keywords': ['Push', 'Pop'],
                'time_interval': {'start_seconds': 140.0, 'end_seconds': 200.0}
            }
        ]
        test_dir = self.out_dir / 'multi_test'
        test_dir.mkdir(parents=True, exist_ok=True)
        save(test_dir / 'corpus.json', {
            'version': 1,
            'signature': signature({'version': 1, 'chunks': multi_chunks}),
            'chunks': multi_chunks,
            'concept_index': {'data_structures.stack': ['slide_002', 'slide_003']}
        })
        multi_rag = UnifiedMultimodalRAG(test_dir)
        candidates = multi_rag.extract_shorts_candidates(min_score=60.0, group_by_concept=True)
        self.assertEqual(len(candidates), 1)
        cand = candidates[0]
        self.assertTrue(cand['is_multi_slide'])
        self.assertEqual(cand['slide_count'], 2)
        self.assertIn('슬라이드 2~3', cand['source_locator'])
        self.assertEqual(cand['metrics']['duration_seconds'], 100.0)  # 40s + 60s
        self.assertTrue(cand['metrics']['has_code'])  # from slide 3!

        # Script generation from bundled concept
        script = multi_rag.generate_shorts_script(chunk_id=cand['id'])
        self.assertTrue(script['success'])
        self.assertIn('슬라이드 2~3', script['source_locator'])

    def test_hybrid_rule_and_handwriting_bonus(self):
        # 1. Verify Handwriting as Pure Additive Bonus:
        # A slide with full speech and full PPT but NO handwriting should achieve base_score = 100
        no_ink_chunk = {
            'id': 'slide_no_ink',
            'title': '이론 완벽 정리',
            'slide_number': 10,
            'text': '## 완벽 이론 정리\n\n' + ('상세한 강의 텍스트 설명입니다. ' * 20) + '\n```java\nint x = 10;\n```\n[시각 자료/다이어그램]: 도표 설명',
            'time_interval': {'start_seconds': 0.0, 'end_seconds': 120.0},
            'emphasized_keywords': []  # No ink at all!
        }
        metrics_no_ink = self.rag.score_chunk_for_shorts(no_ink_chunk, max_duration=120.0)
        self.assertEqual(metrics_no_ink['speech_score'], 100.0)
        self.assertEqual(metrics_no_ink['ppt_score'], 100.0)
        self.assertEqual(metrics_no_ink['ink_bonus'], 0.0)
        # Even with 0 ink bonus, base_score and total_score reach 100.0!
        self.assertEqual(metrics_no_ink['base_score'], 100.0)
        self.assertEqual(metrics_no_ink['total_score'], 100.0)

        # 2. Verify Hybrid Rule Fallback:
        # Create chunks where none reach min_score=75.0 (c1 has ~70 pts)
        # With min_score=75.0 and ensure_min_candidates=3:
        # Primary filter finds 0 candidates >= 75.
        # Fallback kicks in and safely returns top 3 while rejecting the low score slide (c4)!
        borderline_chunks = [
            {'id': 'c1', 'title': '슬라이드 1', 'slide_number': 1, 'text': '개념 A', 'time_interval': {'start_seconds': 0.0, 'end_seconds': 80.0}, 'emphasized_keywords': []},
            {'id': 'c2', 'title': '슬라이드 2', 'slide_number': 2, 'text': '개념 B', 'time_interval': {'start_seconds': 0.0, 'end_seconds': 70.0}, 'emphasized_keywords': []},
            {'id': 'c3', 'title': '슬라이드 3', 'slide_number': 3, 'text': '개념 C', 'time_interval': {'start_seconds': 0.0, 'end_seconds': 65.0}, 'emphasized_keywords': []},
            {'id': 'c4', 'title': '단순 공지', 'slide_number': 4, 'text': '공지', 'time_interval': {'start_seconds': 0.0, 'end_seconds': 5.0}, 'emphasized_keywords': []}
        ]
        test_dir = self.out_dir / 'hybrid_test'
        test_dir.mkdir(parents=True, exist_ok=True)
        save(test_dir / 'corpus.json', {
            'version': 1,
            'signature': signature({'version': 1, 'chunks': borderline_chunks}),
            'chunks': borderline_chunks,
            'concept_index': {}
        })
        hybrid_rag = UnifiedMultimodalRAG(test_dir)
        candidates = hybrid_rag.extract_shorts_candidates(min_score=75.0, ensure_min_candidates=3, fallback_floor=40.0)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0]['id'], 'c1')
        self.assertEqual(candidates[0]['selection_rule'], 'hybrid_fallback')
        self.assertEqual(candidates[2]['id'], 'c3')

    def test_heygen_export_and_neutral_tone(self):
        # Generate script and ensure sensational exam claims are completely absent
        script = self.rag.generate_shorts_script('다형성')
        self.assertTrue(script['success'])
        narration_all = " ".join(act['narration'] for act in script['acts'])
        title = script['title']

        # Verify no "시험에 꼭 나온다" or "교수님이 중요하다고 함"
        self.assertNotIn('시험에 꼭', title)
        self.assertNotIn('시험에 무조건', narration_all)
        self.assertNotIn('교수님이 중요', narration_all)
        self.assertNotIn('빨간 펜', narration_all)

        # Verify HeyGen & Canva export
        hg_res = self.rag.export_heygen_format(script, out_dir=self.out_dir)
        self.assertTrue(hg_res['txt_file'].exists())
        self.assertTrue(hg_res['json_file'].exists())
        self.assertTrue(hg_res['canva_csv'].exists())

        txt_text = hg_res['txt_file'].read_text(encoding='utf-8')
        self.assertIn('헤이젠(HeyGen) 숏츠 영상 제작 전용 대본', txt_text)
        self.assertIn('9:16', txt_text)
        self.assertIn('Circle PiP', txt_text)
        self.assertNotIn('표준 디자인 테마 스키마', txt_text)

        payload = hg_res['api_payload']
        self.assertEqual(payload['dimension']['width'], 1080)
        self.assertEqual(payload['dimension']['height'], 1920)
        self.assertEqual(len(payload['video_inputs']), 3)
        self.assertEqual(payload['video_inputs'][1]['character']['avatar_style'], 'circle')
        self.assertNotIn('design_schema', payload)

    def test_ds_metadata_extraction_and_enrichment(self):
        """Verify algorithm and data structure metadata extraction and reverse indexing."""
        sample_stack_chunk = {
            'id': 'test-ds-1',
            'title': '스택의 pop 연산과 언더플로우 방어',
            'text': '스택(Stack)에서 pop() 연산을 수행할 때는 비어있는지 확인하여 underflow를 방지해야 합니다. O(1) 시간 복잡도를 가집니다. 배열 stack[top--] 기반 구현입니다.',
            'concept_ids': ['data_structures.stack'],
            'emphasized_keywords': ['스택', 'pop', 'underflow']
        }
        meta = UnifiedMultimodalRAG.extract_ds_metadata(sample_stack_chunk)
        self.assertEqual(meta['data_structure'], 'stack')
        self.assertEqual(meta['operation'], 'pop')
        self.assertEqual(meta['time_complexity'], 'O(1)')
        self.assertIn('underflow', meta['edge_cases'])
        self.assertEqual(meta['implementation_style'], 'array_based')

        sample_queue_chunk = {
            'id': 'test-ds-2',
            'title': '원형 큐(Circular Queue)의 enqueue 연산',
            'text': '원형 큐에서 데이터를 삽입(enqueue)할 때는 포화 상태(overflow)를 방지해야 합니다. 포인터 기반 노드로 구현됩니다.',
            'concept_ids': ['data_structures.queue'],
            'emphasized_keywords': ['원형 큐', 'enqueue']
        }
        meta_q = UnifiedMultimodalRAG.extract_ds_metadata(sample_queue_chunk)
        self.assertEqual(meta_q['data_structure'], 'queue')
        self.assertEqual(meta_q['operation'], 'enqueue')
        self.assertEqual(meta_q['time_complexity'], 'O(1)')
        self.assertIn('overflow', meta_q['edge_cases'])
        self.assertEqual(meta_q['implementation_style'], 'pointer_based')

        sample_algo_chunk = {
            'id': 'test-ds-3',
            'title': '이진 탐색(Binary Search)과 분할 정복',
            'text': '이진 탐색 알고리즘은 분할 정복(divide and conquer) 패러다임으로 O(log N) 시간에 정렬된 배열을 탐색합니다.',
            'concept_ids': ['algorithms.search'],
            'emphasized_keywords': ['이진 탐색', '분할 정복']
        }
        meta_a = UnifiedMultimodalRAG.extract_ds_metadata(sample_algo_chunk)
        self.assertEqual(meta_a['algorithm_type'], 'binary_search')
        self.assertEqual(meta_a['algorithm_paradigm'], 'divide_and_conquer')
        self.assertEqual(meta_a['time_complexity'], 'O(LOGN)')

    def test_ds_metadata_retrieval_filtering(self):
        """Verify fine-grained retrieval filtering using data_structure, operation, complexity, and edge_case."""
        # Inject custom chunks with DS metadata into test RAG
        c_stack = {
            'id': 'ds-c1',
            'title': '스택 Pop 연산',
            'text': '스택에서 pop() 연산은 O(1)이며 underflow를 체크합니다.',
            'ds_metadata': {
                'data_structure': 'stack',
                'operation': 'pop',
                'time_complexity': 'O(1)',
                'edge_cases': ['underflow'],
                'implementation_style': 'array_based'
            }
        }
        c_queue = {
            'id': 'ds-c2',
            'title': '큐 Enqueue 연산',
            'text': '큐에서 enqueue() 연산은 O(1)이며 overflow를 체크합니다.',
            'ds_metadata': {
                'data_structure': 'queue',
                'operation': 'enqueue',
                'time_complexity': 'O(1)',
                'edge_cases': ['overflow'],
                'implementation_style': 'pointer_based'
            }
        }
        c_algo = {
            'id': 'ds-c3',
            'title': '스택을 이용한 괄호 검사 알고리즘',
            'text': '괄호 매칭 검사 알고리즘은 스택을 활용하여 O(N)에 판정합니다.',
            'ds_metadata': {
                'data_structure': 'stack',
                'algorithm_type': 'bracket_matching',
                'time_complexity': 'O(N)'
            }
        }
        test_rag = UnifiedMultimodalRAG(self.out_dir)
        test_rag.chunks = [c_stack, c_queue, c_algo]
        test_rag.chunks_by_id = {c['id']: c for c in test_rag.chunks}

        # Filter by data_structure='stack'
        hits_stack = test_rag.retrieve('연산', data_structure='stack')
        self.assertEqual(len(hits_stack), 1)
        self.assertEqual(hits_stack[0]['id'], 'ds-c1')

        # Filter by algorithm_type='bracket_matching'
        hits_algo = test_rag.retrieve('검사', algorithm_type='bracket_matching')
        self.assertEqual(len(hits_algo), 1)
        self.assertEqual(hits_algo[0]['id'], 'ds-c3')

        # Filter by operation='enqueue'
        hits_queue = test_rag.retrieve('연산', operation='enqueue')
        self.assertEqual(len(hits_queue), 1)
        self.assertEqual(hits_queue[0]['id'], 'ds-c2')

        # Filter by edge_case='underflow'
        hits_edge = test_rag.retrieve('체크', edge_case='underflow')
        self.assertEqual(len(hits_edge), 1)
        self.assertEqual(hits_edge[0]['id'], 'ds-c1')

        # Filter by implementation_style='pointer_based'
        hits_style = test_rag.retrieve('연산', implementation_style='pointer_based')
        self.assertEqual(len(hits_style), 1)
        self.assertEqual(hits_style[0]['id'], 'ds-c2')

    def test_ds_metadata_context_formatting_and_summary(self):
        """Verify that format_multimodal_context includes the DS metadata block and summary works."""
        c_test = {
            'id': 'ds-fmt-1',
            'title': '스택 구현',
            'source_locator': '슬라이드 5',
            'text': '스택의 pop 연산입니다.',
            'ds_metadata': {
                'data_structure': 'stack',
                'operation': 'pop',
                'time_complexity': 'O(1)',
                'space_complexity': 'O(N)',
                'edge_cases': ['underflow'],
                'implementation_style': 'array_based'
            }
        }
        test_rag = UnifiedMultimodalRAG(self.out_dir)
        test_rag.chunks = [c_test]
        formatted = test_rag.format_multimodal_context([c_test])
        self.assertIn('[자료구조/알고리즘 메타데이터]:', formatted)
        self.assertIn('자료구조: stack', formatted)
        self.assertIn('연산: pop', formatted)
        self.assertIn('시간복잡도: O(1)', formatted)
        self.assertIn('엣지케이스: underflow', formatted)

        # Verify summary statistics
        summary = test_rag.get_ds_metadata_summary()
        self.assertEqual(summary['total_chunks'], 1)
        self.assertEqual(summary['ds_classified_chunks'], 1)
        self.assertEqual(summary['structures'].get('stack'), 1)
        self.assertEqual(summary['operations'].get('pop'), 1)
        self.assertEqual(summary['edge_cases'].get('underflow'), 1)


if __name__ == '__main__':
    unittest.main()

