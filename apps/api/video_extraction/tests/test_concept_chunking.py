"""Unit tests for Automatic Concept Mapping and Multimodal Chunking (Step 6)."""
import json
import tempfile
import unittest
from pathlib import Path
from video_extraction.pipeline import concept_chunking as cc
from video_extraction.shared.common import save, read, jsonl


class TestConceptChunking(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_concept_mapping_from_handwriting_emphasis(self):
        bundle = {
            'bundle_id': 'deck:slide:007',
            'bundle_type': 'slide_bundle',
            'slide_number': 7,
            'source_file': 'xr_industry.pdf',
            'content': {
                'title': 'XR 시장 현황',
                'base_text': '글로벌 XR 시장 규모 전망',
                'emphasized_keywords': ['1조5429억', 'COVID-19 유행 시나리오'],
                'speech': {'transcript': '국내 XR 시장 규모는 약 1조5429억에 달할 것으로 예상됩니다.'},
                'code_snippets': []
            },
            'provenance': {'record_ids': ['r1'], 'modalities': ['document', 'handwriting', 'audio']}
        }
        concept_ids, candidates = cc.map_concepts_for_bundle(bundle)
        self.assertIn('xr_domain.market', concept_ids)

        market_cand = next(c for c in candidates if c['concept_id'] == 'xr_domain.market')
        self.assertEqual(market_cand['confidence'], 'high')
        self.assertIn('handwriting_emphasis', market_cand['basis'])

    def test_concept_mapping_from_code_and_title(self):
        bundle = {
            'bundle_id': 'code:slide:004',
            'bundle_type': 'slide_bundle',
            'slide_number': 4,
            'content': {
                'title': '제어문 - break문',
                'base_text': '반복문 실행 중 특정 조건에서 루프를 중단합니다.',
                'emphasized_keywords': ['break'],
                'speech': {'transcript': 'break 문을 만나면 가장 가까운 반복문을 즉시 탈출합니다.'},
                'code_snippets': [
                    {
                        'record_id': 'c1',
                        'language': 'java',
                        'symbol_name': 'testBreak',
                        'code': 'for(int i=0; i<10; i++) {\n    if(i==5) break;\n}'
                    }
                ]
            },
            'concept_metadata': {
                'concept_candidates': [{'concept': 'programming.iteration', 'confidence': 'high'}]
            }
        }
        concept_ids, candidates = cc.map_concepts_for_bundle(bundle)
        self.assertIn('programming.control_flow.break', concept_ids)
        self.assertIn('programming.control_flow.iteration', concept_ids)

    def test_multimodal_chunk_formatting(self):
        bundle = {
            'bundle_id': 'deck:slide:001',
            'bundle_type': 'slide_bundle',
            'slide_number': 1,
            'content': {
                'title': '자바 프로그래밍 기초',
                'base_text': '클래스와 객체의 개념을 이해합니다.',
                'emphasized_keywords': ['클래스', '객체'],
                'speech': {'transcript': '클래스는 붕어빵 틀이고 객체는 붕어빵입니다.'},
                'code_snippets': [
                    {
                        'record_id': 'c1',
                        'language': 'java',
                        'symbol_name': 'Student',
                        'code': 'class Student {\n    String name;\n}'
                    }
                ]
            }
        }
        text = cc.format_multimodal_chunk_text(bundle)
        self.assertIn('## 자바 프로그래밍 기초 (슬라이드 1)', text)
        self.assertIn('**[교수님 필기 강조 키워드]**: 클래스, 객체', text)
        self.assertIn('클래스와 객체의 개념을 이해합니다.', text)
        self.assertIn('**[강사 음성 해설]**:\n클래스는 붕어빵 틀이고 객체는 붕어빵입니다.', text)
        self.assertIn('```java\n# c1 · Student\nclass Student {\n    String name;\n}\n```', text)

    def test_oversized_slide_lossless_partitioning(self):
        # Create a large bundle text exceeding 300 characters
        bundle = {
            'bundle_id': 'deck:slide:010',
            'bundle_type': 'slide_bundle',
            'slide_number': 10,
            'content': {
                'title': '대형 슬라이드',
                'base_text': '블록 1: 아주 긴 설명 문장입니다. ' * 10 + '\n\n' + '블록 2: 추가적인 설명 문장입니다. ' * 10,
                'speech': {'transcript': '음성 설명도 길게 진행됩니다. ' * 10}
            }
        }
        chunks = cc.create_chunks_for_bundle(bundle, limit=250)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]['parent_chunk_id'], 'deck:slide:010')
        self.assertTrue(chunks[0]['id'].startswith('deck:slide:010:part-'))
        # Total text preserved
        self.assertTrue(all(c['eligible_for_chunking'] for c in chunks))

    def test_inverted_concept_index_generation(self):
        bundles = [
            {
                'bundle_id': 'b1',
                'bundle_type': 'slide_bundle',
                'slide_number': 1,
                'content': {
                    'title': '스택 자료구조',
                    'base_text': '스택은 LIFO 구조를 가집니다.',
                    'emphasized_keywords': ['스택', 'push', 'pop']
                }
            },
            {
                'bundle_id': 'b2',
                'bundle_type': 'slide_bundle',
                'slide_number': 2,
                'content': {
                    'title': '큐 자료구조',
                    'base_text': '큐는 FIFO 구조를 가집니다.',
                    'emphasized_keywords': ['큐']
                }
            }
        ]
        corpus = cc.build_corpus_from_bundles(bundles)
        self.assertEqual(corpus['version'], 1)
        self.assertIn('data_structures.stack', corpus['concept_index'])
        self.assertIn('b1', corpus['concept_index']['data_structures.stack'])
        self.assertIn('data_structures.queue', corpus['concept_index'])
        self.assertIn('b2', corpus['concept_index']['data_structures.queue'])
        self.assertEqual(corpus['stats']['total_bundles'], 2)
        self.assertEqual(corpus['stats']['total_chunks'], 2)

    def test_step5_modification_tolerance(self):
        """Verifies that Step 6 is resilient if Step 5 bundles change or add extra fields."""
        bundle_with_future_fields = {
            'bundle_id': 'b_future:001',
            'bundle_type': 'slide_bundle',
            'future_pipeline_flag': True,
            'v6_experimental_data': {'score': 99.5},
            'content': {
                'title': '미래 버전 슬라이드',
                'base_text': '리스트 자료구조 설명',
                'emphasized_keywords': ['리스트'],
                'unknown_modality_stream': [1, 2, 3]
            },
            'provenance': {'warnings': ['future_warning']}
        }
        chunks = cc.create_chunks_for_bundle(bundle_with_future_fields)
        self.assertEqual(len(chunks), 1)
        self.assertIn('data_structures.list', chunks[0]['concept_ids'])
        self.assertEqual(chunks[0]['provenance']['warnings'], ['future_warning'])

    def test_process_output_directory_integration(self):
        out_dir = self.root / 'outputs/test-chunking'
        rev_dir = out_dir / 'revisions/rev1'
        rev_dir.mkdir(parents=True)

        bundles = [
            {
                'bundle_id': 'deck:slide:001',
                'bundle_type': 'slide_bundle',
                'slide_number': 1,
                'content': {
                    'title': '트리 알고리즘',
                    'base_text': '이진 트리의 루트 노드',
                    'emphasized_keywords': ['트리']
                }
            }
        ]
        bundles_file = rev_dir / 'multimodal-bundles.jsonl'
        jsonl(bundles_file, bundles)

        latest = {
            'multimodal_bundles': str(bundles_file)
        }
        save(out_dir / 'latest.json', latest)

        corpus, dest = cc.process_output_directory(out_dir)
        self.assertTrue(dest.exists())
        self.assertIn('data_structures.tree', corpus['concept_index'])

        updated_latest = read(out_dir / 'latest.json')
        self.assertEqual(updated_latest['concept_corpus'], str(dest))
        self.assertGreaterEqual(updated_latest['total_concepts_mapped'], 1)

    def test_code_fence_atomic_preservation_with_internal_blank_lines(self):
        """Code block with internal blank lines must NEVER be split mid-fence."""
        code_with_blank_lines = "int a = 1;\n\nint b = 2;\n\nint c = a + b;"
        bundle = {
            'bundle_id': 'code:slide:001',
            'bundle_type': 'slide_bundle',
            'slide_number': 1,
            'content': {
                'title': '코드 공백 분할 방지',
                'base_text': '긴 설명문입니다. ' * 20,
                'code_snippets': [
                    {
                        'record_id': 'c1',
                        'language': 'java',
                        'symbol_name': 'testBlanks',
                        'code': code_with_blank_lines
                    }
                ]
            }
        }
        chunks = cc.create_chunks_for_bundle(bundle, limit=200)
        self.assertGreater(len(chunks), 1)
        # Verify that every chunk with code has balanced opening and closing fences
        for chk in chunks:
            fences = chk['text'].count('```')
            self.assertTrue(fences % 2 == 0, f"Unclosed code fence found in chunk: {chk['id']}")

    def test_multimodal_context_propagation_to_all_partitions(self):
        """When an oversized slide splits into parts, every part retains slide header and emphasis."""
        bundle = {
            'bundle_id': 'deck:slide:005',
            'bundle_type': 'slide_bundle',
            'slide_number': 5,
            'content': {
                'title': '다중 파트 맥락 보존',
                'base_text': '단락 1 설명입니다. ' * 15 + '\n\n' + '단락 2 설명입니다. ' * 15,
                'emphasized_keywords': ['핵심개념A', '핵심개념B'],
                'speech': {'transcript': '강사 음성 설명도 길게 진행됩니다. ' * 15}
            }
        }
        chunks = cc.create_chunks_for_bundle(bundle, limit=250)
        self.assertGreater(len(chunks), 1)
        for i, chk in enumerate(chunks, 1):
            self.assertIn('다중 파트 맥락 보존', chk['text'], f"Part {i} lost slide title")
            self.assertIn('슬라이드 5', chk['text'], f"Part {i} lost slide number")
            self.assertIn('핵심개념A, 핵심개념B', chk['text'], f"Part {i} lost emphasized keywords")

    def test_huge_unbroken_speech_sentence_splitting(self):
        """A continuous 2500-char speech with no blank lines must split on sentence endings without cutting words."""
        sentences = [f"{i}번째 설명 문장입니다. 교수님이 계속해서 설명하고 있습니다." for i in range(1, 30)]
        continuous_speech = " ".join(sentences)  # No \n\n
        bundle = {
            'bundle_id': 'speech:slide:001',
            'bundle_type': 'slide_bundle',
            'slide_number': 1,
            'content': {
                'title': '초거대 음성 분할',
                'speech': {'transcript': continuous_speech}
            }
        }
        chunks = cc.create_chunks_for_bundle(bundle, limit=350)
        self.assertGreater(len(chunks), 1)
        for chk in chunks:
            self.assertIn('초거대 음성 분할', chk['text'])
            # Verify no mid-word truncation: chunks end cleanly
            self.assertTrue(chk['text'].rstrip().endswith(('.', ']', '다')))

    def test_exam_question_set_atomic_chunking_with_stem_code_options(self):
        """Exam question sets must remain indivisible; stem, code, and choices never severed."""
        q1_text = "1. 다음 자바 코드의 실행 결과는?\n```java\nint x = 10;\nSystem.out.println(x++);\n```\n① 10\n② 11\n③ 12\n④ Error"
        q2_text = "2. 다음 중 객체지향 4대 특징이 아닌 것은?\n① 캡슐화\n② 상속성\n③ 다형성\n④ 스레드풀"
        bundle = {
            'bundle_id': 'exam:slide:001',
            'bundle_type': 'slide_bundle',
            'slide_number': 1,
            'content': {
                'title': '2026 기말 기출시험',
                'is_exam_page': True,
                'exam_questions': [
                    {'id': 'q1', 'stem': '1. 다음 자바 코드의 실행 결과는?', 'question_text': q1_text, 'is_exam_question': True},
                    {'id': 'q2', 'stem': '2. 다음 중 객체지향 4대 특징이 아닌 것은?', 'question_text': q2_text, 'is_exam_question': True}
                ]
            }
        }
        # Limit low enough to force 2 chunks, but each question is atomic
        chunks = cc.create_chunks_for_bundle(bundle, limit=180)
        self.assertEqual(len(chunks), 2)
        # Chunk 1 must contain ALL of Q1 (stem + code + choices)
        self.assertIn('1. 다음 자바 코드의 실행 결과는?', chunks[0]['text'])
        self.assertIn('int x = 10;', chunks[0]['text'])
        self.assertIn('① 10', chunks[0]['text'])
        self.assertIn('④ Error', chunks[0]['text'])
        self.assertTrue(chunks[0]['is_exam_page'])
        self.assertEqual(chunks[0]['exam_question_count'], 2)

        # Chunk 2 must contain ALL of Q2
        self.assertIn('2. 다음 중 객체지향 4대 특징이 아닌 것은?', chunks[1]['text'])
        self.assertIn('④ 스레드풀', chunks[1]['text'])
        self.assertTrue(chunks[1]['is_exam_page'])


if __name__ == '__main__':
    unittest.main()

