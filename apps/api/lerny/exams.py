"""Optional exam practice uses public sources, never private answer files."""
from fastapi import APIRouter, Header
from pydantic import Field, model_validator
from sqlalchemy import select
from lerny.auth import Input
from lerny.courses import view, audit
from lerny.security import Db, Actor, course_access, staff_access, match_revision, deny
from lerny.models import ExamPlan, Question, Chunk, MaterialVersion, Material
from lerny.learning import valid_sources, question_view
router=APIRouter(prefix="/api/v1")
class PlanInput(Input):
    title:str=Field(min_length=1,max_length=100)
    start_week:int=Field(ge=1,le=52)
    end_week:int=Field(ge=1,le=52)
    published:bool=False
    @model_validator(mode="after")
    def weeks(self):
        if self.end_week<self.start_week: raise ValueError("종료 주차를 확인해 주세요.")
        return self

def plan_view(plan):
    return view(plan,"id course_id title start_week end_week published revision")
@router.get("/courses/{course_id}/exam-plans")
def plans(course_id:str,session:Db,actor:Actor):
    course_access(session,actor,course_id)
    query=select(ExamPlan).where(ExamPlan.course_id==course_id)
    if actor.role=="student":query=query.where(ExamPlan.published.is_(True))
    return {"items":[plan_view(p) for p in session.scalars(query.order_by(ExamPlan.created_at.desc()))]}
@router.post("/courses/{course_id}/exam-plans",status_code=201)
def create(course_id:str,body:PlanInput,session:Db,actor:Actor):
    staff_access(session,actor,course_id)
    plan=ExamPlan(course_id=course_id,**body.model_dump());session.add(plan);session.flush()
    audit(session,actor,"exam_plan_created",plan.id);session.commit();return plan_view(plan)
@router.patch("/exam-plans/{plan_id}")
def update(plan_id:str,body:PlanInput,session:Db,actor:Actor,if_match:str|None=Header(default=None)):
    plan=session.scalar(select(ExamPlan).where(ExamPlan.id==plan_id).with_for_update())
    if not plan:deny(404)
    staff_access(session,actor,plan.course_id);match_revision(plan.revision,if_match)
    for key,value in body.model_dump().items():setattr(plan,key,value)
    plan.revision+=1;session.commit();return plan_view(plan)

def access_plan(session,actor,plan_id):
    plan=session.get(ExamPlan,plan_id)
    if not plan:deny(404)
    course_access(session,actor,plan.course_id)
    if actor.role=="student" and not plan.published:deny(404)
    return plan

def in_scope(session,plan,q):
    if q.course_id!=plan.course_id or q.status!="active" or not valid_sources(session,q):return False
    for source in q.sources:
        chunk=session.get(Chunk,source["chunk_id"])
        version=session.get(MaterialVersion,chunk.version_id)
        material=session.get(Material,version.material_id)
        if not plan.start_week<=material.week<=plan.end_week:return False
    return True
@router.get("/exam-plans/{plan_id}/practice")
def practice(plan_id:str,session:Db,actor:Actor):
    plan=access_plan(session,actor,plan_id)
    questions=[q for q in session.scalars(select(Question).where(Question.course_id==plan.course_id,Question.status=="active").order_by(Question.created_at.desc())) if in_scope(session,plan,q)][:30]
    resources=session.scalars(select(Material).where(Material.course_id==plan.course_id,Material.visibility=="public",Material.deleted.is_(False),Material.kind.in_(["past_exam","assignment"]),Material.week.between(plan.start_week,plan.end_week)))
    return {"plan":plan_view(plan),"questions":[question_view(q) for q in questions],"resources":[view(m,"id title kind week") for m in resources]}
class PracticeAnswer(Input):
    answer:str=Field(max_length=5000)
@router.post("/exam-plans/{plan_id}/questions/{question_id}/review")
def review(plan_id:str,question_id:str,body:PracticeAnswer,session:Db,actor:Actor):
    plan=access_plan(session,actor,plan_id);q=session.get(Question,question_id)
    if not q or not in_scope(session,plan,q):deny(404)
    correct=None
    if q.kind=="mcq":
        if body.answer not in [str(i) for i in range(len(q.options))]:deny(422)
        correct=int(body.answer)==q.solution["answer_index"]
    elif not body.answer.strip():deny(422)
    return {"correct":correct,"solution":q.solution,"message":"서술형은 해설과 채점 요소를 비교하며 복습하세요." if q.kind=="essay" else "정답이에요." if correct else "해설을 확인하고 다시 살펴보세요."}
