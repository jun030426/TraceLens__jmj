"""Unit tests for Multimodal Data Integration and Bundling (Step 5)."""
import json
import tempfile
import unittest
from pathlib import Path
from video_extraction.pipeline import data_integration as di
from video_extraction.shared.common import save, read, jsonl, digest_file


class TestDataIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_slide_bundle_text_ordering_and_title(self):
        records = [
            {
                'id': 'src:visual:0:b2',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'source_file': 'lecture1.pptx',
                'unit_id': 'src:visual:0',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '두 번째 설명 문장입니다.',
                'bbox': [300, 100, 400, 800],
                'eligible_for_chunking': True,
                'judgment': 'verified'
            },
            {
                'id': 'src:visual:0:b1',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'source_file': 'lecture1.pptx',
                'unit_id': 'src:visual:0',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '제1장: 객체지향 기초',
                'bbox': [50, 100, 150, 800],
                'eligible_for_chunking': True,
                'judgment': 'verified'
            }
        ]
        bundles = di.integrate_records(records)
        self.assertEqual(len(bundles), 1)
        b = bundles[0]
        self.assertEqual(b['bundle_type'], 'slide_bundle')
        self.assertEqual(b['slide_number'], 1)
        self.assertEqual(b['content']['title'], '제1장: 객체지향 기초')
        self.assertEqual(b['content']['text_blocks'][0]['text'], '제1장: 객체지향 기초')
        self.assertEqual(b['content']['text_blocks'][1]['text'], '두 번째 설명 문장입니다.')
        self.assertIn('제1장: 객체지향 기초\n\n두 번째 설명 문장입니다.', b['content']['base_text'])

    def test_handwriting_emphasis_and_keyword_extraction(self):
        records = [
            {
                'id': 'src:visual:6:b19',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'unit_id': 'src:visual:6',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 7},
                'observed_text': '1조5429억',
                'bbox': [869, 343, 945, 372],
                'eligible_for_chunking': True,
                'judgment': 'source_rechecked'
            },
            {
                'id': 'src:visual:6:b20',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'unit_id': 'src:visual:6',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 7},
                'observed_text': 'COVID-19 유행 시나리오에 따라',
                'bbox': [500, 200, 550, 700],
                'eligible_for_chunking': True,
                'judgment': 'source_rechecked'
            },
            {
                'id': 'src:visual:6:v3',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'unit_id': 'src:visual:6',
                'modality': 'handwriting',
                'kind': 'annotation',
                'location': {'page': 7},
                'observed_text': '',
                'description': '1조5429억 텍스트 주위를 강조하여 둘러싼 빨간색 타원형 강조 표시',
                'related_record_ids': ['src:visual:6:b19'],
                'bbox': [860, 335, 955, 380],
                'eligible_for_chunking': True,
                'judgment': 'source_rechecked'
            },
            {
                'id': 'src:visual:6:v4',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'unit_id': 'src:visual:6',
                'modality': 'handwriting',
                'kind': 'annotation',
                'location': {'page': 7},
                'observed_text': '',
                'description': "'COVID-19 유행 시나리오에 따라' 텍스트 부분에 칠해진 노란색 형광펜 하이라이트",
                'related_record_ids': ['src:visual:6:b20'],
                'bbox': [500, 200, 550, 700],
                'eligible_for_chunking': True,
                'judgment': 'source_rechecked'
            },
            {
                'id': 'src:visual:6:v5',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'unit_id': 'src:visual:6',
                'modality': 'handwriting',
                'kind': 'handwriting',
                'location': {'page': 7},
                'observed_text': '예산 증액 검토 요망',
                'description': '우측 상단 여백에 기재된 손글씨 메모',
                'related_record_ids': [],
                'bbox': [100, 700, 150, 950],
                'eligible_for_chunking': True,
                'judgment': 'source_rechecked'
            }
        ]
        bundles = di.integrate_records(records)
        self.assertEqual(len(bundles), 1)
        b = bundles[0]
        self.assertEqual(b['slide_number'], 7)

        # Check emphasized keywords
        self.assertIn('1조5429억', b['content']['emphasized_keywords'])
        self.assertIn('COVID-19 유행 시나리오에 따라', b['content']['emphasized_keywords'])
        self.assertIn('예산 증액 검토 요망', b['content']['emphasized_keywords'])

        # Check text block emphasis
        target_b19 = next(blk for blk in b['content']['text_blocks'] if blk['id'] == 'src:visual:6:b19')
        self.assertEqual(len(target_b19['emphasis']), 1)
        self.assertEqual(target_b19['emphasis'][0]['type'], 'circle')

        target_b20 = next(blk for blk in b['content']['text_blocks'] if blk['id'] == 'src:visual:6:b20')
        self.assertEqual(len(target_b20['emphasis']), 1)
        self.assertEqual(target_b20['emphasis'][0]['type'], 'highlight')

        # Check handwritten text additions
        self.assertEqual(len(b['content']['handwritten_text_additions']), 1)
        self.assertEqual(b['content']['handwritten_text_additions'][0]['text'], '예산 증액 검토 요망')
        self.assertIn('예산 증액 검토 요망', b['content']['base_text'])

    def test_table_and_diagram_multimodal_incorporation(self):
        records = [
            {
                'id': 'src:visual:3:b1',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 4},
                'observed_text': '제어문 비교표',
                'bbox': [50, 50, 100, 300],
                'eligible_for_chunking': True
            },
            {
                'id': 'src:visual:3:t1',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'modality': 'document',
                'kind': 'table',
                'location': {'page': 4},
                'observed_text': '| 역할 | 설명 |\n| --- | --- |\n| 실행 흐름 변경 | 프로그램의 실행 순서를 변경한다. |',
                'table_rows': [['역할', '설명'], ['실행 흐름 변경', '프로그램의 실행 순서를 변경한다.']],
                'eligible_for_chunking': True
            },
            {
                'id': 'src:visual:3:d1',
                'source_id': 'src1',
                'source_sha256': 'src1',
                'modality': 'image',
                'kind': 'diagram',
                'location': {'page': 4},
                'description': '반복문 루프 제어 흐름 다이어그램',
                'bbox': [400, 100, 800, 900],
                'eligible_for_chunking': True
            }
        ]
        bundles = di.integrate_records(records)
        self.assertEqual(len(bundles), 1)
        b = bundles[0]
        self.assertEqual(len(b['content']['tables']), 1)
        self.assertEqual(b['content']['tables'][0]['rows'][0], ['역할', '설명'])
        self.assertEqual(len(b['content']['diagrams']), 1)
        self.assertIn('흐름 다이어그램', b['content']['diagrams'][0]['description'])

    def test_speech_audio_temporal_overlap_and_orphan_handling(self):
        units = [
            {
                'id': 'u1',
                'source_id': 'src_video',
                'modality': 'visual',
                'location': {'page': 1},
                'time_seconds': 10.0
            },
            {
                'id': 'u2',
                'source_id': 'src_video',
                'modality': 'visual',
                'location': {'page': 2},
                'time_seconds': 40.0
            }
        ]
        records = [
            {
                'id': 'src_video:visual:0:text',
                'source_id': 'src_video',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '슬라이드 1 본문',
                'eligible_for_chunking': True
            },
            {
                'id': 'src_video:visual:1:text',
                'source_id': 'src_video',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 2},
                'observed_text': '슬라이드 2 본문',
                'eligible_for_chunking': True
            },
            # Speech 1: overlaps slide 1 (10s ~ 40s)
            {
                'id': 'sp1',
                'source_id': 'src_video',
                'modality': 'audio',
                'kind': 'speech',
                'start_seconds': 15.0,
                'end_seconds': 25.0,
                'observed_text': '첫 번째 슬라이드에 대해 설명드리겠습니다.',
                'eligible_for_chunking': True
            },
            # Speech 2: overlaps slide 2 (40s ~ 70s)
            {
                'id': 'sp2',
                'source_id': 'src_video',
                'modality': 'audio',
                'kind': 'speech',
                'start_seconds': 45.0,
                'end_seconds': 55.0,
                'observed_text': '두 번째 슬라이드의 핵심 내용은 이것입니다.',
                'eligible_for_chunking': True
            },
            # Speech 3: orphan audio segment (120s ~ 130s)
            {
                'id': 'sp3',
                'source_id': 'src_video',
                'modality': 'audio',
                'kind': 'speech',
                'start_seconds': 120.0,
                'end_seconds': 130.0,
                'observed_text': '오늘 강의는 여기서 마무리하겠습니다.',
                'eligible_for_chunking': True
            }
        ]
        bundles = di.integrate_records(records, units=units)
        self.assertEqual(len(bundles), 3)

        s1 = next(b for b in bundles if b['slide_number'] == 1)
        self.assertIn('첫 번째 슬라이드에 대해 설명드리겠습니다.', s1['content']['speech']['transcript'])
        self.assertEqual(len(s1['content']['speech']['segments']), 1)

        s2 = next(b for b in bundles if b['slide_number'] == 2)
        self.assertIn('두 번째 슬라이드의 핵심 내용은 이것입니다.', s2['content']['speech']['transcript'])
        self.assertEqual(len(s2['content']['speech']['segments']), 1)

        orphan = next(b for b in bundles if b['bundle_type'] == 'audio_segment')
        self.assertEqual(orphan['time_interval']['start_seconds'], 120.0)
        self.assertEqual(orphan['time_interval']['end_seconds'], 130.0)
        self.assertIn('오늘 강의는 여기서 마무리하겠습니다.', orphan['content']['base_text'])

    def test_code_corpus_and_symbol_cross_referencing(self):
        records = [
            {
                'id': 's1_txt',
                'source_id': 'deck',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '학생 성적 처리를 위해 calculateGrade 함수를 구현합니다.',
                'eligible_for_chunking': True
            }
        ]
        code_corpus = {
            'chunks': [
                {
                    'id': 'code_calc',
                    'language': 'python',
                    'title': 'grade.py · calculateGrade',
                    'symbol_name': 'calculateGrade',
                    'source_file': '/path/grade.py',
                    'source_sha256': 'code_sha',
                    'code_text': 'def calculateGrade(score):\n    return "A" if score >= 90 else "B"',
                    'concept_candidates': [{'concept': 'GradeCalculation', 'confidence': 'high'}],
                    'slide_number': None
                },
                {
                    'id': 'code_standalone',
                    'language': 'python',
                    'title': 'util.py · helper',
                    'symbol_name': 'helper',
                    'source_file': '/path/util.py',
                    'source_sha256': 'code_sha2',
                    'code_text': 'def helper():\n    pass',
                    'concept_candidates': [],
                    'slide_number': None
                }
            ]
        }
        bundles = di.integrate_records(records, code_corpus=code_corpus)
        self.assertEqual(len(bundles), 2)

        slide_b = next(b for b in bundles if b['bundle_type'] == 'slide_bundle')
        self.assertEqual(len(slide_b['content']['code_snippets']), 1)
        self.assertEqual(slide_b['content']['code_snippets'][0]['symbol_name'], 'calculateGrade')
        self.assertIn('GradeCalculation', [c['concept'] for c in slide_b['concept_metadata']['concept_candidates']])

        code_b = next(b for b in bundles if b['bundle_type'] == 'code_module')
        self.assertIn('util.py', code_b['source_file'])
        self.assertEqual(code_b['content']['code_snippets'][0]['symbol_name'], 'helper')

    def test_direction_a_low_impact_warning_provenance(self):
        records = [
            {
                'id': 'low1',
                'source_id': 'deck',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '스택의 원리',
                'eligible_for_chunking': True,
                'judgment': 'accepted_with_low_impact_warning',
                'warnings': ['low_impact_warning_accepted', 'minor_discrepancy']
            }
        ]
        bundles = di.integrate_records(records)
        self.assertEqual(len(bundles), 1)
        b = bundles[0]
        self.assertTrue(b['provenance']['has_low_impact_warnings'])
        self.assertIn('low_impact_warning_accepted', b['provenance']['warnings'])
        self.assertEqual(b['concept_metadata']['status'], 'ready_for_step6')

    def test_end_to_end_directory_bundling(self):
        # Create mock output directory structure
        out_dir = self.root / 'outputs/test-pipeline'
        rev_dir = out_dir / 'revisions/abc123'
        rev_dir.mkdir(parents=True)

        records = [
            {
                'id': 'r1',
                'source_id': 's1',
                'source_sha256': 'sha_s1',
                'source_file': 'lecture.pptx',
                'modality': 'document',
                'kind': 'text',
                'location': {'page': 1},
                'observed_text': '자료구조 1주차',
                'eligible_for_chunking': True
            }
        ]
        usable_path = rev_dir / 'usable-records.jsonl'
        jsonl(usable_path, records)

        latest = {
            'manifest': str(rev_dir / 'manifest.json'),
            'records': str(rev_dir / 'records.jsonl'),
            'usable_records': str(usable_path),
            'pending': str(rev_dir / 'pending.jsonl')
        }
        save(out_dir / 'latest.json', latest)
        save(out_dir / 'plan.json', {'source_plan': {'units': []}})

        summary, bundles = di.bundle_directory(out_dir)
        self.assertEqual(summary['total_bundles'], 1)
        self.assertEqual(summary['slide_bundles'], 1)
        self.assertEqual(summary['bundles_with_low_impact_warnings'], 0)

        # Check files created
        bundles_file = Path(summary['bundle_file'])
        self.assertTrue(bundles_file.exists())
        self.assertTrue((out_dir / 'bundles-summary.json').exists())

        # Check updated latest.json
        updated_latest = read(out_dir / 'latest.json')
        self.assertEqual(updated_latest['multimodal_bundles'], str(bundles_file))

        # Idempotency check: running again produces same hash
        summary2, _ = di.bundle_directory(out_dir)
        self.assertEqual(summary['bundle_sha256'], summary2['bundle_sha256'])


if __name__ == '__main__':
    unittest.main()

