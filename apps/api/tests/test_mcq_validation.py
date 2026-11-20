from types import SimpleNamespace
import pytest
from lerny.assessment import verify_choice


@pytest.mark.parametrize('selected', [[], ['FILO', 'push adds at top'], ['FILO'],
    ['push adds at top','push adds at top'], 'push adds at top'])
def test_multiple_equivalent_or_missing_answers_do_not_pass(monkeypatch, selected):
    q=SimpleNamespace(prompt='Which statement about a stack is correct?',
        options=['FIFO','FILO','push adds at top','pop removes bottom'],answer_index=2)
    monkeypatch.setattr('lerny.worker.model_json',lambda *_:{'correct_options':selected})
    with pytest.raises(ValueError,match='ANSWER_KEY_MISMATCH'):
        verify_choice(q,[])


def test_exactly_one_supported_answer_is_required(monkeypatch):
    q=SimpleNamespace(prompt='What does push do?',options=['remove','add at top','sort','read'],answer_index=1)
    monkeypatch.setattr('lerny.worker.model_json',lambda *_:{'correct_options':['add at top']})
    verify_choice(q,[])
