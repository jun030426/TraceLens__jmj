"""Turn existing decoded-scene findings into immutable extra visual tasks."""
from pathlib import Path
from video_extraction.shared import multimodal_checks
from video_extraction.shared.common import save,read,signature,digest_file


def expand(source,frames,metadata,folder,config):
    folder=Path(folder);path=folder/'supplemental-frames.json'
    binding=signature({'source':digest_file(source),'frames':frames,'metadata':metadata,
                       'scan_fps':config['scan_fps'],'implementation':digest_file(__file__)})
    if path.exists():
        receipt=read(path)
        if receipt['binding']!=binding:raise ValueError('supplemental_video_binding_changed')
        for f in receipt['added']:
            if digest_file(folder/f['path'])!=f['sha256']:raise ValueError('supplemental_video_image_changed')
        return frames+receipt['added']
    events,metrics=multimodal_checks.scan_video(source,frames,metadata,folder/'supplemental-scan',
        scan_fps=config['scan_fps'],frame_root=folder)
    targets=sorted({float(e[k]) for e in events if e['reason']=='possibly_unrepresented_scene_change'
        for k in ('start_seconds','end_seconds')
        if not any(abs(f['time_seconds']-e[k])<.001 for f in frames)})
    added=[];unresolved=[]
    if targets:
        import av
        index=0
        with av.open(str(source)) as container:
            for frame in container.decode(video=0):
                if index>=len(targets):break
                if frame.time is None:continue
                at=float(frame.time)-metadata['video_origin_seconds']
                while index<len(targets) and at>=targets[index]-.001:
                    wanted=targets[index];index+=1
                    if abs(at-wanted)>max(.15,2/max(1,metadata['fps'])):
                        unresolved.append({'requested':wanted,'reason':'source_frame_not_found'});continue
                    if any(abs(f['time_seconds']-at)<.001 for f in frames+added):continue
                    name='supplemental-'+signature([binding,at])[:20]
                    dest=folder/'frames'/(name+'.png');dest.parent.mkdir(parents=True,exist_ok=True)
                    frame.to_image().save(dest)
                    added.append({'id':name,'path':str(dest.relative_to(folder)),'time_seconds':at,
                                  'sha256':digest_file(dest),'origin':'decoded_scene_followup'})
        unresolved += [{'requested':t,'reason':'source_frame_not_found'} for t in targets[index:]]
    save(path,{'binding':binding,'original_findings':events,'metrics':metrics,'added':added,
               'unresolved':unresolved,'coverage_guarantee':False})
    return sorted(frames+added,key=lambda f:f['time_seconds'])
