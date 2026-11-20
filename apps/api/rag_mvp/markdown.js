'use strict';
document.addEventListener('click',async event=>{
  const button=event.target.closest('button[data-copy-code]');
  if(!button)return;
  const code=button.closest('.code-block')?.querySelector('pre code');
  if(!code)return;
  try{await navigator.clipboard.writeText(code.textContent);button.textContent='복사됨';}
  catch(_){button.textContent='코드를 선택해 복사하세요';}
  setTimeout(()=>{button.textContent='코드 복사';},1800);
});
