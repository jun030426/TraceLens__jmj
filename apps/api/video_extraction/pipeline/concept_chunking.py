"""Automatic Concept Mapping and Multimodal Chunking (Step 6).

Transforms multimodal bundles (from Step 5: data_integration) into retrieval-ready
chunks and maps canonical educational concept IDs.

Key Capabilities:
1. Concept Extraction & Mapping:
   - High-priority extraction from handwriting emphasis (emphasized_keywords).
   - AST syntactic concepts from code snippets (concept_candidates).
   - Slide titles, headings, and spoken terminology from speech transcripts.
   - Canonical mapping into a hierarchical concept taxonomy.
2. Multimodal Chunking:
   - Formats complete slide context (slide text, emphasized keywords, teacher speech, code).
   - Keeps standard slides intact (1 Slide = 1 Chunk) to preserve instructional context.
   - Losslessly partitions oversized slides on markdown block boundaries.
3. RAG Corpus & Concept Index:
   - Inverted concept index: concept_id -> [chunk_ids].
   - Deterministic corpus.json generation compatible with rag_mvp.

Policy: multimodal_concept_chunker_v1
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from video_extraction.shared.common import read, save, jsonl, signature, digest_file

CHUNK_POLICY = "multimodal_concept_chunker_v1"
DEFAULT_CHUNK_LIMIT = 1800

# Built-in Canonical Concept Taxonomy (Hierarchical)
# Extensible with domain-specific terms
CONCEPT_TAXONOMY = {
    # Programming & Control Flow
    'programming.control_flow.iteration': {
        'name': '반복문 (Iteration / Loop)',
        'keywords': ['반복문', '루프', 'for', 'while', 'do-while', 'loop', 'iteration', '반복 제어']
    },
    'programming.control_flow.break': {
        'name': 'break문 (Break Statement)',
        'keywords': ['break', 'break문', '루프 탈출', '반복문 종료']
    },
    'programming.control_flow.continue': {
        'name': 'continue문 (Continue Statement)',
        'keywords': ['continue', 'continue문', '다음 반복']
    },
    'programming.control_flow.condition': {
        'name': '조건문 (Condition / Branching)',
        'keywords': ['조건문', 'if', 'else', 'switch', 'case', 'branch', '분기']
    },
    # Data Structures
    'data_structures.array': {
        'name': '배열 (Array)',
        'keywords': ['배열', 'array', '인덱스', 'index', '배열 크기']
    },
    'data_structures.list': {
        'name': '리스트 (List)',
        'keywords': ['리스트', 'list', 'linked list', '연결 리스트', '동적 배열']
    },
    'data_structures.stack': {
        'name': '스택 (Stack)',
        'keywords': ['스택', 'stack', 'push', 'pop', 'lifo', '후입선출']
    },
    'data_structures.queue': {
        'name': '큐 (Queue)',
        'keywords': ['큐', 'queue', 'enqueue', 'dequeue', 'fifo', '선입선출']
    },
    'data_structures.tree': {
        'name': '트리 (Tree)',
        'keywords': ['트리', 'tree', '이진 트리', 'binary tree', 'root', 'node', '노드']
    },
    'data_structures.graph': {
        'name': '그래프 (Graph)',
        'keywords': ['그래프', 'graph', '간선', '정점', 'vertex', 'edge']
    },
    # Object-Oriented Programming (OOP)
    'oop.class': {
        'name': '클래스 (Class)',
        'keywords': ['클래스', 'class', '객체', 'object', '인스턴스', 'instance']
    },
    'oop.method': {
        'name': '메서드 (Method / Function)',
        'keywords': ['메서드', 'method', '함수', 'function', '반환값', '매개변수', 'parameter']
    },
    'oop.inheritance': {
        'name': '상속 (Inheritance)',
        'keywords': ['상속', 'inheritance', 'extends', 'super', '부모 클래스', '자식 클래스']
    },
    'oop.polymorphism': {
        'name': '다형성 (Polymorphism)',
        'keywords': ['다형성', 'polymorphism', '오버라이딩', 'overriding', '오버로딩', 'overloading']
    },
    'oop.encapsulation': {
        'name': '캡슐화 (Encapsulation)',
        'keywords': ['캡슐화', 'encapsulation', '정보은닉', 'private', 'public', 'getter', 'setter']
    },
    # Technology & Domain Concepts (XR, Metaverse, Web)
    'xr_domain.market': {
        'name': 'XR 시장 및 산업 규모 (XR Market Size)',
        'keywords': ['xr', 'xr 시장', '시장규모', '시장 규모', '1조5429억', '연평균 성장']
    },
    'xr_domain.metaverse': {
        'name': '메타버스 플랫폼 (Metaverse Platform)',
        'keywords': ['메타버스', 'metaverse', '제페토', 'zepeto', '가상공간', '아바타']
    },
    'xr_domain.web3d': {
        'name': 'Web3D 및 웹 전시기술 (Web3D & Web Exhibition)',
        'keywords': ['web3d', '온라인 전시', '웹 기반', '설치 없이', 'webgl']
    },
    'xr_domain.3d_modeling': {
        'name': '3D 모델링 폴리곤 (3D Polygon Modeling)',
        'keywords': ['로우 폴리곤', '하이 폴리곤', 'low polygon', 'high polygon', '폴리곤', 'mesh']
    }
}


def _clean(s):
    return (s or "").strip()


def extract_keywords_from_text(text):
    """Extract candidate keywords (Korean nouns, English code identifiers, CamelCase)."""
    if not text:
        return []
    keywords = set()

    # 1. English identifiers and CamelCase/PascalCase (e.g. calculateGrade, StudentId, for, while)
    en_words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{1,30}\b', text)
    for w in en_words:
        if len(w) >= 2:
            keywords.add(w)

    # 2. Korean nouns and compound technical terms (2 to 15 chars)
    # Exclude common grammatical endings
    ko_words = re.findall(r'[가-힣0-9]{2,15}', text)
    stop_stems = {'합니다', '입니다', '있습니다', '없습니다', '통하여', '대하여', '그리고', '하지만', '때문에', '경우에', '우리가'}
    for w in ko_words:
        if w not in stop_stems and not w.endswith(('하다', '되다', '이다', '했다', '된다')):
            keywords.add(w)

    return sorted(keywords)


def map_concepts_for_bundle(bundle, extra_taxonomy=None):
    """Extract concept candidates from a bundle and map to canonical concept IDs.

    Returns:
      mapped_concept_ids: list of canonical concept IDs
      detailed_candidates: list of candidate dicts with basis and confidence
    """
    taxonomy = dict(CONCEPT_TAXONOMY)
    if extra_taxonomy:
        taxonomy.update(extra_taxonomy)

    content = bundle.get('content') or {}
    emp_keywords = content.get('emphasized_keywords') or []
    title = content.get('title') or ""
    base_text = content.get('base_text') or ""
    speech_transcript = (content.get('speech') or {}).get('transcript') or ""
    code_snippets = content.get('code_snippets') or []
    existing_candidates = bundle.get('concept_metadata', {}).get('concept_candidates', [])

    candidate_evidence = {}  # term -> list of evidence bases

    # Evidence 1: Handwriting Emphasis (Highest priority)
    for kw in emp_keywords:
        kw_clean = _clean(kw)
        if kw_clean:
            candidate_evidence.setdefault(kw_clean, []).append('handwriting_emphasis')
            for sub in extract_keywords_from_text(kw_clean):
                candidate_evidence.setdefault(sub, []).append('handwriting_emphasis_subterm')

    # Evidence 2: Slide Title
    if title:
        candidate_evidence.setdefault(title, []).append('slide_title')
        for sub in extract_keywords_from_text(title):
            candidate_evidence.setdefault(sub, []).append('title_keyword')

    # Evidence 3: Code AST Candidates & Snippet Symbols
    for cand in existing_candidates:
        c_id = cand.get('concept') or cand.get('id')
        if c_id:
            candidate_evidence.setdefault(c_id, []).append('code_ast')

    for code_item in code_snippets:
        sym = code_item.get('symbol_name')
        if sym:
            candidate_evidence.setdefault(sym, []).append('code_symbol')
        lang = code_item.get('language')
        if lang:
            candidate_evidence.setdefault(f"programming.language.{lang.lower()}", []).append('code_language')

    # Evidence 4: Spoken Emphasis (Frequent or key technical terms in speech)
    if speech_transcript:
        speech_words = extract_keywords_from_text(speech_transcript)
        for w in speech_words:
            count = speech_transcript.count(w)
            if count >= 2:
                candidate_evidence.setdefault(w, []).append('speech_frequency')
            elif count >= 1 and w in base_text:
                candidate_evidence.setdefault(w, []).append('audiovisual_cooccurrence')

    # Evidence 5: Base Text keywords
    for w in extract_keywords_from_text(base_text):
        if w in candidate_evidence:
            candidate_evidence[w].append('base_text')

    # Map Candidate Evidence to Canonical Concept Taxonomy
    mapped_concept_ids = set()
    detailed_candidates = []

    # Direct match against taxonomy
    for concept_id, spec in taxonomy.items():
        spec_name = spec.get('name', concept_id)
        spec_keywords = spec.get('keywords', [])

        matched_bases = []
        for kw in spec_keywords:
            kw_lower = kw.lower()
            for cand_term, bases in candidate_evidence.items():
                cand_lower = cand_term.lower()
                if kw_lower == cand_lower or (len(kw_lower) >= 3 and (kw_lower in cand_lower or cand_lower in kw_lower)):
                    matched_bases.extend(bases)

        if matched_bases:
            mapped_concept_ids.add(concept_id)
            confidence = 'high' if ('handwriting_emphasis' in matched_bases or 'code_ast' in matched_bases or 'slide_title' in matched_bases) else 'medium'
            detailed_candidates.append({
                'concept_id': concept_id,
                'canonical_name': spec_name,
                'confidence': confidence,
                'basis': sorted(set(matched_bases))
            })

    # Also register candidates with strong evidence that are not in taxonomy
    for term, bases in candidate_evidence.items():
        if any(b in ('handwriting_emphasis', 'slide_title', 'code_symbol') for b in bases):
            detailed_candidates.append({
                'concept_id': f"unmapped.{term}",
                'canonical_name': term,
                'confidence': 'high' if 'handwriting_emphasis' in bases else 'medium',
                'basis': sorted(set(bases))
            })

    return sorted(mapped_concept_ids), detailed_candidates


def format_multimodal_chunk_text(bundle):
    """Format rich, cohesive retrieval text combining slide text, emphasis, speech, and code."""
    content = bundle.get('content') or {}
    title = content.get('title') or f"Slide {bundle.get('slide_number', '')}"
    page = bundle.get('page') or bundle.get('slide_number')
    page_str = f"슬라이드 {page}" if page is not None else "강의 자료"

    header = f"## {title} ({page_str})"

    sections = [header]

    # 1. Emphasized Keywords (High visual salience)
    emp_kws = content.get('emphasized_keywords') or []
    if emp_kws:
        sections.append(f"**[교수님 필기 강조 키워드]**: {', '.join(emp_kws)}")

    # 2. Base Slide Text
    base_text = _clean(content.get('base_text'))
    if base_text:
        sections.append(base_text)

    # 3. Tables
    tables = content.get('tables') or []
    for t in tables:
        md = _clean(t.get('markdown'))
        if md:
            sections.append(f"\n[표 데이터]\n{md}")

    # 4. Diagrams
    diagrams = content.get('diagrams') or []
    for d in diagrams:
        desc = _clean(d.get('description'))
        if desc:
            sections.append(f"[시각 자료/다이어그램]: {desc}")

    # 5. Teacher Speech Explanation (Contextual commentary)
    speech = content.get('speech') or {}
    transcript = _clean(speech.get('transcript'))
    if transcript:
        sections.append(f"\n**[강사 음성 해설]**:\n{transcript}")

    # 6. Code Snippets
    code_snippets = content.get('code_snippets') or []
    for cs in code_snippets:
        lang = cs.get('language') or ""
        sym = cs.get('symbol_name') or ""
        code = _clean(cs.get('code'))
        if code:
            title_part = f" · {sym}" if sym else ""
            sections.append(f"```{lang}\n# {cs.get('record_id', '')}{title_part}\n{code}\n```")

    return "\n\n".join(sections)


def partition_bundle_into_part_texts(bundle, limit=DEFAULT_CHUNK_LIMIT):
    """Safely partition a bundle into cohesive chunk texts without cutting code fences or sentences.

    Guarantees:
    1. Code blocks (```lang ... ```) are treated as indivisible atomic units.
    2. Header and emphasized keywords are propagated to every partition (context preservation).
    3. Paragraphs and long speech transcripts are partitioned on sentence boundaries without word cuts.
    """
    content = bundle.get('content') or {}
    title = content.get('title') or f"Slide {bundle.get('slide_number', '')}"
    page = bundle.get('page') or bundle.get('slide_number')
    page_str = f"슬라이드 {page}" if page is not None else "강의 자료"
    emp_kws = content.get('emphasized_keywords') or []
    emp_line = f"**[교수님 필기 강조 키워드]**: {', '.join(emp_kws)}" if emp_kws else ""

    items = []

    # Check if this bundle is an exam question set
    exam_questions = [q for q in (content.get('exam_questions') or []) if q.get('is_exam_question')]
    if exam_questions:
        # Pre-exam instructions or headers
        pre_instructions = [q['stem'] for q in content.get('exam_questions', []) if not q.get('is_exam_question') and q.get('stem')]
        if pre_instructions:
            items.extend(pre_instructions)
        # Keep each exam question set intact as an indivisible atomic item
        for eq in exam_questions:
            items.append(eq['question_text'])
    else:
        # 1. Base text: split into paragraphs (or sentences if an individual paragraph is huge)
        base_text = _clean(content.get('base_text'))
        if base_text:
            for p in base_text.split('\n\n'):
                p_clean = p.strip()
                if not p_clean:
                    continue
                if len(p_clean) > limit:
                    sentences = re.findall(r'[^.!?\n]+(?:[.!?\n]+|$)', p_clean)
                    cur_s = []
                    cur_len = 0
                    for s in sentences:
                        s_str = s.strip()
                        if not s_str:
                            continue
                        if cur_len + len(s_str) > limit and cur_s:
                            items.append(" ".join(cur_s))
                            cur_s = [s_str]
                            cur_len = len(s_str)
                        else:
                            cur_s.append(s_str)
                            cur_len += len(s_str)
                    if cur_s:
                        items.append(" ".join(cur_s))
                else:
                    items.append(p_clean)

    # 2. Tables
    for t in content.get('tables') or []:
        md = _clean(t.get('markdown'))
        if md:
            items.append(f"[표 데이터]\n{md}")

    # 3. Diagrams
    for d in content.get('diagrams') or []:
        desc = _clean(d.get('description'))
        if desc:
            items.append(f"[시각 자료/다이어그램]: {desc}")

    # 4. Speech transcript
    speech = content.get('speech') or {}
    transcript = _clean(speech.get('transcript'))
    if transcript:
        if len(transcript) > limit:
            sentences = re.findall(r'[^.!?\n]+(?:[.!?\n]+|$)', transcript)
            cur_s = []
            cur_len = 0
            for s in sentences:
                s_str = s.strip()
                if not s_str:
                    continue
                if cur_len + len(s_str) > limit and cur_s:
                    items.append(f"**[강사 음성 해설]**:\n{' '.join(cur_s)}")
                    cur_s = [s_str]
                    cur_len = len(s_str)
                else:
                    cur_s.append(s_str)
                    cur_len += len(s_str)
            if cur_s:
                items.append(f"**[강사 음성 해설]**:\n{' '.join(cur_s)}")
        else:
            items.append(f"**[강사 음성 해설]**:\n{transcript}")

    # 5. Code snippets (EACH CODE SNIPPET IS ATOMIC)
    for cs in content.get('code_snippets') or []:
        lang = cs.get('language') or ""
        sym = cs.get('symbol_name') or ""
        code = _clean(cs.get('code'))
        if code:
            title_part = f" · {sym}" if sym else ""
            items.append(f"```{lang}\n# {cs.get('record_id', '')}{title_part}\n{code}\n```")

    if not items:
        header = f"## {title} ({page_str})"
        return [header if not emp_line else f"{header}\n\n{emp_line}"]

    header_reserve = len(title) + len(page_str) + len(emp_line) + 60
    effective_limit = max(50, limit - header_reserve)

    groups = []
    current_group = []
    current_len = 0

    for it in items:
        it_len = len(it) + 2
        if current_len + it_len > effective_limit and current_group:
            groups.append(current_group)
            current_group = [it]
            current_len = it_len
        else:
            current_group.append(it)
            current_len += it_len
    if current_group:
        groups.append(current_group)

    total_parts = len(groups)
    part_texts = []
    for i, grp in enumerate(groups, 1):
        if total_parts == 1:
            part_header = f"## {title} ({page_str})"
        else:
            part_header = f"## {title} ({page_str} - Part {i}/{total_parts})"
        sec = [part_header]
        if emp_line:
            sec.append(emp_line)
        sec.extend(grp)
        part_texts.append("\n\n".join(sec))

    return part_texts


def extract_ds_metadata(chunk):
    """Extract specialized Data Structure & Algorithm metadata from a chunk."""
    title = (chunk.get('title') or '').lower()
    text = (chunk.get('text') or '').lower()
    concepts = [str(cid).lower() for cid in chunk.get('concept_ids') or []]
    emp_kws = [str(w).lower() for w in chunk.get('emphasized_keywords') or []]

    combined = f"{title} {text} {' '.join(concepts)} {' '.join(emp_kws)}"

    meta = {
        'data_structure': None,
        'operation': None,
        'algorithm_type': None,
        'algorithm_paradigm': None,
        'time_complexity': None,
        'space_complexity': None,
        'edge_cases': [],
        'implementation_style': None,
        'professor_analogy': None
    }

    ds_patterns = [
        ('stack', ['스택', 'stack', 'lifo', '후입선출', 'call stack', '콜 스택']),
        ('queue', ['원형 큐', '원형큐', 'circular queue', '큐', 'queue', 'deque', '덱', 'fifo', '선입선출']),
        ('linked_list', ['연결 리스트', '연결리스트', 'linked list', 'singly linked', 'doubly linked']),
        ('tree', ['이진 탐색 트리', '이진탐색트리', 'bst', '이진 트리', '트리', 'tree', 'binary tree']),
        ('heap', ['최대 힙', '최소 힙', '우선순위 큐', 'priority queue', 'heap', '힙']),
        ('hash_table', ['해시 테이블', '해시 맵', '해시맵', 'hash table', 'hashmap', 'hash', '해시']),
        ('graph', ['인접 행렬', '인접 리스트', '그래프', 'graph', '정점', '간선', 'vertex', 'edge', 'dfs', 'bfs']),
        ('recursion', ['재귀 함수', '재귀함수', '재귀', 'recursion', 'recursive']),
        ('sort', ['정렬', 'sort', 'quicksort', 'mergesort']),
        ('array', ['배열', 'array', '동적 배열'])
    ]

    for ds_name, keywords in ds_patterns:
        if any(k in title for k in keywords):
            meta['data_structure'] = ds_name
            break
    if not meta['data_structure']:
        for ds_name, keywords in ds_patterns:
            if any(k in concepts for k in keywords) or any(k in emp_kws for k in keywords):
                meta['data_structure'] = ds_name
                break
    if not meta['data_structure']:
        for ds_name, keywords in ds_patterns:
            if any(k in combined for k in keywords):
                meta['data_structure'] = ds_name
                break

    op_patterns = [
        ('peek', ['peek', '피크', 'top 조회', 'peek()']),
        ('is_empty', ['is_empty', 'isempty', '비어 있는지', '공백 상태']),
        ('is_full', ['is_full', 'isfull', '가득 찼는지', '포화 상태']),
        ('enqueue', ['enqueue', 'en_queue', '큐 삽입']),
        ('dequeue', ['dequeue', 'de_queue', '큐 삭제']),
        ('push', ['push', '삽입', '추가', 'push()']),
        ('pop', ['pop', '삭제', '추출', '제거', 'pop()']),
        ('traverse', ['순회', 'traverse', 'traversal', 'inorder', 'preorder', 'postorder']),
        ('search', ['탐색', '검색', 'search', 'find']),
        ('init', ['init', '초기화', 'create'])
    ]

    for op_name, keywords in op_patterns:
        if any(k in title for k in keywords):
            meta['operation'] = op_name
            break
    if not meta['operation']:
        for op_name, keywords in op_patterns:
            if any(k in combined for k in keywords):
                meta['operation'] = op_name
                break

    paradigm_patterns = [
        ('divide_and_conquer', ['분할 정복', '분할정복', 'divide and conquer']),
        ('dynamic_programming', ['동적 계획법', '동적계획법', 'dp', 'dynamic programming', '메모이제이션']),
        ('greedy', ['그리디', '탐욕', 'greedy']),
        ('backtracking', ['백트래킹', 'backtracking', '되추적', 'n-queen']),
        ('brute_force', ['완전 탐색', '완전탐색', 'brute force', '브루트포스']),
        ('two_pointers', ['투 포인터', '투포인터', 'two pointer', '슬라이딩 윈도우']),
        ('recursion', ['재귀', 'recursion', 'recursive'])
    ]
    for p_name, keywords in paradigm_patterns:
        if any(k in combined for k in keywords):
            meta['algorithm_paradigm'] = p_name
            break

    algo_patterns = [
        ('binary_search', ['이진 탐색', '이진탐색', 'binary search', '이분 탐색']),
        ('dfs', ['dfs', '깊이 우선 탐색', '깊이우선탐색']),
        ('bfs', ['bfs', '너비 우선 탐색', '너비우선탐색']),
        ('quick_sort', ['퀵 정렬', '퀵정렬', 'quicksort', 'quick sort']),
        ('merge_sort', ['병합 정렬', '병합정렬', '머지 정렬', 'mergesort']),
        ('heap_sort', ['힙 정렬', '힙정렬', 'heapsort']),
        ('bubble_sort', ['버블 정렬', '버블정렬', 'bubble sort']),
        ('insertion_sort', ['삽입 정렬', '삽입정렬', 'insertion sort']),
        ('selection_sort', ['선택 정렬', '선택정렬', 'selection sort']),
        ('dijkstra', ['다익스트라', 'dijkstra', '최단 경로']),
        ('mst', ['mst', '최소 신장 트리', 'kruskal', 'prim']),
        ('topological_sort', ['위상 정렬', '위상정렬', 'topological sort']),
        ('bracket_matching', ['괄호 검사', '괄호 매칭', '괄호 짝', 'bracket matching']),
        ('postfix_eval', ['후위 표기법', '후위표기법', 'postfix', '수식 계산']),
        ('maze_solving', ['미로 탐색', '미로찾기', 'maze', '미로'])
    ]
    for a_name, keywords in algo_patterns:
        if any(k in title for k in keywords):
            meta['algorithm_type'] = a_name
            break
    if not meta['algorithm_type']:
        for a_name, keywords in algo_patterns:
            if any(k in combined for k in keywords):
                meta['algorithm_type'] = a_name
                break

    comp_match = re.search(r'o\s*\(\s*(1|log\s*n|n\s*log\s*n|n\^2|n)\s*\)', combined)
    if comp_match:
        meta['time_complexity'] = f"O({comp_match.group(1).replace(' ', '').upper()})"
    elif meta['data_structure'] == 'stack' and meta['operation'] in ('push', 'pop', 'peek', 'is_empty', 'is_full'):
        meta['time_complexity'] = 'O(1)'
    elif meta['data_structure'] == 'queue' and meta['operation'] in ('enqueue', 'dequeue', 'peek', 'is_empty', 'is_full'):
        meta['time_complexity'] = 'O(1)'

    if meta['data_structure'] in ('stack', 'queue', 'linked_list', 'array', 'tree'):
        meta['space_complexity'] = 'O(N)'

    edge_cases = []
    if 'underflow' in combined or '언더플로우' in combined:
        edge_cases.append('underflow')
    if 'overflow' in combined or '오버플로우' in combined:
        edge_cases.append('overflow')
    if '비어' in combined or 'empty' in combined or meta['operation'] == 'is_empty':
        edge_cases.append('empty_check')
    if '가득' in combined or 'full' in combined or meta['operation'] == 'is_full':
        edge_cases.append('full_check')
    if 'null' in combined or 'none' in combined or '널 포인터' in combined:
        edge_cases.append('null_pointer')
    meta['edge_cases'] = sorted(set(edge_cases))

    if any(k in combined for k in ['포인터', 'pointer', 'node', '노드', '->', '.next']):
        meta['implementation_style'] = 'pointer_based'
    elif any(k in combined for k in ['배열로 구현', '배열 기반', 'array', '배열', 'stack[']):
        meta['implementation_style'] = 'array_based'

    # Professor Analogy Detection
    analogy_patterns = [
        ('프링글스 통', ['프링글스']),
        ('접시 쌓기', ['접시', '식판']),
        ('테니스공 통', ['테니스공', '테니스 공']),
        ('책 쌓기', ['책 쌓기', '쌓여있는 책']),
        ('뒤로가기/실행취소', ['뒤로가기', '뒤로 가기', 'ctrl+z', 'ctrl-z', '실행취소', '실행 취소']),
        ('줄서기/매표소', ['줄서기', '줄 서기', '매표소', '대기표', '은행 창구', '번호표']),
        ('터널/파이프', ['터널', '파이프']),
        ('기차 칸 연결', ['기차', '객차', '기차 칸']),
        ('손잡기 놀이', ['손잡기', '손을 잡고', '기차놀이']),
        ('가계도/조직도', ['가계도', '족보', '조직도']),
        ('마트료시카 인형', ['마트료시카', '러시아 인형'])
    ]
    for a_label, keywords in analogy_patterns:
        if any(k in combined for k in keywords):
            meta['professor_analogy'] = a_label
            break

    if not meta['professor_analogy']:
        match_analogy = re.search(r'([가-힣A-Za-z0-9\s]{2,15}?)(?:에|로)\s*비유', text)
        if match_analogy:
            meta['professor_analogy'] = match_analogy.group(1).strip()
        else:
            match_like = re.search(r'마치\s*([가-힣A-Za-z0-9\s]{2,15}?)(?:과|와|처럼)', text)
            if match_like:
                meta['professor_analogy'] = match_like.group(1).strip()

    return meta


def create_chunks_for_bundle(bundle, limit=DEFAULT_CHUNK_LIMIT, extra_taxonomy=None):
    """Create one or more retrieval chunks from a multimodal bundle.

    If the bundle text fits in limit, emits 1 cohesive chunk.
    If oversized, splits losslessly on semantic block boundaries with context preservation.
    """
    mapped_concept_ids, detailed_candidates = map_concepts_for_bundle(bundle, extra_taxonomy)

    bundle_id = bundle['bundle_id']
    parts = partition_bundle_into_part_texts(bundle, limit=limit)
    provenance = bundle.get('provenance') or {}
    time_interval = bundle.get('time_interval') or {}
    content = bundle.get('content') or {}
    title = content.get('title') or f"Slide {bundle.get('slide_number', '')}"
    is_exam_page = bool(content.get('is_exam_page'))
    exam_questions = content.get('exam_questions') or []
    exam_q_count = len([q for q in exam_questions if q.get('is_exam_question')])

    if len(parts) == 1:
        chunk = {
            'id': bundle_id,
            'bundle_id': bundle_id,
            'bundle_type': bundle.get('bundle_type', 'slide_bundle'),
            'slide_number': bundle.get('slide_number'),
            'page': bundle.get('page'),
            'time_interval': time_interval,
            'title': title,
            'text': parts[0],
            'source_file': bundle.get('source_file', ''),
            'source_sha256': bundle.get('source_sha256', ''),
            'source_locator': f"슬라이드 {bundle.get('slide_number', '')}" if bundle.get('slide_number') else '세그먼트',
            'concept_ids': mapped_concept_ids,
            'concept_candidates': detailed_candidates,
            'emphasized_keywords': content.get('emphasized_keywords', []),
            'is_exam_page': is_exam_page,
            'exam_question_count': exam_q_count,
            'provenance': {
                'record_ids': provenance.get('record_ids', []),
                'modalities': provenance.get('modalities', []),
                'warnings': provenance.get('warnings', []),
                'has_low_impact_warnings': provenance.get('has_low_impact_warnings', False)
            },
            'quality': 'multimodal_bundle_verified',
            'eligible_for_chunking': True
        }
        chunk['ds_metadata'] = extract_ds_metadata(chunk)
        return [chunk]

    chunks = []
    for i, part_text in enumerate(parts, 1):
        chunk_id = f"{bundle_id}:part-{i}"
        part_title = f"{title} (Part {i}/{len(parts)})"
        c_dict = {
            'id': chunk_id,
            'parent_chunk_id': bundle_id,
            'bundle_id': bundle_id,
            'bundle_type': bundle.get('bundle_type', 'slide_bundle'),
            'slide_number': bundle.get('slide_number'),
            'page': bundle.get('page'),
            'time_interval': time_interval,
            'title': part_title,
            'text': part_text,
            'source_file': bundle.get('source_file', ''),
            'source_sha256': bundle.get('source_sha256', ''),
            'source_locator': f"슬라이드 {bundle.get('slide_number', '')} (Part {i})" if bundle.get('slide_number') else f"세그먼트 (Part {i})",
            'concept_ids': mapped_concept_ids,
            'concept_candidates': detailed_candidates,
            'emphasized_keywords': content.get('emphasized_keywords', []),
            'is_exam_page': is_exam_page,
            'exam_question_count': exam_q_count,
            'provenance': {
                'record_ids': provenance.get('record_ids', []),
                'modalities': provenance.get('modalities', []),
                'warnings': provenance.get('warnings', []),
                'has_low_impact_warnings': provenance.get('has_low_impact_warnings', False)
            },
            'quality': 'multimodal_bundle_verified',
            'eligible_for_chunking': True
        }
        c_dict['ds_metadata'] = extract_ds_metadata(c_dict)
        chunks.append(c_dict)
    return chunks


def build_corpus_from_bundles(bundles, limit=DEFAULT_CHUNK_LIMIT, extra_taxonomy=None):
    """Transform a list of multimodal bundles into a complete RAG corpus and concept index.

    Returns:
      corpus dictionary compatible with rag_mvp
    """
    all_chunks = []
    concept_index = {}  # concept_id -> list of chunk_ids

    for b in bundles:
        chunks = create_chunks_for_bundle(b, limit=limit, extra_taxonomy=extra_taxonomy)
        for chk in chunks:
            all_chunks.append(chk)
            for cid in chk.get('concept_ids', []):
                concept_index.setdefault(cid, []).append(chk['id'])

    corpus_signature = signature({'version': 1, 'chunks': all_chunks})

    # Summary statistics
    total_concepts_mapped = len(concept_index)
    total_emphasis_chunks = sum(1 for c in all_chunks if c.get('emphasized_keywords'))

    return {
        'version': 1,
        'policy': CHUNK_POLICY,
        'signature': corpus_signature,
        'chunks': all_chunks,
        'concept_index': concept_index,
        'stats': {
            'total_bundles': len(bundles),
            'total_chunks': len(all_chunks),
            'total_concepts_mapped': total_concepts_mapped,
            'chunks_with_handwriting_emphasis': total_emphasis_chunks
        }
    }


def process_bundles_file(bundles_file, dest_corpus_path=None, extra_taxonomy=None):
    """Read a multimodal-bundles.jsonl file, generate corpus.json, and write to destination."""
    bpath = Path(bundles_file).resolve()
    if not bpath.exists():
        raise ValueError(f"Bundles file not found at {bpath}")

    bundles = [json.loads(line) for line in bpath.read_text(encoding='utf-8').splitlines() if line.strip()]
    corpus = build_corpus_from_bundles(bundles, extra_taxonomy=extra_taxonomy)

    if dest_corpus_path:
        dest = Path(dest_corpus_path).resolve()
    else:
        dest = bpath.parent / 'corpus.json'

    save(dest, corpus)
    return corpus, dest


def process_output_directory(output_dir, dest_corpus_path=None):
    """Automatically find multimodal bundles in an output directory and build corpus.json."""
    out = Path(output_dir).resolve()
    latest_path = out / 'latest.json'
    if not latest_path.exists():
        raise ValueError(f"latest.json not found in {out}")

    latest = read(latest_path)
    bundles_path = None
    if 'multimodal_bundles' in latest and Path(latest['multimodal_bundles']).exists():
        bundles_path = Path(latest['multimodal_bundles'])
    else:
        # Search in revisions
        candidates = list(out.glob('revisions/*/multimodal-bundles.jsonl'))
        if candidates:
            bundles_path = candidates[-1]

    if not bundles_path or not bundles_path.exists():
        # If bundles don't exist yet, run Step 5 bundler first!
        from video_extraction.pipeline.data_integration import bundle_directory
        bundle_directory(out)
        latest = read(latest_path)
        bundles_path = Path(latest['multimodal_bundles'])

    corpus, dest = process_bundles_file(bundles_path, dest_corpus_path)

    # Register in latest.json
    latest['concept_corpus'] = str(dest)
    latest['total_concepts_mapped'] = corpus['stats']['total_concepts_mapped']
    latest['total_chunks'] = corpus['stats']['total_chunks']
    save(latest_path, latest)

    save(out / 'corpus.json', corpus)
    return corpus, dest


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, help='Output directory of pipeline')
    ap.add_argument('--bundles', type=Path, help='Path to multimodal-bundles.jsonl')
    ap.add_argument('--dest', type=Path, help='Destination path for corpus.json')
    args = ap.parse_args()

    if args.bundles:
        corpus, dest = process_bundles_file(args.bundles, args.dest)
    elif args.output:
        corpus, dest = process_output_directory(args.output, args.dest)
    else:
        ap.error("Either --output or --bundles must be provided.")

    print(json.dumps(corpus['stats'], ensure_ascii=False, indent=2))
    print(f"Corpus generated at: {dest}")


if __name__ == '__main__':
    main()

