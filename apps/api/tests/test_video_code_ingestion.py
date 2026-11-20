"""Synthetic, isolated source-to-practice checks. No cloud, live AI, or host code execution."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from lerny import local_media, local_media_checks, local_ocr, practice, video_code, weekly_content, worker
from lerny.models import Chunk, ContentGeneration, Job, Material, MaterialVersion, PracticeExercise
from test_gemini_integration import api, configured, integration, fake_provider  # noqa: F401
from test_weekly_publication import weekly  # noqa: F401
from test_weekly_without_video import finish

CODE = "numbers = [1, 2]\ntotal = sum(numbers)\nprint(total)"


def reading(code=CODE):
    result=[]
    step=min(25,800/len(code.splitlines()))
    for i,line in enumerate(code.splitlines()):
        indent=len(line)-len(line.lstrip(" "))
        text=line[indent:]
        x=100+indent*8
        result.append({"text":text,"bbox":[x,100+i*step,x+len(text)*8,100+i*step+step*.8],
                       "min_confidence":99,"mean_confidence":99,
                       "words":[{"text":text,"bbox":[x,100+i*step,x+len(text)*8,100+i*step+step*.8],"confidence":99}]})
    return result


def verified(tmp_path, monkeypatch, code=CODE, second=None):
    image=tmp_path/"frame.png"
    Image.new("RGB",(2000,1000),"white").save(image)
    monkeypatch.setattr(local_ocr,"recognize",lambda *args:reading(code if second is None else second))
    records,consumed=video_code.verify_frame(image,tmp_path/"ocr",{"psm":3},reading(code),10,20,"frame")
    return image,records,consumed


def test_indented_block_is_source_bound_and_cache_is_reused(tmp_path,monkeypatch):
    code="numbers = [1, 2]\ntotal = 0\nfor number in numbers:\n    total += number\nprint(total)"
    image,records,consumed=verified(tmp_path,monkeypatch,code)
    assert len(records)==1 and consumed==set(range(5))
    assert records[0]["text"]=="\x60\x60\x60python\n"+code+"\n\x60\x60\x60"
    assert records[0]["code_block"]["execution_verified"] is False
    before={p.name:p.read_bytes() for p in (tmp_path/"ocr").glob("*.json")}
    monkeypatch.setattr(local_ocr,"recognize",lambda *a:pytest.fail("Repeated OCR despite valid cache"))
    repeated,_=video_code.verify_frame(image,tmp_path/"ocr",{"psm":3},reading(code),10,20,"frame")
    assert repeated==records and before=={p.name:p.read_bytes() for p in (tmp_path/"ocr").glob("*.json")}
    records[0]["text"]=records[0]["text"].replace("[1, 2]","[9, 2]")
    with pytest.raises(ValueError,match="VIDEO_CODE_PROOF_INVALID"):
        local_media_checks.build_chunks(records,"source")


@pytest.mark.parametrize("mutation",["literal","indent","confidence","incomplete","tamper"])
def test_uncertain_code_never_bypasses_original_review(tmp_path,monkeypatch,mutation):
    image=tmp_path/"frame.png";Image.new("RGB",(2000,1000),"white").save(image)
    first=reading()
    second=reading(CODE.replace("[1, 2]","[1, 7]")) if mutation=="literal" else reading()
    if mutation=="indent":first[1]["bbox"][0]+=3.9
    if mutation=="confidence":first[0]["min_confidence"]=40
    if mutation=="incomplete":first=reading("total = sum(numbers)\nprint(total)")
    monkeypatch.setattr(local_ocr,"recognize",lambda *a:second)
    if mutation=="tamper":
        records,_=video_code.verify_frame(image,tmp_path/"ocr",{"psm":3},first,0,1,"frame")
        assert records
        receipt=next((tmp_path/"ocr").glob("*.json"))
        value=json.loads(receipt.read_text());value["second_reading"][0]["text"]="numbers = [9, 9]"
        receipt.write_text(json.dumps(value))
    records,consumed=video_code.verify_frame(image,tmp_path/"ocr",{"psm":3},first,0,1,"frame")
    assert not records and not consumed
    original=local_media_checks.ocr_records(first,0,1,"frame")
    assert any(not row["eligible_for_chunking"] for row in original)


def test_complete_code_is_not_split_at_generic_text_chunk_limit(tmp_path,monkeypatch):
    code="numbers = [1, 2]\n"+"\n".join(f"value_{i} = sum(numbers) + {i}" for i in range(65))+"\nprint(value_64)"
    assert len(code)>1800
    _,records,_=verified(tmp_path,monkeypatch,code)
    row=records[0]
    chunks=local_media_checks.build_chunks([row],"source")
    assert len(chunks)==1 and code in chunks[0]["text"]


def test_real_media_entry_point_then_embedding_then_both_practice_kinds(weekly,configured,fake_provider,tmp_path,monkeypatch):
    """Real pipeline/APIs, synthetic OCR/model/sandbox replies are explicit."""
    from lerny.team_ingestion import publish_extraction
    client,session,_=weekly
    configured.heygen_rendering_enabled=False
    source=tmp_path/"source.mp4";source.write_bytes(b"synthetic source identity")
    checksum=hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(local_media.media,"probe",lambda p:{"duration_seconds":20,"width":2000,"height":1000,"audio_present":False})
    def frames(path,out,metadata,options,progress):
        Image.new("RGB",(2000,1000),"white").save(out/"frame.png")
        return [{"id":"frame","time_seconds":0,"path":"frame.png"}]
    monkeypatch.setattr(local_media.media,"select_frames",frames)
    monkeypatch.setattr(local_ocr,"runtime",lambda:{"psm":3})
    monkeypatch.setattr(local_ocr,"recognize",lambda *a:reading())
    result=local_media.process(source,tmp_path/"media",checksum,lambda:None,lambda *a:None)
    assert result["evidence"]["api_calls"]==0 and len(result["chunks"])==1
    version=session.get(MaterialVersion,"version");material=session.get(Material,"material")
    version.filename="lecture.mp4";version.sha256=checksum
    job=Job(owner_id="teacher",course_id="course",kind="extract",payload={"version_id":version.id})
    session.add(job);session.flush()
    publish_extraction(session,job,version,material,{"source_sha256":checksum},result["chunks"],result["held"],result["evidence"])
    session.commit()
    embed=session.scalar(select(Job).where(Job.kind=="embed"))
    finish(session,embed)
    assert version.status=="ready"
    assert not session.scalars(select(ContentGeneration)).all()
    assert not session.scalars(select(Job).where(Job.kind.in_(["weekly_content","practice_prepare","narration_lesson"]))).all()
    chunks=session.scalars(select(Chunk).where(Chunk.version_id==version.id)).all()
    assert len(chunks)==1 and CODE in chunks[0].content
    sources=weekly_content.source_snapshot(session,"course",1)
    generation=ContentGeneration(course_id="course",week=1,owner_id="teacher",sources=sources,
        source_hash=weekly_content.source_hash(sources),options={"video_mode":"none","videos":False,"practice":True})
    session.add(generation);session.flush()
    task=Job(owner_id="teacher",course_id="course",kind="practice_prepare",
             payload={"generation_id":generation.id,"source_version_id":version.id,"source_version_ids":[version.id]})
    session.add(task);session.commit()
    def model(prompt,schema):
        data=json.loads(prompt.rsplit("\n",1)[1])
        assert data["sources"]==[{"source_id":chunks[0].id,"text":chunks[0].content}]
        return {"programs":[{"source_id":chunks[0].id,"concept_id":None,"code":CODE,
            "title":"숫자 합 계산","prompt":"주어진 숫자 배열의 합을 계산하고 출력하세요.",
            "input_statement":"numbers = [1, 2]","variants":["numbers = [3, 4]","numbers = [0, 0]"],
            "blank_lines":[2],"full_template":"numbers = [1, 2]\n# 합을 계산하고 출력하세요."}]}
    monkeypatch.setattr(worker,"model_json",model)
    calls=[]
    def sandbox(lang,code,**kwargs):
        calls.append(code)
        # Synthetic sandbox protocol result; never exec/eval the extracted program.
        return "7" if "[3, 4]" in code else "0" if "[0, 0]" in code else "3"
    monkeypatch.setattr(practice,"output_of",sandbox)
    completed=practice.prepare(session,task)
    assert completed["status"]=="ready" and not completed["held"] and len(calls)==3
    exercises=session.scalars(select(PracticeExercise).where(PracticeExercise.generation_id==generation.id)).all()
    assert {e.kind for e in exercises}=={"blank","full"}
    assert all(e.version_id==version.id and e.reference==CODE and len(e.tests)==3 for e in exercises)
    assert all(e.sources==[{"chunk_id":chunks[0].id,"quote":CODE}] for e in exercises)
    assert len(fake_provider)==1 and fake_provider[0][0].endswith(":embedContent")


def test_numeric_stdin_video_block_uses_existing_adapter_without_changing_logic(tmp_path,monkeypatch):
    from lerny.practice_inputs import numeric_source
    code='a = int(input("A: "))\nb = int(input("B: "))\nprint(a + b)'
    _,records,_=verified(tmp_path,monkeypatch,code)
    assert len(records)==1
    parsed=numeric_source(records[0]["text"])
    assert parsed["code"]==code and [i["name"] for i in parsed["inputs"]]==["a","b"]


def test_code_confidence_gate_keeps_weak_symbols_held_and_preserves_string_spaces():
    lines=reading()
    lines[0]['min_confidence']=79
    with pytest.raises(ValueError,match='VIDEO_CODE_LOW_CONFIDENCE'):video_code.reading(lines)
    assert video_code.code_tokens('x = 1\nprint(x)')==video_code.code_tokens('x=1\nprint (x)')
    assert video_code.code_tokens('x = "a b"\nprint(x)')!=video_code.code_tokens('x = "ab"\nprint(x)')


def test_cancelled_source_stops_before_additional_ocr(tmp_path,monkeypatch):
    image=tmp_path/'frame.png';Image.new('RGB',(2000,1000),'white').save(image)
    monkeypatch.setattr(local_ocr,'recognize',lambda *a:pytest.fail('OCR after source cancellation'))
    def cancelled():raise ValueError('SOURCE_REVOKED')
    with pytest.raises(ValueError,match='SOURCE_REVOKED'):
        video_code.verify_frame(image,tmp_path/'ocr',{'psm':3},reading(),0,1,'frame',check=cancelled)

