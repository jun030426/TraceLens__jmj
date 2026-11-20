// DOM/request unit harness, not a browser or a live server connection.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.hidden=false;this.classList={add(){},toggle(){},remove(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  scrollIntoView(){} click(){}
}
const elements=new Map(),storage=new Map([
 ['quizMvpStudent',JSON.stringify({student_id:'student-a',name:'테스트'})],
 ['quizMvpAttempt:student-a','old-attempt']
]);
const requests=[];let delayed=null, delayedChat=null;
const context=vm.createContext({
 console,URL,Blob,crypto:require('node:crypto').webcrypto,performance,
 setInterval(){},setTimeout,
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 document:{getElementById(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);},
 createElement:tag=>new Element(tag),addEventListener(){},hidden:false,querySelector(){return null;}},
 window:{addEventListener(){}},
 fetch:async(path,options)=>{
  const oid=options.headers['X-Offering-ID'];requests.push({path,oid,options});
  if(delayed&&path==='/api/quizzes'&&oid==='legacy-stack')return new Promise(resolve=>{delayed.resolve=resolve;});
  if(delayedChat&&path==='/api/chat'&&oid==='other')return new Promise(resolve=>{delayedChat.resolve=resolve;});
  let result;
  if(path==='/api/config')result={scope_version:2,chat_version:1,default_offering:'legacy-stack',concepts:{'stack.pop':'Pop'},offline:true};
  else if(path==='/api/chat')result={turns:[],next_before:null};
  else if(path==='/api/courses')result=['legacy-stack','other'].map(id=>({id,subject_name:id,semester:'2026-2',section:'01',enrolled:1}));
  else if(path==='/api/enrollments')result={enrolled:true};
  else if(path==='/api/course')result={id:oid,concepts:{'stack.pop':'Pop'},subject_name:oid,subject_code:'CS',semester:'2026-2',section:'01'};
  else if(path==='/api/materials'||path==='/api/quizzes')result=[];
  else if(path==='/api/analysis')result={notice:'',timing_notice:'',total_responses:0,unique_items:0,concepts:[]};
  else if(path==='/api/attempts/old-attempt')return {ok:false,status:400,json:async()=>({error:'기록 없음'})};
  else throw new Error('Unexpected '+path);
  return {ok:true,json:async()=>result};
 }
});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInContext(fs.readFileSync(__dirname+'/web/app.js','utf8'),context);
 for(let n=0;n<10;n++)await flush();
 assert.equal(vm.runInContext('offering',context),'legacy-stack');
 assert(requests.some(r=>r.path==='/api/attempts/old-attempt'&&r.oid==='legacy-stack'));
 delayed={};const oldLibrary=vm.runInContext('library()',context).catch(e=>e);await flush();
 await vm.runInContext("changeCourse('other')",context);
 delayed.resolve({ok:true,json:async()=>[{quiz_id:'old',title:'LEAKED',origin:'manual_demo'}]});
 const discarded=await oldLibrary;assert.equal(discarded.contextChanged,true);delayed=null;
 assert(!elements.get('quizzes').children.some(x=>x.textContent==='LEAKED'));
 assert(!requests.some(r=>r.path==='/api/attempts/old-attempt'&&r.oid==='other'));
 vm.runInContext("remember({attempt_id:'other-attempt',offering_id:'other'})",context);
 assert.equal(storage.get('quizMvpAttempt:student-a:other'),'other-attempt');
 assert.equal(storage.get('quizMvpCourse:student-a'),'other');
 assert(requests.filter(r=>['/api/materials','/api/quizzes','/api/analysis','/api/course'].includes(r.path)).every(r=>!!r.oid));
 delayedChat={};const oldChat=vm.runInContext('loadChat()',context).catch(e=>e);await flush();
 vm.runInContext('state=null',context);
 await vm.runInContext("changeCourse('legacy-stack')",context);
 delayedChat.resolve({ok:true,json:async()=>({turns:[{id:'private-other-chat',state:'pending',question:'OTHER PRIVATE'}],next_before:null})});
 assert.equal((await oldChat).contextChanged,true);delayedChat=null;
 assert.equal(vm.runInContext('chatRows.length',context),0);
 console.log('Frontend unit checks passed: scoped headers, legacy resume, isolated resume keys, stale response rejection.');
})().catch(e=>{console.error(e);process.exitCode=1;});
