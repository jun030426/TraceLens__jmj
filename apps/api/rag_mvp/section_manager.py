"""Course & Section Multi-Tenancy Manager.

Implements two-tier multi-section isolation:
1. Physical Partitioning (Method 1):
   Dynamically creates dedicated directory for each section under outputs/courses/{course_id}_{section_id}/
2. Logical Metadata Tagging & Enforcement (Method 2):
   Tags every chunk with course_id, section_id, course_name, section_name, professor_id
   and strictly filters out other sections during retrieval.
"""
import copy
import json
import re
from pathlib import Path

from video_extraction.shared.common import read, save, signature, now
from .corpus import load_corpus
from .unified_rag import UnifiedMultimodalRAG

DEFAULT_COURSES_ROOT = Path("outputs/courses")


class CourseSectionManager:
    """Manages course sections, physical directory provisioning, and data ingestion."""

    def __init__(self, base_dir=DEFAULT_COURSES_ROOT):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_id(self, text):
        return re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', (text or '').strip())

    def get_section_dir(self, course_id, section_id):
        safe_course = self._safe_id(course_id)
        safe_section = self._safe_id(section_id)
        return self.base_dir / f"{safe_course}_{safe_section}"

    def create_section(self, course_id, section_id, course_name=None, section_name=None, professor_id=None):
        """Method 1 (Physical): Dynamically create section directory and meta file."""
        folder = self.get_section_dir(course_id, section_id)
        folder.mkdir(parents=True, exist_ok=True)

        meta = {
            'course_id': course_id,
            'section_id': section_id,
            'course_name': course_name or course_id,
            'section_name': section_name or section_id,
            'professor_id': professor_id or 'prof_default',
            'created_at': now(),
            'folder': str(folder),
            'status': 'active'
        }
        save(folder / 'section_meta.json', meta)
        return meta

    def ingest_corpus_to_section(self, course_id, section_id, source_corpus_or_dir, course_name=None, section_name=None):
        """Method 2 (Logical): Tag all chunks with section metadata and save in section directory."""
        folder = self.get_section_dir(course_id, section_id)
        if not folder.exists() or not (folder / 'section_meta.json').exists():
            self.create_section(course_id, section_id, course_name=course_name, section_name=section_name)

        meta = read(folder / 'section_meta.json')
        if course_name and meta.get('course_name') != course_name:
            meta['course_name'] = course_name
            save(folder / 'section_meta.json', meta)
        if section_name and meta.get('section_name') != section_name:
            meta['section_name'] = section_name
            save(folder / 'section_meta.json', meta)

        source_p = Path(source_corpus_or_dir).resolve()
        if source_p.is_dir():
            corpus_file = source_p / 'corpus.json'
            if not corpus_file.exists():
                candidates = list(source_p.glob('revisions/*/corpus.json'))
                if candidates:
                    corpus_file = candidates[-1]
                else:
                    raise FileNotFoundError(f"corpus.json not found in {source_p}")
        else:
            corpus_file = source_p

        raw_corpus = read(corpus_file)
        tagged_chunks = copy.deepcopy(raw_corpus['chunks'])

        # Method 2: Logical metadata tagging on every single chunk
        for c in tagged_chunks:
            c['course_id'] = course_id
            c['section_id'] = section_id
            c['course_name'] = meta.get('course_name', course_id)
            c['section_name'] = meta.get('section_name', section_id)
            c['professor_id'] = meta.get('professor_id', '')

        # Calculate new signature
        new_sig = signature({'version': 1, 'chunks': tagged_chunks})

        section_corpus = {
            'version': 1,
            'signature': new_sig,
            'course_id': course_id,
            'section_id': section_id,
            'course_name': meta.get('course_name'),
            'section_name': meta.get('section_name'),
            'professor_id': meta.get('professor_id'),
            'chunks': tagged_chunks,
            'concept_index': raw_corpus.get('concept_index', {}),
            'stats': {
                'total_chunks': len(tagged_chunks),
                'ingested_from': str(corpus_file),
                'ingested_at': now()
            }
        }

        dest_corpus = folder / 'corpus.json'
        save(dest_corpus, section_corpus)
        return dest_corpus, section_corpus

    def list_sections(self):
        """List all registered sections and their statistics."""
        sections = []
        for meta_file in sorted(self.base_dir.glob('*/section_meta.json')):
            meta = read(meta_file)
            corpus_file = meta_file.parent / 'corpus.json'
            chunk_count = 0
            if corpus_file.exists():
                try:
                    c = read(corpus_file)
                    chunk_count = len(c.get('chunks', []))
                except Exception:
                    pass
            meta['chunk_count'] = chunk_count
            meta['has_corpus'] = corpus_file.exists()
            sections.append(meta)
        return sections

    def get_section_rag(self, course_id, section_id, client=None):
        """Get an isolated UnifiedMultimodalRAG instance dedicated to this section."""
        folder = self.get_section_dir(course_id, section_id)
        if not folder.exists() or not (folder / 'corpus.json').exists():
            raise FileNotFoundError(f"Section {course_id}-{section_id} not initialized with corpus at {folder}")

        meta = read(folder / 'section_meta.json') if (folder / 'section_meta.json').exists() else {}
        return UnifiedMultimodalRAG(
            output_dir=folder,
            client=client,
            course_id=course_id,
            section_id=section_id,
            course_name=meta.get('course_name'),
            section_name=meta.get('section_name')
        )
