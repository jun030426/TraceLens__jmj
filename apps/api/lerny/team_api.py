"""Small API contracts required by the latest teammate frontend."""
import json

from fastapi import APIRouter, Query
from sqlalchemy import select

from lerny.material_policy import student_source
from lerny.config import settings
from lerny.models import Chunk, Concept, Material, MaterialVersion
from lerny.security import Actor, Db, course_access, deny, staff_access
from lerny.team_ingestion import report_path

router = APIRouter(prefix="/api/v1", tags=["team-integration"])


@router.get("/materials/{material_id}/lecture-summary")
def lecture_summary(material_id: str, session: Db, actor: Actor, concept_id: str | None = None):
    material = session.get(Material, material_id)
    if not material or material.deleted:
        deny(404)
    course_access(session, actor, material.course_id)
    if actor.role == "student" and not student_source(material):
        deny(404)
    version = session.get(MaterialVersion, material.active_version_id) if material.active_version_id else None
    from lerny.weekly_content import published_generations
    from lerny.models import ContentGeneration
    generations=published_generations(session,material.course_id)
    generation=next((g for g in generations if any(s["material_id"]==material.id for s in g.sources)),None)
    if actor.role != "student":
        generation=session.scalar(select(ContentGeneration).where(ContentGeneration.course_id==material.course_id,
            ContentGeneration.week==material.week,ContentGeneration.status=="draft")) or generation
    if actor.role=="student" and not generation:
        return {"items":[]}
    if generation:
        source=next((s for s in generation.sources if s["material_id"]==material.id),None)
        version=session.get(MaterialVersion,source["version_id"]) if source else None
    if not version or version.status != "ready":
        return {"items": []}
    chunks = list(session.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    total = sum(len(c.content) for c in chunks)
    items = []
    evidence=generation.concept_evidence if generation else []
    for cid in (generation.concept_ids if generation else version.concept_ids) or []:
        if concept_id is not None and cid != concept_id:
            continue
        concept = session.get(Concept, cid)
        if not concept or concept.course_id != material.course_id:
            continue
        entry=next((e for e in evidence if e["id"]==cid),None)
        name=entry["name"] if entry else concept.name
        description=entry["description"] if entry else concept.description
        source_description = entry.get("source_description", description) if entry else description
        matched = [c for c in chunks if name in c.content and source_description in c.content]
        if not matched or not description.strip():
            continue
        locations = sorted({str((c.locator or {}).get("slide", (c.locator or {}).get("page", ""))) for c in matched} - {""})
        items.append({"concept_id": cid, "concept": name, "share": sum(len(c.content) for c in matched) / max(1, total),
                      "pages": ", ".join(locations), "points": [description],
                      "video_status": "planned"})
    return {"items": items, "share_basis": "matched_text_characters", "version_id": version.id}


@router.get("/materials/{material_id}/extraction-review")
def extraction_review(material_id: str, session: Db, actor: Actor,
                      offset: int = Query(0,ge=0), limit: int = Query(10,ge=1,le=50),
                      modality: str = Query('all',pattern='^(all|audio|visual|document)$'),
                      version_id: str | None = None):
    material = session.get(Material, material_id)
    if not material or material.deleted:
        deny(404)
    staff_access(session, actor, material.course_id, "read")
    version = session.scalar(select(MaterialVersion).where(MaterialVersion.material_id == material.id)
                             .order_by(MaterialVersion.version_no.desc()).limit(1))
    if version is None:
        return {"available": False, "held_count": 0}
    if version_id and version_id != version.id:
        deny(409, "자료 버전이 변경됐습니다. 목록을 새로고침해 주세요.")
    report = version.extraction_report
    if report is None and settings().deployment == "local" and report_path(version.id).is_file():
        report = json.loads(report_path(version.id).read_text(encoding="utf-8"))
    if report is None:
        return {"available": False, "held_count": 0}
    if report.get("source_sha256") != version.sha256:
        deny(409, "자료 버전이 변경됐습니다.")
    from lerny.extraction_review import normalized
    rows=[normalized(item,i) for i,item in enumerate(report['review_queue'])]
    filtered=[r for r in rows if modality=='all' or r['modality']==modality]
    evidence=report.get('native_evidence') or {}
    if not isinstance(evidence,dict):evidence={}
    return {"available": True, "version_id": version.id, "held_count": len(rows),
            "usable_chunks": report["usable_chunks"], "review_queue": filtered[offset:offset+limit],
            "total":len(filtered), "offset":offset,"limit":limit,"has_more":offset+limit<len(filtered),
            "pipeline":evidence.get('pipeline','native'), "limitations":evidence.get('limitations',[]),
            "is_video":version.filename.lower().endswith('.mp4')}
