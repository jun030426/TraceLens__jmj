"""Local learning MVP; independent of the vector index lifecycle."""
from rag_mvp import ROOT

OUTPUT = ROOT / 'outputs/quiz-mvp'
CONCEPT_VERSION = 'stack-concepts-v1'
ANALYSIS_VERSION = 'offering-evidence-and-time-v3'
CONCEPTS = {
    'stack.lifo': '스택의 LIFO 원리',
    'stack.push': 'Push 연산',
    'stack.pop': 'Pop 연산',
    'stack.peek': 'Peek 연산',
    'stack.complexity': '스택 연산의 시간복잡도',
    'stack.underflow': '스택 언더플로',
}
DIFFICULTIES = {'basic': '기초', 'apply': '적용', 'reason': '심화'}
