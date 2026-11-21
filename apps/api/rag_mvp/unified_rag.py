"""Unified Multimodal RAG Engine (Core Platform).

Provides a versatile, unified multimodal RAG foundation powering:
1. Interactive Grounded Q&A Chatbot (Multi-turn dialogue with slide & code citations)
2. Conceptual Adaptive Quiz Generator (4-choice questions with distractor rationales)
3. Short-form Video Script Generator (30~60s YouTube Shorts / Reels scripts with video timestamps)

All three applications share the identical multimodal knowledge base (text, tables,
diagrams, handwriting emphasis, teacher speech, and code) with strict grounding.
"""
import copy
import html
import json
import math
import re
import time
from pathlib import Path

from video_extraction.shared.common import read, save, signature, now
from .corpus import load_corpus, canonical
from .retrieval import keyword_search, fuse, vector_search
from .source_context import citation_texts, search_text
from .markdown_tools import render as render_markdown, supported_code, asset


class UnifiedMultimodalRAG:
    """Unified Multimodal RAG Engine for Chatbot, Quiz, and Shorts Scripting."""

    def __init__(self, output_dir, client=None, course_id=None, section_id=None, course_name=None, section_name=None,
                 *, corpus=None, retriever=None):
        self.output_dir = Path(output_dir).resolve()
        # A service may supply an already authorized DB snapshot and its persisted-vector
        # retriever. CLI callers retain the original signed file/index path.
        self.corpus = copy.deepcopy(corpus) if corpus is not None else load_corpus(self.output_dir)
        self.retriever = retriever
        self.client = client
        self.chunks = self.corpus.get('chunks', [])
        self.concept_index = self.corpus.get('concept_index', {})

        # Course & Section isolation parameters
        self.course_id = course_id or self.corpus.get('course_id')
        self.section_id = section_id or self.corpus.get('section_id')
        self.course_name = course_name or self.corpus.get('course_name')
        self.section_name = section_name or self.corpus.get('section_name')

        # Build reverse index for quick chunk lookup
        self.chunks_by_id = {c['id']: c for c in self.chunks}

        # Enrich chunks with specialized Data Structure & Algorithm metadata
        self.ds_structure_index = {}
        self.ds_operation_index = {}
        self.ds_complexity_index = {}
        self.ds_edge_case_index = {}
        self.ds_style_index = {}
        self.ds_algorithm_type_index = {}
        self.ds_paradigm_index = {}
        self.ds_analogy_index = {}

        for c in self.chunks:
            if 'ds_metadata' not in c:
                c['ds_metadata'] = self.extract_ds_metadata(c)
            meta = c['ds_metadata'] or {}
            st = meta.get('data_structure')
            if st:
                self.ds_structure_index.setdefault(st, []).append(c['id'])
            op = meta.get('operation')
            if op:
                self.ds_operation_index.setdefault(op, []).append(c['id'])
            comp = meta.get('time_complexity')
            if comp:
                self.ds_complexity_index.setdefault(comp, []).append(c['id'])
            for ec in meta.get('edge_cases', []):
                self.ds_edge_case_index.setdefault(ec, []).append(c['id'])
            style = meta.get('implementation_style')
            if style:
                self.ds_style_index.setdefault(style, []).append(c['id'])
            algo = meta.get('algorithm_type')
            if algo:
                self.ds_algorithm_type_index.setdefault(algo, []).append(c['id'])
            paradigm = meta.get('algorithm_paradigm')
            if paradigm:
                self.ds_paradigm_index.setdefault(paradigm, []).append(c['id'])
            analogy = meta.get('professor_analogy')
            if analogy:
                self.ds_analogy_index.setdefault(analogy, []).append(c['id'])

    @staticmethod
    def extract_ds_metadata(chunk):
        """Extract specialized Data Structure & Algorithm metadata from a multimodal chunk.

        Extracts:
        - data_structure: stack, queue, linked_list, tree, heap, hash_table, graph, array, recursion, sort
        - operation: init, push, pop, peek, enqueue, dequeue, is_empty, is_full, insert, delete, search, traverse
        - algorithm_type: binary_search, dfs, bfs, quick_sort, merge_sort, heap_sort, dijkstra, mst, bracket_matching, postfix_eval, maze_solving
        - algorithm_paradigm: divide_and_conquer, dynamic_programming, greedy, backtracking, brute_force, two_pointers, recursion
        - time_complexity: O(1), O(log N), O(N), O(N log N), O(N^2)
        - space_complexity: O(1), O(N)
        - edge_cases: underflow, overflow, empty_check, full_check, null_pointer, boundary_condition
        - implementation_style: array_based, pointer_based, recursive, iterative
        """
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

        # 1. Data Structure classification (Priority: Title > Concept/Emphasis > Body Text)
        ds_patterns = [
            ('stack', ['스택', 'stack', 'lifo', '후입선출', 'call stack', '콜 스택', '시스템 스택']),
            ('queue', ['원형 큐', '원형큐', 'circular queue', '큐', 'queue', 'deque', '덱', 'fifo', '선입선출']),
            ('linked_list', ['연결 리스트', '연결리스트', 'linked list', 'singly linked', 'doubly linked', '단일 연결', '이중 연결']),
            ('tree', ['이진 탐색 트리', '이진탐색트리', 'bst', '이진 트리', '이진트리', '트리', 'tree', 'binary tree', 'avl']),
            ('heap', ['최대 힙', '최소 힙', '우선순위 큐', '우선순위큐', 'priority queue', 'heap', '힙']),
            ('hash_table', ['해시 테이블', '해시테이블', '해시 맵', '해시맵', 'hash table', 'hashmap', 'hash', '해시', '해싱']),
            ('graph', ['인접 행렬', '인접 리스트', '그래프', 'graph', '정점', '간선', 'vertex', 'edge', 'dfs', 'bfs']),
            ('recursion', ['재귀 함수', '재귀함수', '재귀', 'recursion', 'recursive', '하노이의 탑']),
            ('sort', ['정렬', 'sort', 'quicksort', 'mergesort', 'bubblesort', 'insertionsort']),
            ('array', ['배열', 'array', '동적 배열', '배열 크기'])
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

        # 2. Algorithm Paradigm & Type classification
        paradigm_patterns = [
            ('divide_and_conquer', ['분할 정복', '분할정복', 'divide and conquer']),
            ('dynamic_programming', ['동적 계획법', '동적계획법', 'dp', 'dynamic programming', '메모이제이션', 'memoization']),
            ('greedy', ['그리디', '탐욕', 'greedy']),
            ('backtracking', ['백트래킹', 'backtracking', '되추적', 'n-queen']),
            ('brute_force', ['완전 탐색', '완전탐색', 'brute force', '브루트포스']),
            ('two_pointers', ['투 포인터', '투포인터', 'two pointer', '슬라이딩 윈도우', 'sliding window']),
            ('recursion', ['재귀', 'recursion', 'recursive', '하노이', 'hanoi'])
        ]
        for p_name, keywords in paradigm_patterns:
            if any(k in combined for k in keywords):
                meta['algorithm_paradigm'] = p_name
                break

        algo_patterns = [
            # Search
            ('binary_search', ['이진 탐색', '이진탐색', 'binary search', '이분 탐색']),
            ('dfs', ['dfs', '깊이 우선 탐색', '깊이우선탐색', 'depth-first', 'depth first']),
            ('bfs', ['bfs', '너비 우선 탐색', '너비우선탐색', 'breadth-first', 'breadth first']),
            # Sorting
            ('quick_sort', ['퀵 정렬', '퀵정렬', 'quicksort', 'quick sort']),
            ('merge_sort', ['병합 정렬', '병합정렬', '머지 정렬', 'mergesort', 'merge sort']),
            ('heap_sort', ['힙 정렬', '힙정렬', 'heapsort', 'heap sort']),
            ('bubble_sort', ['버블 정렬', '버블정렬', 'bubble sort']),
            ('insertion_sort', ['삽입 정렬', '삽입정렬', 'insertion sort']),
            ('selection_sort', ['선택 정렬', '선택정렬', 'selection sort']),
            # Graph Algorithms
            ('dijkstra', ['다익스트라', 'dijkstra', '최단 경로', '최단경로', 'shortest path']),
            ('mst', ['mst', '최소 신장 트리', '최소신장트리', 'kruskal', '크루스칼', 'prim', '프림']),
            ('topological_sort', ['위상 정렬', '위상정렬', 'topological sort']),
            # Data Structure Application Algorithms
            ('bracket_matching', ['괄호 검사', '괄호 매칭', '괄호 짝', 'bracket matching', 'parentheses']),
            ('postfix_eval', ['후위 표기법', '후위표기법', 'postfix', '수식 계산', '후위 수식']),
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

        # 2. Operation classification (Priority: Title > Combined)
        op_patterns = [
            ('peek', ['peek', '피크', 'top 조회', 'peek()', '맨 위']),
            ('is_empty', ['is_empty', 'isempty', '비어 있는지', '비어있는지', '공백 상태', 'empty check']),
            ('is_full', ['is_full', 'isfull', '가득 찼는지', '포화 상태', 'full check']),
            ('enqueue', ['enqueue', 'en_queue', '큐 삽입']),
            ('dequeue', ['dequeue', 'de_queue', '큐 삭제', '큐 제거']),
            ('push', ['push', '삽입', '추가', 'push()', '인큐']),
            ('pop', ['pop', '삭제', '추출', '제거', 'pop()', '디큐']),
            ('traverse', ['순회', 'traverse', 'traversal', 'inorder', 'preorder', 'postorder', '중위 순회', '전위 순회', '후위 순회']),
            ('search', ['탐색', '검색', 'search', 'find']),
            ('init', ['init', '초기화', 'create', '생성'])
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

        # 3. Time & Space Complexity
        comp_match = re.search(r'o\s*\(\s*(1|log\s*n|n\s*log\s*n|n\^2|n|2\^n)\s*\)', combined)
        if comp_match:
            meta['time_complexity'] = f"O({comp_match.group(1).replace(' ', '').upper()})"
        else:
            # Canonical algorithmic complexity defaults
            if meta['data_structure'] == 'stack' and meta['operation'] in ('push', 'pop', 'peek', 'is_empty', 'is_full'):
                meta['time_complexity'] = 'O(1)'
            elif meta['data_structure'] == 'queue' and meta['operation'] in ('enqueue', 'dequeue', 'peek', 'is_empty', 'is_full'):
                meta['time_complexity'] = 'O(1)'
            elif meta['data_structure'] == 'array' and meta['operation'] == 'push':
                meta['time_complexity'] = 'O(1)'
            elif meta['data_structure'] == 'array' and meta['operation'] in ('search', 'delete'):
                meta['time_complexity'] = 'O(N)'
            elif meta['data_structure'] == 'linked_list' and meta['operation'] in ('push', 'insert_front', 'delete_front'):
                meta['time_complexity'] = 'O(1)'
            elif meta['data_structure'] == 'linked_list' and meta['operation'] in ('search', 'traverse'):
                meta['time_complexity'] = 'O(N)'

        # Space complexity
        if meta['data_structure'] in ('stack', 'queue', 'linked_list', 'array', 'tree'):
            meta['space_complexity'] = 'O(N)'

        # 4. Edge Cases
        edge_cases = []
        if 'underflow' in combined or '언더플로우' in combined or '언더플로' in combined:
            edge_cases.append('underflow')
        if 'overflow' in combined or '오버플로우' in combined or '오버플로' in combined:
            edge_cases.append('overflow')
        if '비어' in combined or 'empty' in combined or '공백' in combined or meta['operation'] == 'is_empty':
            edge_cases.append('empty_check')
        if '가득' in combined or 'full' in combined or '포화' in combined or meta['operation'] == 'is_full':
            edge_cases.append('full_check')
        if 'null' in combined or 'none' in combined or '널 포인터' in combined or 'nullptr' in combined:
            edge_cases.append('null_pointer')
        if any(k in combined for k in ['boundary', '경계', '초과', '인덱스 오류', 'indexerror', '인덱스 범위']):
            edge_cases.append('boundary_condition')
        meta['edge_cases'] = sorted(set(edge_cases))

        # 5. Implementation Style
        if any(k in combined for k in ['포인터', 'pointer', 'node', '노드', '->', '.next', 'next node', '연결 리스트로 구현']):
            meta['implementation_style'] = 'pointer_based'
        elif any(k in combined for k in ['배열로 구현', '배열 기반', 'array', '배열', 'stack[', 'arr[']):
            meta['implementation_style'] = 'array_based'
        elif any(k in combined for k in ['재귀', 'recursion', 'recursive']):
            meta['implementation_style'] = 'recursive'
        elif any(k in combined for k in ['반복', 'iteration', 'iterative', '루프', 'while', 'for']):
            meta['implementation_style'] = 'iterative'

        # 6. Professor Analogy Detection (Real-life metaphors used in lectures)
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

    def get_ds_metadata_summary(self):
        """Return statistical breakdown of algorithms and data structures across the corpus."""
        summary = {
            'total_chunks': len(self.chunks),
            'ds_classified_chunks': 0,
            'structures': {},
            'operations': {},
            'algorithms': {},
            'paradigms': {},
            'complexities': {},
            'edge_cases': {},
            'implementation_styles': {},
            'analogies': {}
        }
        for c in self.chunks:
            meta = c.get('ds_metadata') or {}
            if any(meta.values()):
                summary['ds_classified_chunks'] += 1
            if meta.get('data_structure'):
                st = meta['data_structure']
                summary['structures'][st] = summary['structures'].get(st, 0) + 1
            if meta.get('operation'):
                op = meta['operation']
                summary['operations'][op] = summary['operations'].get(op, 0) + 1
            if meta.get('algorithm_type'):
                algo = meta['algorithm_type']
                summary['algorithms'][algo] = summary['algorithms'].get(algo, 0) + 1
            if meta.get('algorithm_paradigm'):
                p = meta['algorithm_paradigm']
                summary['paradigms'][p] = summary['paradigms'].get(p, 0) + 1
            if meta.get('time_complexity'):
                comp = meta['time_complexity']
                summary['complexities'][comp] = summary['complexities'].get(comp, 0) + 1
            for ec in meta.get('edge_cases', []):
                summary['edge_cases'][ec] = summary['edge_cases'].get(ec, 0) + 1
            if meta.get('implementation_style'):
                style = meta['implementation_style']
                summary['implementation_styles'][style] = summary['implementation_styles'].get(style, 0) + 1
            if meta.get('professor_analogy'):
                an = meta['professor_analogy']
                summary['analogies'][an] = summary['analogies'].get(an, 0) + 1
        return summary

    def retrieve(self, query, top_k=4, concept_id=None, slide_number=None, require_code=False, require_speech=False,
                 data_structure=None, operation=None, algorithm_type=None, algorithm_paradigm=None,
                 time_complexity=None, edge_case=None, implementation_style=None, professor_analogy=None):
        """Retrieve top multimodal chunks using hybrid vector + keyword fusion with metadata filtering."""
        filtered_chunks = self.chunks

        # 1. Section Isolation (Method 2: Logical metadata enforcement)
        if self.section_id:
            filtered_chunks = [c for c in filtered_chunks if c.get('section_id') == self.section_id]
        if self.course_id:
            filtered_chunks = [c for c in filtered_chunks if c.get('course_id') == self.course_id]

        # 2. Metadata Filtering
        if concept_id:
            matching_ids = set(self.concept_index.get(concept_id, []))
            if not matching_ids:
                # Substring/fuzzy concept match
                for cid, cids in self.concept_index.items():
                    if concept_id.lower() in cid.lower():
                        matching_ids.update(cids)
            filtered_chunks = [c for c in filtered_chunks if c['id'] in matching_ids or concept_id in c.get('concept_ids', [])]

        if slide_number is not None:
            filtered_chunks = [c for c in filtered_chunks if c.get('slide_number') == slide_number]

        if require_code:
            filtered_chunks = [c for c in filtered_chunks if '```' in c.get('text', '') or c.get('kind') == 'code']

        if require_speech:
            filtered_chunks = [c for c in filtered_chunks if '강사 음성 해설' in c.get('text', '') or (c.get('time_interval') or {}).get('start_seconds') is not None]

        # Data Structure & Algorithm specialized metadata filtering
        if data_structure:
            norm_ds = data_structure.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('data_structure') == norm_ds]

        if operation:
            norm_op = operation.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('operation') == norm_op]

        if algorithm_type:
            norm_algo = algorithm_type.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('algorithm_type') == norm_algo]

        if algorithm_paradigm:
            norm_p = algorithm_paradigm.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('algorithm_paradigm') == norm_p]

        if time_complexity:
            norm_comp = time_complexity.upper().replace(' ', '')
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('time_complexity') == norm_comp]

        if edge_case:
            norm_ec = edge_case.lower()
            filtered_chunks = [c for c in filtered_chunks if norm_ec in (c.get('ds_metadata') or {}).get('edge_cases', [])]

        if implementation_style:
            norm_style = implementation_style.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('implementation_style') == norm_style]

        if professor_analogy:
            norm_an = professor_analogy.lower()
            filtered_chunks = [c for c in filtered_chunks if (c.get('ds_metadata') or {}).get('professor_analogy') == norm_an]

        if not filtered_chunks:
            # Never broaden an explicit course/concept/metadata filter on an empty result.
            return []

        if self.retriever is not None:
            return self.retriever(query, filtered_chunks, top_k)

        # 2. Hybrid Retrieval
        if not query or not str(query).strip():
            return filtered_chunks[:top_k]

        keyword_hits = keyword_search(filtered_chunks, query, limit=max(top_k * 2, 8))

        vector_hits = []
        if self.client is not None:
            try:
                vector_hits = vector_search(self.output_dir, self.corpus, self.client, query, limit=max(top_k * 2, 8))
                # Filter vector hits to stay within filtered_chunks
                allowed_ids = {c['id'] for c in filtered_chunks}
                vector_hits = [h for h in vector_hits if h['id'] in allowed_ids]
            except Exception:
                # Fallback to keyword search if vector index is not yet built or offline
                vector_hits = []

        if vector_hits:
            fused_hits = fuse(filtered_chunks, vector_hits, keyword_hits, limit=top_k)
        else:
            fused_hits = keyword_hits[:top_k]

        return fused_hits

    # -------------------------------------------------------------------------
    # Context Formatting
    # -------------------------------------------------------------------------

    def format_multimodal_context(self, hits):
        """Format retrieved hits into structured prompt context with temporal and emphasis cues."""
        sections = []
        for i, hit in enumerate(hits, 1):
            slide_no = hit.get('slide_number') or hit.get('page')
            loc = hit.get('source_locator') or (f"슬라이드 {slide_no}" if slide_no else "강의 자료")
            sec_info = ""
            c_name = hit.get('course_name') or self.course_name
            s_name = hit.get('section_name') or self.section_name
            if c_name or s_name:
                sec_info = f"({c_name or ''} {s_name or ''}) "

            title = hit.get('title', '')
            t_interval = hit.get('time_interval') or {}
            start_s = t_interval.get('start_seconds')
            end_s = t_interval.get('end_seconds')

            time_str = ""
            if start_s is not None and end_s is not None:
                m_start, s_start = int(start_s // 60), int(start_s % 60)
                m_end, s_end = int(end_s // 60), int(end_s % 60)
                time_str = f" [영상 시간: {m_start:02d}:{s_start:02d} ~ {m_end:02d}:{s_end:02d}]"

            emp_kws = hit.get('emphasized_keywords') or []
            emp_str = f"\n[교수님 필기 강조 키워드]: {', '.join(emp_kws)}" if emp_kws else ""

            ds_meta = hit.get('ds_metadata') or {}
            ds_parts = []
            if ds_meta.get('data_structure'):
                ds_parts.append(f"자료구조: {ds_meta['data_structure']}")
            if ds_meta.get('operation'):
                ds_parts.append(f"연산: {ds_meta['operation']}")
            if ds_meta.get('algorithm_type'):
                ds_parts.append(f"알고리즘: {ds_meta['algorithm_type']}")
            if ds_meta.get('algorithm_paradigm'):
                ds_parts.append(f"패러다임: {ds_meta['algorithm_paradigm']}")
            if ds_meta.get('time_complexity'):
                ds_parts.append(f"시간복잡도: {ds_meta['time_complexity']}")
            if ds_meta.get('space_complexity'):
                ds_parts.append(f"공간복잡도: {ds_meta['space_complexity']}")
            if ds_meta.get('edge_cases'):
                ds_parts.append(f"엣지케이스: {', '.join(ds_meta['edge_cases'])}")
            if ds_meta.get('implementation_style'):
                ds_parts.append(f"구현방식: {ds_meta['implementation_style']}")
            if ds_meta.get('professor_analogy'):
                ds_parts.append(f"교수님 비유: {ds_meta['professor_analogy']}")
            ds_str = f"\n[자료구조/알고리즘 메타데이터]: {' | '.join(ds_parts)}" if ds_parts else ""

            sec = [
                f"### [자료 {i}: {sec_info}{loc} · {title}{time_str}]",
                f"자료 ID: {hit['id']}{emp_str}{ds_str}",
                hit['text']
            ]
            sections.append("\n\n".join(sec))

        return "\n\n---\n\n".join(sections)

    # -------------------------------------------------------------------------
    # 1. Chatbot Engine (대화형 질의응답)
    # -------------------------------------------------------------------------

    def ask_chat(self, question, history=None, top_k=4):
        """Answer a question in an interactive conversational style with grounding and citations."""
        if not question or not question.strip():
            raise ValueError("질문을 입력해주세요.")

        hits = self.retrieve(question, top_k=top_k)
        if not hits and history:
            # [방법 3: 직전 질문 결합 재검색]
            prev_user_msgs = [h['content'] for h in history if h.get('role') == 'user']
            if prev_user_msgs:
                combined_query = f"{prev_user_msgs[-1]} {question}"
                hits = self.retrieve(combined_query, top_k=top_k)
        if not hits and getattr(self, 'corpus', None):
            # [방법 2: 직전 슬라이드 근거 폴백]
            hits = self.corpus[:top_k]

        if not hits:
            return {
                'answerable': False,
                'reply': '현재 검색된 강의 자료 중 질문과 관련된 내용을 찾지 못했습니다. 다른 키워드로 질문해주세요.',
                'citations': [],
                'reason': 'no_relevant_sources_found',
                'hits': []
            }

        # Offline heuristic response or Gemini client call
        if self.client is None:
            # Deterministic offline mock response for testing/offline mode
            top_hit = hits[0]
            loc = top_hit.get('source_locator', f"슬라이드 {top_hit.get('slide_number', '')}")
            quote = top_hit['text'].split('\n')[0].replace('#', '').strip()
            reply = f"검색된 {loc}에 따르면, '{question}' 관련 내용은 다음과 같습니다:\n\n{top_hit['text'][:250]}..."
            return {
                'answerable': True,
                'reply': reply,
                'citations': [{'source_id': top_hit['id'], 'locator': loc, 'quote': quote}],
                'reason': 'offline_retrieval_success',
                'hits': hits
            }

        # Online LLM execution
        context_str = self.format_multimodal_context(hits)
        prompt = self._build_chat_prompt(question, context_str, history)
        if hasattr(self.client, 'answer_chat_prompt'):
            candidate = self.client.answer_chat_prompt(question, hits, history, prompt)
        else:
            candidate = self.client.answer_chat(question, hits, history) if hasattr(self.client, 'answer_chat') else self.client.answer(question, hits)

        return {
            'question': question,
            'candidate': candidate,
            'hits': hits,
            'at': now()
        }

    def _build_chat_prompt(self, question, context_str, history=None):
        hist_str = ""
        if history:
            hist_str = "\n[이전 대화 내역]\n" + "\n".join(f"- {h['role']}: {h['content']}" for h in history[-4:]) + "\n"
        return f"""당신은 대학 '알고리즘 및 자료구조' 과목의 친절하고 노련한 선배 조교(TA) AI 튜터입니다.
대화 상대는 **자료구조를 이번 학기에 처음 배우는 초심자 학부생(2학년 및 비전공/복수전공생)**입니다.

[초심자 맞춤형 상담 및 지도 5대 원칙]
1. **완성된 정답 코드 통째 복붙 금지 (스캐폴딩 단계별 유도)**:
   - 학생이 "코드 짜줘", "구현해줘", "답 알려줘"라고 요구하더라도 완성된 전체 코드를 한 번에 던져주지 마세요.
   - 스스로 로직을 깨달을 수 있도록 1) 직관적 일상 비유 -> 2) 현재 자료구조의 상태 변화 관찰 -> 3) 한 줄 힌트 순으로 단계별로 유도하세요.
2. **2단계 적응형 일상 비유 원칙 (교수님 비유 최우선 -> AI 초심자 비유 백업)**:
   - **[1순위: 교수님 비유 최우선 계승]**: 제공된 [강의 발췌 자료]의 슬라이드나 음성 해설에 교수님이 직접 사용하신 비유/예시(예: '교수님 비유' 메타데이터 또는 본문의 '프링글스', '접시 쌓기', '줄서기' 등)가 있다면, 반드시 "교수님께서 수업 중에 비유하신 [교수님의 비유]처럼..."과 같이 교수님의 비유를 100% 최우선으로 사용하여 설명하세요.
   - **[2순위: AI 초심자 비유 자동 보완]**: 강의 자료에 교수님의 일상 비유가 없는 경우에만, AI가 직접 자료구조를 처음 배우는 초심자 눈높이에 맞는 가장 직관적인 일상 사물 비유(스택=접시 쌓기/프링글스 통, 큐=편의점 줄서기/터널, 연결리스트=기차 칸/손잡기 등)를 하나 선정하여 부드럽게 설명하세요.
   - 절대 어려운 컴퓨터 구조 용어(하드웨어 메모리 주소, 레지스터, 가상 메모리 등)로 학생에게 직관을 대신하지 마세요.
3. **1번에 딱 1개만 묻는 직관적인 유도 질문 (Socratic Questioning)**:
   - 한 번에 여러 개의 질문을 쏟아붓지 마세요.
   - 초심자가 복잡한 수식 없이 바로 머릿속에 떠올릴 수 있는 1단계 질문(양자택일, 예/아니오, 단순 상태 추적) 1개만 던져 학생이 답하게 하세요.
     - ⭕ 좋은 질문 예시: "만약 상자가 텅 비어있는데 물건을 꺼내려고(pop) 하면 어떤 문제가 생길까요?", "데이터를 넣을 때, top의 위치 번호를 먼저 1 올려야 할까요? 아니면 데이터를 먼저 집어넣어야 할까요?"
     - ❌ 나쁜 질문 예시: "스택 프레임의 가상 주소 할당과 오버헤드를 고려하여 최적의 동적 할당 방식을 설명해보세요." (절대 금지)
4. **철저한 강의 자료 인용 (Grounding & Citations)**:
   - 오직 아래 제공된 [강의 발췌 자료]에 근거해서만 답변하세요. 자료에 없는 내용은 추측하지 마세요.
   - 교수님이 강의에서 사용하신 변수명(예: self.top, self.items, capacity 등)과 [슬라이드 N] 또는 코드 위치를 반드시 인용하세요.
5. **정서적 지지와 긍정적 격려**:
   - 학생이 틀리거나 헷갈려해도 "자료구조를 처음 배울 때는 top이 0인지 -1인지 헷갈리는 것이 아주 자연스러워요!", "여기까지 생각하신 건 정말 좋은 접근이에요!"처럼 자신감을 북돋워주세요.

{hist_str}
[강의 발췌 자료]
{context_str}

학생 질문: {question}"""

    # -------------------------------------------------------------------------
    # 2. Quiz Generator Engine (개념 및 강의 퀴즈)
    # -------------------------------------------------------------------------

    def generate_quiz(self, topic_or_concept, difficulty='medium', top_k=3):
        """Generate a 4-choice conceptual quiz question grounded in lecture slides and speech."""
        hits = self.retrieve(topic_or_concept, top_k=top_k)
        if not hits:
            return {
                'success': False,
                'reason': f"'{topic_or_concept}' 관련 강의 자료를 찾을 수 없습니다."
            }

        top_hit = hits[0]
        loc = top_hit.get('source_locator', f"슬라이드 {top_hit.get('slide_number', '')}")
        emp_kws = top_hit.get('emphasized_keywords') or []

        # If offline or no client, provide structured template response
        if self.client is None:
            concept_name = emp_kws[0] if emp_kws else topic_or_concept
            quiz_data = {
                'success': True,
                'concept_id': top_hit.get('concept_ids', [topic_or_concept])[0] if top_hit.get('concept_ids') else topic_or_concept,
                'question_stem': f"다음 중 '{concept_name}'에 대한 강의 내용의 설명으로 가장 올바른 것은?",
                'options': [
                    f"① {concept_name}의 주요 특성과 원리에 부합하는 올바른 설명",
                    f"② 다른 개념과 혼동하기 쉬운 오답 선지 A",
                    f"③ 기술적 한계 및 제약 사항을 반대로 왜곡한 오답 선지 B",
                    f"④ 일반적인 통념이지만 본 강의 내용과 일치하지 않는 오답 선지 C"
                ],
                'correct_index': 0,
                'explanation': f"{loc}의 강의 내용 및 강사 해설에 근거하여 1번이 정답입니다.",
                'distractor_rationales': [
                    "정답: 본문 강의 설명과 일치",
                    "오답: 개념의 정의를 반대로 기술함",
                    "오답: 조건 및 적용 범위가 잘못됨",
                    "오답: 강의에서 다루지 않은 왜곡된 설명"
                ],
                'source_id': top_hit['id'],
                'source_locator': loc,
                'quote': top_hit['text'].split('\n')[0].replace('#', '').strip()
            }
            return quiz_data

        # Online LLM execution
        quiz_result = self.client.generate_quiz(topic_or_concept, hits, difficulty)
        return quiz_result

    # -------------------------------------------------------------------------
    # 3. Shorts Script Generator & Candidate Extractor Engine (숏츠 영상 대본)
    # -------------------------------------------------------------------------

    def score_chunk_for_shorts(self, chunk, max_duration=None, weights=None):
        """Calculate 3-factor composite importance score for short-form video generation.
        
        Triangulates:
        1. Speech Duration Ratio (음성 비중): How long the professor spoke on this slide.
        2. Handwriting Ink Emphasis (필기 강조): Professor's hand-drawn ink keywords & marks.
        3. PPT Content & Visual Density (피피티 비율): Text length + Code fences + Diagrams/Tables.

        Formula:
            Base_Score (0~100) = (Speech_Score * 0.70) + (PPT_Score * 0.30)
            Ink_Bonus (+0~+10) = Additive bonus for hand-drawn keywords/marks
            Total_Score = min(100.0, Base_Score + Ink_Bonus)
        
        Designed so that:
        1. Base score allows professors who never write by hand to reach a full 100 points.
        2. Handwriting acts purely as an additive bonus (+0 ~ +10), never penalizing no-ink slides.
        """
        weights = weights or {'speech': 0.70, 'ppt': 0.30}
        w_speech = weights.get('speech', 0.70)
        w_ppt = weights.get('ppt', 0.30)

        # 1. Speech Duration Score (0~100)
        t_interval = chunk.get('time_interval') or {}
        start_s = t_interval.get('start_seconds')
        end_s = t_interval.get('end_seconds')
        duration = 0.0
        if start_s is not None and end_s is not None and end_s > start_s:
            duration = float(end_s - start_s)
        elif '강사 음성 해설' in chunk.get('text', ''):
            speech_match = re.search(r'\*\*\[강사 음성 해설\]\*\*:\s*([^\n]+)', chunk.get('text', ''))
            if speech_match:
                duration = len(speech_match.group(1)) / 4.0  # Approx 4 chars per second in Korean

        if max_duration and max_duration > 0:
            speech_score = min(100.0, (duration / max_duration) * 100.0)
        else:
            speech_score = min(100.0, (duration / 120.0) * 100.0)  # 2 minutes = 100 pts benchmark

        # 2. PPT Content & Visual Density Score (0~100)
        text = chunk.get('text', '')
        clean_text = re.sub(r'#|\*|\[.*?\]', '', text).strip()
        text_score = min(50.0, (len(clean_text) / 200.0) * 50.0)

        code_score = 30.0 if ('```' in text or chunk.get('kind') == 'code') else 0.0

        visual_score = 0.0
        if '[시각 자료/다이어그램]' in text or '다이어그램' in text or '표' in text or '\t' in text:
            visual_score = 20.0
        elif (chunk.get('provenance') or {}).get('modalities') and 'image' in chunk['provenance']['modalities']:
            visual_score = 20.0

        ppt_score = min(100.0, text_score + code_score + visual_score)

        # 3. Base Score (Speech + PPT Density): 100-point base scale
        base_score = round(speech_score * w_speech + ppt_score * w_ppt, 1)

        # 4. Handwriting Ink Bonus (+0 ~ +10 points additive bonus)
        # Treated purely as a bonus booster, never a penalty for no ink:
        emp_kws = chunk.get('emphasized_keywords') or []
        kw_count = len(emp_kws)
        if kw_count >= 3:
            ink_score = 100.0
            ink_bonus = 10.0
        elif kw_count == 2:
            ink_score = 80.0
            ink_bonus = 8.0
        elif kw_count == 1:
            ink_score = 60.0
            ink_bonus = 6.0
        else:
            prov_records = (chunk.get('provenance') or {}).get('record_ids', [])
            has_ink = any(':ink:' in str(r) for r in prov_records)
            ink_score = 30.0 if has_ink else 0.0
            ink_bonus = 3.0 if has_ink else 0.0

        # Total score: Base Score + Additive Ink Bonus, capped at 100.0
        total_score = min(100.0, round(base_score + ink_bonus, 1))

        return {
            'total_score': total_score,
            'base_score': round(base_score, 1),
            'speech_score': round(speech_score, 1),
            'ppt_score': round(ppt_score, 1),
            'ink_bonus': round(ink_bonus, 1),
            'ink_score': round(ink_score, 1),
            'duration_seconds': round(duration, 1),
            'keyword_count': kw_count,
            'has_code': code_score > 0,
            'has_visual': visual_score > 0
        }

    def _bundle_concept_chunks(self, eligible_chunks):
        """Bundle multi-slide chunks that share the same concept_id into unified concept units.
        
        Allows multi-slide concepts (e.g. Slide 1: Definition -> Slide 2: Operations -> Slide 3: Code)
        to be evaluated and scripted as a cohesive educational story arc.
        """
        cid_to_chunks = {}
        standalone_chunks = []

        for c in eligible_chunks:
            cids = c.get('concept_ids') or []
            if cids:
                for cid in cids:
                    cid_to_chunks.setdefault(cid, []).append(c)
            else:
                standalone_chunks.append(c)

        bundled = []
        processed_ids = set()

        for cid, clist in cid_to_chunks.items():
            unique_clist = []
            seen = set()
            for chk in clist:
                if chk['id'] not in seen:
                    seen.add(chk['id'])
                    unique_clist.append(chk)

            if len(unique_clist) == 1:
                bundled.append(unique_clist[0])
                processed_ids.add(unique_clist[0]['id'])
            else:
                for chk in unique_clist:
                    processed_ids.add(chk['id'])

                unique_clist.sort(key=lambda x: (x.get('slide_number') or x.get('page') or 0))
                s_nums = [c.get('slide_number') or c.get('page') for c in unique_clist if (c.get('slide_number') or c.get('page')) is not None]

                starts = [c.get('time_interval', {}).get('start_seconds') for c in unique_clist if c.get('time_interval', {}).get('start_seconds') is not None]
                ends = [c.get('time_interval', {}).get('end_seconds') for c in unique_clist if c.get('time_interval', {}).get('end_seconds') is not None]

                t_interval = {}
                if starts and ends:
                    t_interval = {'start_seconds': min(starts), 'end_seconds': max(ends)}

                merged_text = "\n\n---\n\n".join(c.get('text', '') for c in unique_clist)
                merged_kws = list(dict.fromkeys(sum([c.get('emphasized_keywords', []) for c in unique_clist], [])))

                loc_str = f"슬라이드 {min(s_nums)}~{max(s_nums)} (연계 {len(unique_clist)}장)" if s_nums else f"연계 {len(unique_clist)}장"

                merged = {
                    'id': f"concept_bundle:{cid}",
                    'concept_id': cid,
                    'title': unique_clist[0].get('title', cid),
                    'slide_number': s_nums[0] if s_nums else 1,
                    'source_locator': loc_str,
                    'text': merged_text,
                    'time_interval': t_interval,
                    'emphasized_keywords': merged_kws,
                    'is_multi_slide': True,
                    'slide_count': len(unique_clist),
                    'contained_chunk_ids': [c['id'] for c in unique_clist]
                }
                bundled.append(merged)

        for c in standalone_chunks:
            if c['id'] not in processed_ids:
                bundled.append(c)

        return bundled

    def extract_shorts_candidates(self, min_score=70.0, top_n=5, ensure_min_candidates=3, fallback_floor=60.0, weights=None, group_by_concept=True):
        """Automatically extract top candidate slides/concepts for Shorts scripts using the Hybrid Rule:
        
        Hybrid Rule:
        1. Primary Rule: Select all candidates satisfying total_score >= min_score (default: 70.0).
        2. Safety Fallback: If fewer than `ensure_min_candidates` (default: 3) reach `min_score`,
           automatically lower threshold down to `fallback_floor` (default: 60.0) to guarantee
           the top candidates (up to ensure_min_candidates) are preserved for video production.
        
        Args:
            min_score: Primary score threshold (default: 70.0)
            top_n: Maximum number of top candidates to return
            ensure_min_candidates: Minimum number of candidates to secure via hybrid fallback (default: 3)
            fallback_floor: Absolute floor threshold below which no candidates are accepted (default: 60.0)
            weights: Dictionary of custom weights ('speech', 'ppt')
            group_by_concept: If True, multi-slide concepts sharing a concept_id are evaluated as a unified bundle.
        """
        if not self.chunks:
            return []

        # 1. Course and Section isolation
        eligible_chunks = self.chunks
        if self.section_id:
            eligible_chunks = [c for c in eligible_chunks if c.get('section_id') == self.section_id]
        if self.course_id:
            eligible_chunks = [c for c in eligible_chunks if c.get('course_id') == self.course_id]

        if not eligible_chunks:
            return []

        # Bundle multi-slide concept sequences if enabled
        if group_by_concept:
            eligible_chunks = self._bundle_concept_chunks(eligible_chunks)

        # 2. Compute max duration for fair normalization
        max_duration = 0.0
        for c in eligible_chunks:
            t_int = c.get('time_interval') or {}
            st, et = t_int.get('start_seconds'), t_int.get('end_seconds')
            if st is not None and et is not None and et > st:
                max_duration = max(max_duration, float(et - st))
        if max_duration <= 0.0:
            max_duration = 120.0

        scored = []
        for c in eligible_chunks:
            metrics = self.score_chunk_for_shorts(c, max_duration=max_duration, weights=weights)
            emp_kws = c.get('emphasized_keywords') or []
            title = c.get('title') or c.get('id')
            recommended_hook = emp_kws[0] if emp_kws else title

            scored.append({
                'id': c['id'],
                'slide_number': c.get('slide_number') or c.get('page'),
                'title': title,
                'source_locator': c.get('source_locator', f"슬라이드 {c.get('slide_number', '')}"),
                'total_score': metrics['total_score'],
                'tier': 'Gold' if metrics['total_score'] >= 75.0 else 'Silver',
                'metrics': metrics,
                'recommended_hook': recommended_hook,
                'is_multi_slide': c.get('is_multi_slide', False),
                'slide_count': c.get('slide_count', 1),
                'selection_rule': 'primary' if metrics['total_score'] >= min_score else 'fallback',
                'chunk': c
            })

        scored.sort(key=lambda x: x['total_score'], reverse=True)

        # Apply Hybrid Rule
        primary = [c for c in scored if c['total_score'] >= min_score]
        if len(primary) >= ensure_min_candidates:
            return primary[:top_n]

        # Hybrid Fallback kicks in: ensure at least ensure_min_candidates if above fallback_floor
        fallback_candidates = []
        for c in scored:
            if c['total_score'] >= min_score:
                c['selection_rule'] = 'primary'
                fallback_candidates.append(c)
            elif c['total_score'] >= fallback_floor:
                c['selection_rule'] = 'hybrid_fallback'
                fallback_candidates.append(c)
                if len(fallback_candidates) >= ensure_min_candidates:
                    break

        return fallback_candidates[:top_n]

    def generate_shorts_script(self, topic_or_concept=None, chunk_id=None, target_seconds=60, top_k=3):
        """Generate a 30~60s short-form video script with scene directions, visual cues, and timestamps."""
        top_hit = None
        evidence_hits = []

        if chunk_id:
            if chunk_id in self.chunks_by_id:
                top_hit = self.chunks_by_id[chunk_id]
            else:
                candidates = self.extract_shorts_candidates(min_score=0.0, top_n=50, group_by_concept=True)
                for cand in candidates:
                    if cand['id'] == chunk_id:
                        top_hit = cand['chunk']
                        break
        elif topic_or_concept:
            hits = self.retrieve(topic_or_concept, top_k=top_k, require_speech=False)
            if hits:
                top_hit = hits[0]
                evidence_hits = hits
        else:
            # Auto candidate extraction (using multi-slide concept bundling)
            candidates = self.extract_shorts_candidates(min_score=60.0, top_n=1, group_by_concept=True)
            if candidates:
                top_hit = candidates[0]['chunk']

        if not top_hit:
            return {
                'success': False,
                'reason': f"'{topic_or_concept or '숏츠 후보'}' 관련 강의 자료를 찾을 수 없습니다."
            }
        if self.client is not None:
            return self.client.generate_shorts_script(
                topic_or_concept or top_hit.get('title', ''), evidence_hits or [top_hit], target_seconds
            )
        loc = top_hit.get('source_locator', f"슬라이드 {top_hit.get('slide_number', '')}")
        t_interval = top_hit.get('time_interval') or {}
        start_s = t_interval.get('start_seconds', 0.0)
        end_s = t_interval.get('end_seconds', 60.0)

        m_start, s_start = int(start_s // 60), int(start_s % 60)
        m_end, s_end = int(end_s // 60), int(end_s % 60)
        timestamp_str = f"{m_start:02d}:{s_start:02d} ~ {m_end:02d}:{s_end:02d}"

        emp_kws = top_hit.get('emphasized_keywords') or []
        hook_keyword = emp_kws[0] if emp_kws else (top_hit.get('title') or topic_or_concept or '핵심 개념')

        # Extract teacher speech transcript snippet if available
        speech_match = re.search(r'\*\*\[강사 음성 해설\]\*\*:\s*([^\n]+)', top_hit.get('text', ''))
        speech_snippet = speech_match.group(1) if speech_match else ""

        # Extract code snippet if present (for dedicated dark code editor UI, avoiding professor's raw slide)
        code_match = re.search(r'```(?:\w+)?\n(.*?)```', top_hit.get('text', ''), re.DOTALL)
        code_snippet = code_match.group(1).strip() if code_match else ""
        has_visual = ('[시각 자료' in top_hit.get('text', '') or '다이어그램' in top_hit.get('text', '') or '표' in top_hit.get('text', ''))

        # Build custom graphic directions for each scene (no professor slides used in video)
        if code_snippet:
            body_graphic_desc = f"[VS Code 스타일 다크 에디터 창]\n```\n{code_snippet[:200]}\n```"
            body_visual_dir = f"다크 모드 개발자 코드 에디터(VS Code 스타일) 창 노출. 핵심 코드가 한 줄씩 하이라이트되는 모션 그래픽. (교수님 슬라이드 미사용 / 자체 코드 UI 창)"
        elif has_visual:
            body_graphic_desc = f"[9:16 세로형 플랫 인포그래픽]\n• 중심 개념: {hook_keyword}\n• 주요 동작 흐름을 나타내는 화살표와 2D 모션 블록"
            body_visual_dir = f"9:16 맞춤형 세로형 플랫 인포그래픽. '{hook_keyword}'의 핵심 동작 흐름을 보여주는 직관적인 화살표와 블록 애니메이션. (교수님 슬라이드 미사용 / 자체 인포그래픽)"
        else:
            body_graphic_desc = f"[2단 비교/개념 요약 카드 UI]\n• 좌측: {hook_keyword} 정의 및 원리\n• 우측: 주요 특징 및 처리 방식"
            body_visual_dir = f"모던 2단 카드 UI 그래픽. 좌우로 핵심 정의와 특징이 팝업되는 모션. (교수님 슬라이드 미사용 / 자체 카드 그래픽)"

        # Structured 3-Act Shorts Script Template (Professor slides omitted; fully scripted custom graphics)
        script = {
            'success': True,
            'title': f"[30초 전공핵심] 한 번에 이해하는 '{hook_keyword}'의 원리와 핵심 구조",
            'target_seconds': target_seconds,
            'concept': hook_keyword,
            'source_locator': loc,
            'original_video_timestamp': timestamp_str,
            'acts': [
                {
                    'act': 'Hook',
                    'seconds': '00:00 ~ 00:05',
                    'screen_graphic': f"[타이틀 카드]\n• 네온 텍스트: '{hook_keyword}'\n• 부제: 30초 만에 짚는 핵심 구조",
                    'visual_direction': f"다크 네이비 모던 모션 그래픽. 화면 중앙에 네온 폰트로 '{hook_keyword}' 키워드 카드 팝업. (교수님 슬라이드 미사용 / 자체 텍스트 카드 UI)",
                    'narration': f"전공 공부할 때 자주 접하지만 원리를 놓치기 쉬운 '{hook_keyword}', 5초 만에 핵심만 짚어드립니다!"
                },
                {
                    'act': 'Body',
                    'seconds': '00:05 ~ 00:45',
                    'screen_graphic': body_graphic_desc,
                    'visual_direction': body_visual_dir,
                    'narration': f"{speech_snippet if speech_snippet else hook_keyword + '의 핵심 개념과 동작 원리입니다.'} 화면에 보이는 구조처럼 동작 흐름을 파악하면 원리를 명쾌하게 정리할 수 있습니다!"
                },
                {
                    'act': 'Outro',
                    'seconds': '00:45 ~ 00:60',
                    'screen_graphic': f"[최종 요약 카드]\n• 핵심 1: {hook_keyword} 기본 구조\n• 핵심 2: 동작 흐름 이해\n• 원본 영상 구간: [{timestamp_str}]",
                    'visual_direction': f"모던 3줄 요약 카드 그래픽 노출. 하단에 원본 강의 구간 [{timestamp_str}] 배너 안내. (교수님 슬라이드 미사용 / 자체 요약 카드)",
                    'narration': f"오늘 배운 핵심 요약! '{hook_keyword}'의 기본 원리를 꼭 정리해 두세요. 더 자세한 설명과 풀이는 원본 영상 {timestamp_str} 구간에서 확인하실 수 있습니다!"
                }
            ],
            'key_takeaways': emp_kws[:3] if emp_kws else ([topic_or_concept] if topic_or_concept else [hook_keyword]),
            'source_id': top_hit['id']
        }

        return script

    # -------------------------------------------------------------------------
    # HTML Rendering Helper
    # -------------------------------------------------------------------------

    def render_shorts_html(self, script, out_file=None):
        """Render a clean preview HTML for the generated shorts script."""
        esc = html.escape
        acts_html = "".join(f"""
        <div class="act-card">
            <span class="act-badge">{esc(a['act'])} ({esc(a['seconds'])})</span>
            <p><strong>🎬 화면 연출:</strong> {esc(a['visual_direction'])}</p>
            <p><strong>🎙️ 나레이션:</strong> {esc(a['narration'])}</p>
        </div>
        """ for a in script['acts'])

        content = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{esc(script['title'])}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 700px; margin: 30px auto; padding: 20px; background: #0f172a; color: #f8fafc; line-height: 1.6; }}
h1 {{ color: #38bdf8; font-size: 22px; }}
.meta-bar {{ background: #1e293b; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; color: #94a3b8; }}
.act-card {{ background: #1e293b; border-left: 4px solid #38bdf8; padding: 16px; margin: 16px 0; border-radius: 6px; }}
.act-badge {{ display: inline-block; background: #0284c7; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; margin-bottom: 8px; }}
p {{ margin: 6px 0; font-size: 15px; }}
strong {{ color: #e2e8f0; }}
</style>
</head>
<body>
<h1>📱 숏츠 영상 대본: {esc(script['title'])}</h1>
<div class="meta-bar">
    ⏱️ 목표 시간: {script['target_seconds']}초 | 📍 출처: {esc(script['source_locator'])} | 🎬 원본 구간: {esc(script['original_video_timestamp'])}
</div>
{acts_html}
</body>
</html>"""
        if out_file:
            Path(out_file).write_text(content, encoding='utf-8')
        return content

    # -------------------------------------------------------------------------
    # HeyGen AI Video Avatar Export Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _convert_phonetic_pronunciation(text):
        """Convert common technical acronyms into Korean phonetic pronunciation hints for HeyGen TTS."""
        replacements = [
            (r'\bLIFO\b', '엘아이에프오(LIFO)'),
            (r'\bFIFO\b', '파이포(FIFO)'),
            (r'\bO\(1\)', '빅오 원'),
            (r'\bO\(n\)', '빅오 엔'),
            (r'\bO\(log\s*n\)', '빅오 로그 엔'),
            (r'\bOOP\b', '객체지향(OOP)'),
            (r'\bAPI\b', '에이피아이(API)'),
            (r'\bCLI\b', '씨엘아이(CLI)'),
            (r'\bGUI\b', '지유아이(GUI)'),
            (r'\bCPU\b', '씨피유(CPU)'),
            (r'\bbreak\b', '브레이크(break)'),
            (r'\bcontinue\b', '컨티뉴(continue)'),
            (r'\breturn\b', '리턴(return)'),
            (r'\bpush\b', '푸시(push)'),
            (r'\bpop\b', '팝(pop)'),
            (r'\bpeek\b', '피크(peek)')
        ]
        res = text
        for pat, rep in replacements:
            res = re.sub(pat, rep, res)
        return res

    def export_heygen_format(self, script, out_dir=None):
        """Export script into both HeyGen Studio copy-paste format and HeyGen API payload JSON."""
        out_path = Path(out_dir or self.output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        acts = script.get('acts', [])
        title = script.get('title', '숏츠 대본')
        loc = script.get('source_locator', '')
        time_str = script.get('original_video_timestamp', '')

        # 1. HeyGen Studio Text
        lines = [
            "=" * 70,
            f"📱 [헤이젠(HeyGen) 숏츠 영상 제작 전용 대본]",
            f"• 제목: {title}",
            f"• 화면 규격: 9:16 세로형 (1080 x 1920 Portrait)",
            f"• 아바타 속도: 1.1x 배속 (숏츠 최적화 빠른 템포)",
            f"• 출처 강의: {loc} (원본 구간: {time_str})",
            "=" * 70,
            ""
        ]

        layouts = [
            ("Scene 1 (Hook)", "아바타 화면 중앙 (Half Body / 1.0x)", "모던 텍스트 카드 UI (교수님 PPT 미사용 / 자체 그래픽)"),
            ("Scene 2 (Body)", "아바타 우측 하단 원형(Circle PiP 25%)", "다크 코드 에디터 창 또는 플랫 인포그래픽 75% (교수님 PPT 미사용 / 자체 그래픽)"),
            ("Scene 3 (Outro)", "아바타 하단 배치 (Half Body)", "핵심 3줄 요약 카드 그래픽 + 원본 타임라인 배너 (교수님 PPT 미사용 / 자체 그래픽)")
        ]

        for i, act in enumerate(acts):
            scene_name, layout, bg_guide = layouts[i] if i < len(layouts) else (f"Scene {i+1}", "아바타 중앙", "자체 제작 그래픽")
            narration_tts = self._convert_phonetic_pronunciation(act.get('narration', ''))
            graphic_text = act.get('screen_graphic', '')
            lines.extend([
                f"[{scene_name}: {act.get('seconds', '')}]",
                f"• 화면 연출 레이아웃: {layout}",
                f"• 배경 시각 자료: {bg_guide}",
                f"• 화면 표시 그래픽 내용 (캔바/AI 이미지/UI 제작용):\n{graphic_text}",
                f"• 상세 연출 가이드: {act.get('visual_direction', '')}",
                f"• 헤이젠 대사 입력 (복사 붙여넣기):",
                f"\"{narration_tts}\"",
                "",
                "-" * 50,
                ""
            ])

        txt_content = "\n".join(lines)
        txt_file = out_path / '헤이젠_대본_스튜디오용.txt'
        txt_file.write_text(txt_content, encoding='utf-8')

        # 2. HeyGen v2 API Payload JSON
        api_scenes = []
        for i, act in enumerate(acts):
            narration_tts = self._convert_phonetic_pronunciation(act.get('narration', ''))
            is_body = (i == 1)
            char_config = {
                "type": "avatar",
                "avatar_id": "Daisy-inskirt-20220818",
                "avatar_style": "circle" if is_body else "normal",
                "scale": 0.35 if is_body else 1.0,
                "offset": {"x": 0.35, "y": 0.35} if is_body else {"x": 0.0, "y": 0.0}
            }
            scene_payload = {
                "scene_index": i + 1,
                "act": act.get('act'),
                "character": char_config,
                "voice": {
                    "type": "text",
                    "input_text": narration_tts,
                    "speed": 1.1
                },
                "background": {
                    "type": "color",
                    "value": "#0f172a"
                }
            }
            api_scenes.append(scene_payload)

        api_payload = {
            "title": title,
            "dimension": {"width": 1080, "height": 1920},
            "aspect_ratio": "9:16",
            "video_inputs": api_scenes,
            "metadata": {
                "source_locator": loc,
                "original_video_timestamp": time_str,
                "target_seconds": script.get('target_seconds', 60)
            }
        }
        json_file = out_path / 'heygen_payload.json'
        save(json_file, api_payload)

        # 3. Canva Bulk Create CSV (캔바 대량제작 일괄 연동용 CSV)
        import csv
        canva_csv = out_path / 'canva_bulk_data.csv'
        with canva_csv.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Title',
                'Concept',
                'Hook_Narration',
                'Body_Graphic_Card',
                'Body_Narration',
                'Outro_Summary',
                'Outro_Narration',
                'Video_Timestamp'
            ])
            hook_act = acts[0] if len(acts) > 0 else {}
            body_act = acts[1] if len(acts) > 1 else {}
            outro_act = acts[2] if len(acts) > 2 else {}
            writer.writerow([
                title,
                script.get('concept', ''),
                self._convert_phonetic_pronunciation(hook_act.get('narration', '')),
                body_act.get('screen_graphic', '').replace('\n', ' | '),
                self._convert_phonetic_pronunciation(body_act.get('narration', '')),
                outro_act.get('screen_graphic', '').replace('\n', ' | '),
                self._convert_phonetic_pronunciation(outro_act.get('narration', '')),
                time_str
            ])

        return {
            'txt_file': txt_file,
            'json_file': json_file,
            'canva_csv': canva_csv,
            'txt_content': txt_content,
            'api_payload': api_payload
        }


