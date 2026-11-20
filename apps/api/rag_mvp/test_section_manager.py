"""Unit tests for Course & Section Multi-Tenancy Manager.

Verifies:
1. Method 1 (Physical Directory Provisioning):
   Dynamic creation of isolated directories per course section.
2. Method 2 (Logical Metadata Tagging & Enforcement):
   Tagging every chunk with course_id and section_id.
3. 100% Leak-Proof Isolation:
   Queries in Section 1 (e.g. Data Structures 1) never retrieve chunks from Section 2 (e.g. Java 2).
"""
import tempfile
import unittest
from pathlib import Path

from rag_mvp.section_manager import CourseSectionManager
from video_extraction.shared.common import save, signature


class TestCourseSectionManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.mgr = CourseSectionManager(base_dir=self.base_dir)

        # 1. Source Corpus A: Data Structures (Stack & Queue)
        self.ds_chunks = [
            {
                'id': 'ds_01',
                'title': '스택의 LIFO 원리',
                'slide_number': 1,
                'text': '## 스택의 LIFO 원리\n스택은 후입선출(LIFO) 구조입니다. push와 pop 연산이 핵심입니다.',
                'concept_ids': ['data_structures.stack'],
                'emphasized_keywords': ['LIFO', '스택']
            }
        ]
        self.ds_corpus = {
            'version': 1,
            'signature': signature({'version': 1, 'chunks': self.ds_chunks}),
            'chunks': self.ds_chunks,
            'concept_index': {'data_structures.stack': ['ds_01']}
        }
        self.ds_source_file = self.base_dir / 'source_ds_corpus.json'
        save(self.ds_source_file, self.ds_corpus)

        # 2. Source Corpus B: Java OOP (Polymorphism & Overriding)
        self.java_chunks = [
            {
                'id': 'java_01',
                'title': '객체지향 다형성',
                'slide_number': 1,
                'text': '## 객체지향 다형성\n자바 다형성이란 부모 타입으로 자식 객체를 다루는 기술입니다.',
                'concept_ids': ['oop.polymorphism'],
                'emphasized_keywords': ['다형성', '오버라이딩']
            }
        ]
        self.java_corpus = {
            'version': 1,
            'signature': signature({'version': 1, 'chunks': self.java_chunks}),
            'chunks': self.java_chunks,
            'concept_index': {'oop.polymorphism': ['java_01']}
        }
        self.java_source_file = self.base_dir / 'source_java_corpus.json'
        save(self.java_source_file, self.java_corpus)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_method1_physical_directory_provisioning(self):
        # Section directory dynamically created when professor creates section
        meta = self.mgr.create_section(
            course_id='cs101',
            section_id='sec01',
            course_name='자료구조',
            section_name='1분반',
            professor_id='prof_kim'
        )
        sec_dir = self.mgr.get_section_dir('cs101', 'sec01')
        self.assertTrue(sec_dir.exists())
        self.assertTrue((sec_dir / 'section_meta.json').exists())
        self.assertEqual(meta['course_name'], '자료구조')
        self.assertEqual(meta['section_name'], '1분반')

    def test_method2_logical_metadata_tagging(self):
        # Ingesting corpus into section tags all chunks with section IDs
        dest, corpus = self.mgr.ingest_corpus_to_section(
            course_id='cs101',
            section_id='sec01',
            source_corpus_or_dir=self.ds_source_file,
            course_name='자료구조',
            section_name='1분반'
        )
        self.assertTrue(dest.exists())
        self.assertEqual(len(corpus['chunks']), 1)
        chunk = corpus['chunks'][0]
        self.assertEqual(chunk['course_id'], 'cs101')
        self.assertEqual(chunk['section_id'], 'sec01')
        self.assertEqual(chunk['course_name'], '자료구조')
        self.assertEqual(chunk['section_name'], '1분반')

    def test_strict_cross_section_leak_prevention(self):
        # Provision Section 1: CS101 Sec01 (Data Structures 1)
        self.mgr.create_section('cs101', 'sec01', course_name='자료구조', section_name='1분반')
        self.mgr.ingest_corpus_to_section('cs101', 'sec01', self.ds_source_file)

        # Provision Section 2: JAVA102 Sec02 (Java OOP 2)
        self.mgr.create_section('java102', 'sec02', course_name='자바프로그래밍', section_name='2분반')
        self.mgr.ingest_corpus_to_section('java102', 'sec02', self.java_source_file)

        # 1. RAG for Section 1 (Data Structures 1)
        rag_sec1 = self.mgr.get_section_rag('cs101', 'sec01')

        # Query "스택" in Section 1 -> SUCCESS
        hits_stack_s1 = rag_sec1.retrieve('스택')
        self.assertEqual(len(hits_stack_s1), 1)
        self.assertEqual(hits_stack_s1[0]['id'], 'ds_01')

        # Query "다형성" in Section 1 -> MUST BE 0 (No leak from Java 2 Section!)
        hits_poly_s1 = rag_sec1.retrieve('다형성')
        self.assertEqual(len(hits_poly_s1), 0)

        # 2. RAG for Section 2 (Java 2)
        rag_sec2 = self.mgr.get_section_rag('java102', 'sec02')

        # Query "다형성" in Section 2 -> SUCCESS
        hits_poly_s2 = rag_sec2.retrieve('다형성')
        self.assertEqual(len(hits_poly_s2), 1)
        self.assertEqual(hits_poly_s2[0]['id'], 'java_01')

        # Query "스택" in Section 2 -> MUST BE 0 (No leak from DS 1 Section!)
        hits_stack_s2 = rag_sec2.retrieve('스택')
        self.assertEqual(len(hits_stack_s2), 0)

    def test_downstream_quiz_and_chat_isolation(self):
        # Section 1 has only Data Structures
        self.mgr.create_section('cs101', 'sec01', course_name='자료구조', section_name='1분반')
        self.mgr.ingest_corpus_to_section('cs101', 'sec01', self.ds_source_file)
        rag_sec1 = self.mgr.get_section_rag('cs101', 'sec01')

        # Chatbot in Section 1: "스택" question answers with Section 1 citation
        chat_ok = rag_sec1.ask_chat('스택이란 무엇인가요?')
        self.assertTrue(chat_ok['answerable'])
        self.assertIn('스택', chat_ok['reply'])

        # Chatbot in Section 1: "다형성" question must abstain!
        chat_abstain = rag_sec1.ask_chat('다형성이 무엇인가요?')
        self.assertFalse(chat_abstain['answerable'])

        # Quiz in Section 1: "다형성" quiz generation must fail gracefully
        quiz_poly = rag_sec1.generate_quiz('다형성')
        self.assertFalse(quiz_poly['success'])


if __name__ == '__main__':
    unittest.main()
