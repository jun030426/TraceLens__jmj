import { useEffect, useState } from 'react';
import { api } from './api';
import { ErrorNotice } from './components';
import { heldReason, sourceTime, type ExtractionReview, type HeldSource } from './extractionReview';
import './held-material-review.css';

export function HeldMaterialReview({materialId,versionId,heldCount=0}:{materialId:string;versionId:string;heldCount?:number}) {
  const [open,setOpen]=useState(false),[offset,setOffset]=useState(0),[modality,setModality]=useState('all');
  const [data,setData]=useState<ExtractionReview>(),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const [selected,setSelected]=useState<HeldSource|null>(null),[refresh,setRefresh]=useState(0);
  useEffect(()=>{setData(undefined);setOffset(0);setSelected(null);},[materialId,versionId,heldCount]);
  useEffect(()=>{
    if(!open)return;
    const abort=new AbortController();setLoading(true);setError('');setData(undefined);
    void api<ExtractionReview>(`/materials/${materialId}/extraction-review?version_id=${encodeURIComponent(versionId)}&offset=${offset}&limit=10&modality=${modality}`,{signal:abort.signal})
      .then(result=>{if(!abort.signal.aborted)setData(result);})
      .catch((e:Error)=>{if(!abort.signal.aborted)setError(e.message);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[open,materialId,versionId,heldCount,offset,modality,refresh]);
  const visible=data?.version_id===versionId ? data : undefined;
  const source=`/api/v1/materials/${materialId}/file?version_id=${encodeURIComponent(versionId)}`;
  return <details className="held-source-panel" onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary>
      <strong>보류 내용 보기{heldCount>0 ? ` · ${heldCount}건` : ''}</strong>
      <small className="held-source-explanation">보류된 내용은 검색·콘텐츠 생성에서 제외돼요. 정상 구간은 별도로 처리해요.</small>
    </summary>
    {open && <div className="held-source-body">
      <ErrorNotice text={error}/>
      <div className="held-source-tools"><label>구분<select value={modality} onChange={e=>{setModality(e.target.value);setOffset(0);setSelected(null);}}>
        <option value="all">전체</option><option value="audio">음성</option><option value="visual">영상 화면</option><option value="document">문서·코드</option>
      </select></label><button type="button" disabled={loading} onClick={()=>setRefresh(n=>n+1)}>목록 새로고침</button><a href={source} target="_blank" rel="noreferrer">원본 열기</a></div>
      {loading && <p role="status">보류 내용을 불러오는 중이에요…</p>}
      {visible?.available && <>
        <p className="held-source-count" role="status">사용 가능한 텍스트 {visible.usable_chunks}개 · 전체 보류 {visible.held_count}건</p>
        {!!visible.limitations?.length && <details><summary>기초 검사 범위</summary><ul>{visible.limitations.map(note=><li key={note}>{note}</li>)}</ul></details>}
        {selected && visible.is_video && <section className="held-source-player" aria-label="보류 구간 원본 영상">
          <div><strong>{sourceTime(selected.start_seconds)} 원본 확인</strong><button type="button" onClick={()=>setSelected(null)}>영상 닫기</button></div>
          <video key={`${versionId}:${selected.id}`} controls preload="metadata" src={source}
            onLoadedMetadata={e=>{e.currentTarget.currentTime=Math.min(selected.start_seconds||0,Math.max(0,e.currentTarget.duration-.1));}} />
        </section>}
        <ol className="held-source-list" aria-label="보류 항목" aria-busy={loading}>
          {!visible.review_queue.length && <li className="held-source-empty">{visible.held_count ? '이 구분에 해당하는 보류 내용이 없어요.' : '보류된 내용이 없어요.'}</li>}
          {visible.review_queue.map(item=><li key={item.id}>
            <div className="held-source-title"><strong>{item.modality==='audio'?'음성':item.modality==='visual'?'영상 화면':'문서·코드'}</strong><span>{item.source_locator || '원본 위치 확인 필요'}</span></div>
            <ul className="held-source-reasons">{item.reasons.map((r,i)=><li key={`${r}:${i}`}>{heldReason(r)}</li>)}</ul>
            {item.text ? <pre>{item.text}{item.text_truncated ? '\n… 긴 내용은 원본에서 확인해 주세요.' : ''}</pre> : <p className="muted">추출된 텍스트가 없어 원본을 확인해야 해요.</p>}
            {item.context && <details><summary>해당 부분의 원문 문맥</summary><pre>{item.context}</pre></details>}
            {visible.is_video && item.start_seconds!==null && <button type="button" onClick={()=>setSelected(item)}>{sourceTime(item.start_seconds)}부터 영상 확인</button>}
            <details><summary>상세 검사 코드</summary><code>{item.reasons.join(', ')}</code></details>
          </li>)}
        </ol>
        <nav className="held-source-pagination" aria-label="보류 목록 페이지"><button type="button" disabled={loading||offset===0} onClick={()=>setOffset(Math.max(0,offset-10))}>이전</button>
          <span>{visible.total ? `${offset+1}–${Math.min(offset+10,visible.total)} / ${visible.total}건` : '0건'}</span>
          <button type="button" disabled={loading||!visible.has_more} onClick={()=>setOffset(offset+10)}>다음</button></nav>
      </>}
      {!loading&&!error&&data&&!data.available&&<p>추출이 완료되면 보류 내용을 확인할 수 있어요.</p>}
    </div>}
  </details>;
}
