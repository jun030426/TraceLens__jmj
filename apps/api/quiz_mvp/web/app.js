'use strict';
const $ = id => document.getElementById(id);
const text = (id,value) => {$(id).textContent=value;};
const levels = {basic:'기초',apply:'적용',reason:'심화'};
let student=JSON.parse(localStorage.getItem('quizMvpStudent')||'null');
let chatRows=[], chatBefore=null, chatPoll=null;
let offering=null, epoch=0, contextQueue=Promise.resolve(), hasMaterials=false;
let state=null, config=null, queue=Promise.resolve(), manualPaused=false, feedbackOpen=false, baseAt=performance.now();
function fail(error){if(error.contextChanged)return;text('error',error.message||String(error));$('error').hidden=false;}
function clearError(){$('error').hidden=true;}
async function api(path,data){
  const requestEpoch=epoch;
  const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Student-ID':student?.student_id||'','X-Offering-ID':offering||''},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();
  if(requestEpoch!==epoch){const e=new Error('강좌가 변경되었습니다.');e.contextChanged=true;throw e;}
  if(!response.ok){const e=new Error(result.error||'요청 실패');e.status=response.status;throw e;}
  return result;
}
function node(tag,value,cls){const e=document.createElement(tag);if(value!==undefined)e.textContent=value;if(cls)e.className=cls;return e;}
function remember(s){state=s;baseAt=performance.now();if(student)localStorage.setItem('quizMvpAttempt:'+student.student_id+':'+offering,s.attempt_id);}
function event(kind,extra={}){
  const qid=state?.question?.question_id, eventEpoch=epoch, aid=state?.attempt_id;
  const task=queue.then(async()=>{
    if(epoch!==eventEpoch||state?.attempt_id!==aid||!state||state.done||state.question?.question_id!==qid)return null;
    const payload={event_id:crypto.randomUUID(),revision:state.revision,question_id:qid,kind,...extra};
    let result;
    try{result=await api('/api/attempts/'+state.attempt_id+'/events',payload);}
    catch(e){if(e.status||e.contextChanged)throw e;result=await api('/api/attempts/'+state.attempt_id+'/events',payload);}
    remember(result);return result;
  });
  queue=task.catch(()=>{});return task;
}
function seconds(ms){return (ms/1000).toFixed(1)+'초';}
function updateClock(){
  if(!state?.timing||state.done||feedbackOpen)return;
  const t=state.timing,delta=Math.max(0,performance.now()-baseAt);
  text('active-time',seconds(t.active_ms+(t.active&&!manualPaused&&!document.hidden?Math.min(delta,15000):0)));
  text('elapsed-time',seconds(Math.max(0,t.last_ms-t.started_ms)+delta));
  text('timer-state',manualPaused||document.hidden?'일시정지':'측정 중');
}
async function renderQuestion(){
  if(state.done){renderSummary();return;}
  feedbackOpen=false;manualPaused=false;
  $('quiz').hidden=false;$('question-area').hidden=false;$('question-area').classList.remove('paused');
  $('feedback').hidden=true;$('next').hidden=true;$('hint-text').hidden=true;
  text('quiz-title',state.title);text('progress',`${state.number} / ${state.total}`);
  text('question-meta',`${config.concepts[state.question.concept_id]} · 예상 난이도 ${levels[state.question.difficulty]}`);
  text('stem',state.question.stem);text('pause','일시정지');
  $('options').replaceChildren(node('legend','정답 하나를 선택하세요'));
  state.question.options.forEach((value,i)=>{const label=node('label',undefined,'option');const input=node('input');input.type='radio';input.name='answer';input.value=String(i);label.append(input,node('span',value));$('options').append(label);});
  $('submit').disabled=false;$('hint').disabled=false;
  await event('shown');
  if(document.hidden)await event('pause');
  updateClock();
}
function feedbackBlock(r){
  const box=node('div',undefined,'result'+(r.correct?'':' wrong'));
  box.append(node('strong',r.correct?'정답입니다':'다시 확인해 보세요'),node('p','정답: '+r.options[r.answer_index]),node('p',r.explanation));
  box.append(node('p',`활성 ${seconds(r.active_ms)} · 경과 ${seconds(r.elapsed_ms)}${r.hint_used?' · 힌트 사용':''}${r.timing_valid?'':' · 시간 불확실 구간 있음'}`));
  box.append(node('small',`${r.source.file} · 슬라이드 ${r.source.slide}`),node('blockquote',r.source.quote));return box;
}
function renderSummary(){
  $('quiz').hidden=false;$('question-area').hidden=true;$('feedback').hidden=false;$('next').hidden=true;feedbackOpen=true;
  text('quiz-title',state.title+' · 완료');text('progress',`${state.summary.correct} / ${state.summary.total} 정답`);
  text('active-time',seconds(state.summary.active_ms));text('elapsed-time',seconds(state.summary.quiz_elapsed_ms));text('timer-state','완료');
  $('feedback').replaceChildren(...state.results.map(feedbackBlock));
}
async function library(){
  const quizzes=await api('/api/quizzes');$('quizzes').replaceChildren();
  if(!quizzes.length)$('quizzes').append(node('p','이 강좌에는 아직 퀴즈가 없습니다. 자료를 등록한 뒤 생성해 주세요.'));
  for(const q of quizzes){const card=node('div',undefined,'quiz-card'),desc=node('div');desc.append(node('strong',q.title),node('small',q.origin==='manual_demo'?'수동 예제 · API 생성 결과 아님':'Gemini + RAG 생성 · 자동 검증 통과'));
    const button=node('button','풀기 / 이어 풀기');button.onclick=async()=>{clearError();try{if(state&&!state.done&&!feedbackOpen)await event('pause');remember(await api('/api/attempts',{quiz_id:q.quiz_id}));await renderQuestion();$('quiz').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){fail(e);}};
    card.append(desc,button);$('quizzes').append(card);}
}
async function analysis(){
  const a=await api('/api/analysis');text('analysis-notice',a.notice+` 전체 제출 ${a.total_responses}회 · 서로 다른 문제 ${a.unique_items}개`);text('time-notice',a.timing_notice);
  const table=node('table'),head=node('thead'),hr=node('tr');['개념','첫 풀이 정답','활성시간 중앙값','학습 신호','시간 신호'].forEach(v=>hr.append(node('th',v)));head.append(hr);table.append(head);
  const body=node('tbody');for(const c of a.concepts){const tr=node('tr');[c.label,`${c.correct}/${c.unique_questions}${c.hint_excluded?' · 힌트 '+c.hint_excluded+'개 제외':''}`,c.median_active_seconds===null?'—':c.median_active_seconds+'초',c.status,c.time_signal].forEach(v=>tr.append(node('td',v)));body.append(tr);}table.append(body);$('analysis').replaceChildren(table);
}
function resetLearning(){chatRows=[];chatBefore=null;chatPoll=null;$('chat-messages').replaceChildren();$('chat-older').hidden=true;$('chat-question').value='';$('chat-send').disabled=true;text('chat-status','');state=null;feedbackOpen=false;manualPaused=false;$('quiz').hidden=true;$('quizzes').replaceChildren();$('analysis').replaceChildren();text('analysis-notice','');text('time-notice','');text('job-status','');text('shorts-status','');}
async function materials(){
  const rows=await api('/api/materials'),active=rows.find(x=>x.active);hasMaterials=!!active;
  text('material-status',active?`현재 강좌 자료 ${active.chunk_count}개 청크 · 저장 버전 ${rows.length}개`:'이 강좌에 등록된 자료가 없습니다. 다른 강좌의 자료는 자동으로 사용하지 않습니다.');
  $('generate').disabled=config.offline||!hasMaterials;
  $('chat-send').disabled=config.offline||!hasMaterials||chatRows.some(r=>r.state==='pending');
}
async function activateCourse(oid){
  if(state&&!state.done&&!feedbackOpen)await event('pause');await queue;
  epoch++;offering=oid;resetLearning();$('generate').disabled=true;
  // Local test self-enrollment is explicit in the selected offering, not production authorization.
  await api('/api/enrollments',{offering_id:oid});
  const c=await api('/api/course');config.concepts=c.concepts;
  $('course-select').value=oid;localStorage.setItem('quizMvpCourse:'+student.student_id,oid);
  text('course-status',`${c.subject_name} (${c.subject_code}) · ${c.semester} · ${c.section}분반`);
  for(const id of ['concept','shorts-concept']){
    $(id).replaceChildren();if(id==='concept'){const o=node('option','현재 강좌 전체');o.value='';$(id).append(o);}
    for(const [cid,label] of Object.entries(c.concepts)){const o=node('option',label);o.value=cid;$(id).append(o);}
  }
  await materials();await loadChat();await library();await analysis();
  const key='quizMvpAttempt:'+student.student_id+':'+offering;
  // One-time browser-state migration; legacy attempts belong only to the default offering.
  if(offering===config.default_offering&&!localStorage.getItem(key)){
    const old=localStorage.getItem('quizMvpAttempt:'+student.student_id);if(old)localStorage.setItem(key,old);
  }
  const aid=localStorage.getItem(key);
  if(aid){try{remember(await api('/api/attempts/'+aid));await renderQuestion();}catch(e){if(e.contextChanged)throw e;if([400,403].includes(e.status))localStorage.removeItem(key);else throw e;}}
}
function changeCourse(oid){
  const sid=student?.student_id;
  const task=contextQueue.then(()=>{if(student?.student_id!==sid)return;return activateCourse(oid);});contextQueue=task.catch(()=>{});return task;
}
async function loadCourses(preferred){
  const courses=await api('/api/courses');$('course-select').replaceChildren();
  for(const c of courses){const o=node('option',`${c.subject_name} · ${c.semester} · ${c.section}분반${c.enrolled?'':' (선택 시 테스트 등록)'}`);o.value=c.id;$('course-select').append(o);}
  const wanted=preferred||localStorage.getItem('quizMvpCourse:'+student.student_id);
  await changeCourse(courses.some(c=>c.id===wanted)?wanted:config.default_offering);
}
async function workspace(){
  $('profile').hidden=!!student;$('workspace').hidden=!student;if(!student)return;
  text('student-name',student.name+' · 테스트 학습자');await loadCourses();
}
$('course-select').onchange=()=>changeCourse($('course-select').value).catch(fail);
$('course-form').onsubmit=async e=>{e.preventDefault();clearError();try{
  const concepts={};for(const line of $('course-concepts').value.split('\n').filter(x=>x.trim())){
    const i=line.indexOf('=');if(i<1)throw new Error('개념은 ID=이름 형식으로 입력하세요.');
    const key=line.slice(0,i).trim();if(Object.hasOwn(concepts,key))throw new Error('중복 개념 ID입니다.');concepts[key]=line.slice(i+1).trim();
  }
  const course=await api('/api/courses',{subject_code:$('subject-code').value,subject_name:$('subject-name').value,semester:$('semester').value,section:$('section-name').value,concepts});
  await loadCourses(course.id);
}catch(e){fail(e);}};
$('use-fixture').onclick=async()=>{clearError();try{await api('/api/materials',{use_legacy_fixture:true});await materials();}catch(e){fail(e);}};
$('material-file').onchange=async()=>{clearError();const file=$('material-file').files[0],fileEpoch=epoch;if(!file)return;try{
  if(file.size>8*1024*1024)throw new Error('8MB 이하의 검증된 JSON을 등록하세요.');
  const corpus=JSON.parse(await file.text());if(fileEpoch!==epoch)return;
  await api('/api/materials',{corpus});await materials();
}catch(e){fail(e);}finally{$('material-file').value='';}};
$('profile-form').onsubmit=async e=>{e.preventDefault();clearError();try{student=await api('/api/students',{name:$('name').value});localStorage.setItem('quizMvpStudent',JSON.stringify(student));const known=JSON.parse(localStorage.getItem('quizMvpProfiles')||'[]');known.push(student);localStorage.setItem('quizMvpProfiles',JSON.stringify(known));await workspace();}catch(e){fail(e);}};
$('switch-profile').onclick=async()=>{try{await contextQueue;if(state&&!state.done&&!feedbackOpen)await event('pause');epoch++;student=null;offering=null;resetLearning();localStorage.removeItem('quizMvpStudent');$('quiz').hidden=true;showProfiles();await workspace();}catch(e){fail(e);}};
function showProfiles(){let box=$('saved-profiles');if(!box){box=node('div');box.id='saved-profiles';$('profile').append(box);}box.replaceChildren();for(const p of JSON.parse(localStorage.getItem('quizMvpProfiles')||'[]')){const b=node('button',p.name,'secondary');b.onclick=async()=>{student=p;localStorage.setItem('quizMvpStudent',JSON.stringify(p));try{await workspace();}catch(e){fail(e);}};box.append(b);}}
$('submit').onclick=async()=>{clearError();const selected=document.querySelector('input[name=answer]:checked');if(!selected){fail(new Error('정답 하나를 선택해 주세요.'));return;}
  $('submit').disabled=true;try{const r=await event('submit',{selected:Number(selected.value)});if(!r)return;feedbackOpen=true;$('question-area').hidden=true;$('feedback').hidden=false;$('feedback').replaceChildren(feedbackBlock(r.feedback));text('active-time',seconds(r.feedback.active_ms));text('elapsed-time',seconds(r.feedback.elapsed_ms));text('timer-state','제출 완료');$('next').hidden=false;text('next',r.done?'전체 결과 보기':'다음 문제');await analysis();}catch(e){$('submit').disabled=false;fail(e);}};
$('next').onclick=()=>renderQuestion().catch(fail);
$('pause').onclick=async()=>{try{manualPaused=!manualPaused;await event(manualPaused?'pause':'resume');$('question-area').classList.toggle('paused',manualPaused);$('submit').disabled=manualPaused;$('hint').disabled=manualPaused;text('pause',manualPaused?'계속 풀기':'일시정지');updateClock();}catch(e){fail(e);}};
$('hint').onclick=async()=>{try{const r=await event('hint');if(r){text('hint-text',r.hint);$('hint-text').hidden=false;}}catch(e){fail(e);}};
$('refresh-analysis').onclick=()=>analysis().catch(fail);
document.addEventListener('visibilitychange',()=>{if(!state||state.done||feedbackOpen)return;event(document.hidden?'pause':manualPaused?'pause':'resume').catch(fail);});
window.addEventListener('blur',()=>{if(state&&!state.done&&!feedbackOpen)event('pause').catch(fail);});
window.addEventListener('focus',()=>{if(state&&!state.done&&!feedbackOpen&&!document.hidden&&!manualPaused)event('resume').catch(fail);});
window.addEventListener('pagehide',()=>{if(!state||state.done||feedbackOpen)return;const p={event_id:crypto.randomUUID(),revision:state.revision,question_id:state.question.question_id,kind:'pause'};fetch('/api/attempts/'+state.attempt_id+'/events',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-Student-ID':student.student_id,'X-Offering-ID':offering||''},body:JSON.stringify(p)}).catch(()=>{});});
setInterval(()=>{if(state&&!state.done&&!feedbackOpen&&!document.hidden&&!manualPaused)event('heartbeat').catch(fail);},5000);
setInterval(updateClock,200);
$('generate').onclick=async()=>{
  const jobEpoch=epoch;clearError();$('generate').disabled=true;
  try{if(state&&!state.done&&!feedbackOpen){await event('pause');manualPaused=true;$('question-area').classList.add('paused');text('pause','계속 풀기');}
    if(jobEpoch!==epoch)return;
    const job=await api('/api/generate',{concept_id:$('concept').value||null});let status;
    do{await new Promise(resolve=>setTimeout(resolve,1500));status=await api('/api/jobs/'+job.job_id);text('job-status',status.message);}while(status.state==='running');
    if(status.state!=='complete')throw new Error(status.message);await library();
  }catch(e){fail(e);}finally{if(jobEpoch===epoch)$('generate').disabled=config.offline||!hasMaterials;}
};
function chatRequestKey(){return 'quizMvpChatRequest:'+student.student_id+':'+offering;}
function renderChat(){
  const blocks=chatRows.map(turn=>{
    const article=node('article',undefined,'chat-turn');article.append(node('p','학생: '+turn.question,'chat-question'));
    if(turn.state==='pending')article.append(node('p','자료 검색·답변 생성 중입니다.','chat-meta'));
    else if(turn.state==='failed'){
      article.append(node('p',turn.error||'답변 생성 실패','chat-meta'));
      const retry=node('button','질문 다시 입력','secondary');retry.type='button';retry.onclick=()=>{$('chat-question').value=turn.question;};article.append(retry);
    }else{
      const r=turn.result;
      if(r.status!=='citation_checked')article.append(node('p',r.reason,'chat-answer'));
      for(const c of r.claims||[]){
        const answer=node('div',undefined,'chat-answer markdown-body');
        // HTML is generated from raw text by the server's HTML-disabled parser.
        if(typeof c.markdown_html==='string')answer.innerHTML=c.markdown_html;
        else answer.textContent=c.text;
        article.append(answer);
        const source=node('details'),label=node('summary',`${c.source_file} · ${c.source_locator||'슬라이드 '+c.slide_number}`);source.append(label,node('blockquote',c.quote));article.append(source);
      }
      const p=r.personalization||{};article.append(node('p',`참고한 이전 대화 ${p.history_turns_used||0}개 · 해당 강좌의 학습 기록 반영`,'chat-meta'));
    }
    return article;
  });
  $('chat-messages').replaceChildren(...blocks);$('chat-older').hidden=!chatBefore;
  const pending=chatRows.find(r=>r.state==='pending');$('chat-send').disabled=config.offline||!hasMaterials||!!pending;
  text('chat-status',pending?'답변 생성 중 · 다른 강좌로 이동해도 서버에서 계속 처리합니다.':config.offline?'오프라인 모드: 저장된 대화만 확인할 수 있습니다.':!hasMaterials?'이 강좌에 자료를 먼저 등록해 주세요.':'');
}
async function watchChat(id){
  const token={id,epoch};chatPoll=token;
  try{
    while(token===chatPoll&&token.epoch===epoch){
      await new Promise(resolve=>setTimeout(resolve,1500));if(token!==chatPoll||token.epoch!==epoch)return;
      const turn=await api('/api/chat/'+id);chatRows=chatRows.map(r=>r.id===id?turn:r);renderChat();
      if(turn.state!=='pending')return;
    }
  }catch(e){fail(e);if(token.epoch===epoch)text('chat-status','진행 상태를 확인하지 못했습니다. 새로고침하면 저장된 대화와 진행 상태를 다시 불러옵니다.');}
  finally{if(chatPoll===token)chatPoll=null;}
}
async function loadChat(older=false){
  const page=await api('/api/chat'+(older&&chatBefore?'?before='+chatBefore:''));
  chatRows=older?[...page.turns,...chatRows]:page.turns;chatBefore=page.next_before;renderChat();
  const pending=chatRows.find(r=>r.state==='pending');if(pending&&chatPoll?.id!==pending.id)watchChat(pending.id);
}
$('chat-older').onclick=()=>loadChat(true).catch(fail);
$('chat-form').onsubmit=async e=>{
  e.preventDefault();clearError();const question=$('chat-question').value;if(!question.trim())return;
  const requestEpoch=epoch,key=chatRequestKey();$('chat-send').disabled=true;
  try{
    if(state&&!state.done&&!feedbackOpen){await event('pause');manualPaused=true;$('question-area').classList.add('paused');$('submit').disabled=true;$('hint').disabled=true;text('pause','계속 풀기');}
    if(requestEpoch!==epoch)return;
    let data=JSON.parse(localStorage.getItem(key)||'null');if(!data||data.question!==question)data={request_id:crypto.randomUUID(),question};
    localStorage.setItem(key,JSON.stringify(data));
    const turn=await api('/api/chat',data);localStorage.removeItem(key);$('chat-question').value='';
    chatRows=chatRows.filter(r=>r.id!==turn.id);chatRows.push(turn);renderChat();
    if(turn.state==='pending')watchChat(turn.id);
  }catch(e){fail(e);}
  finally{if(requestEpoch===epoch)$('chat-send').disabled=config.offline||!hasMaterials||chatRows.some(r=>r.state==='pending');}
};
$('shorts').onclick=async()=>{try{const data=await api('/api/shorts',{concept_id:$('shorts-concept').value});const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download='shorts-learning-request.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);text('shorts-status','개념·분석·출제 근거를 저장했습니다. 영상 생성은 아직 연결하지 않았습니다.');}catch(e){fail(e);}};
(async()=>{try{config=await api('/api/config');if(config.scope_version!==2||config.chat_version!==1)throw new Error('터미널 서버를 Ctrl+C로 종료하고 퀴즈_학습분석_실행.command를 다시 실행한 뒤 새로고침해 주세요.');$('course-concepts').value=Object.entries(config.concepts).map(([id,label])=>id+'='+label).join('\n');$('generate').disabled=config.offline;if(config.offline)text('job-status','현재 오프라인 확인 모드: 예제 풀이와 학습 분석을 테스트할 수 있습니다.');showProfiles();await workspace();}catch(e){fail(e);}})();
