"""Visible embedded PPT picture text; original OOXML/native chunks stay intact."""
import io
import posixpath
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image
from rag_mvp.document_ingest import NS, P, R
from lerny import local_ocr, picture_ocr
from video_extraction.shared.common import digest_file, signature


def pictures(path, folder, allowed):
    """Extract only visible, uncropped top-level raster pictures already held by XML.

    Cropped pictures are cropped to their displayed rectangle. Rotation, groups,
    effects and overlaid shapes remain explicit review items, never hidden text.
    """
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    found=[]
    with zipfile.ZipFile(path) as package:
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(package.read('ppt/_rels/presentation.xml.rels')) if r.get('TargetMode')!='External'}
        root=ET.fromstring(package.read('ppt/presentation.xml'))
        for page,sid in enumerate(root.findall('p:sldIdLst/p:sldId',NS),1):
            target=rels[sid.get('{'+R+'}id')]
            part=posixpath.normpath(posixpath.join('ppt',target)) if not target.startswith('/') else target[1:]
            slide=ET.fromstring(package.read(part));tree=slide.find('p:cSld/p:spTree',NS)
            if tree is None or slide.get('show')=='0':continue
            relpart=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
            refs={r.get('Id'):r.get('Target') for r in ET.fromstring(package.read(relpart)) if r.get('TargetMode')!='External'} if relpart in package.namelist() else {}
            nodes=list(tree)
            for index,node in enumerate(nodes):
                if node.tag!='{'+P+'}pic':continue
                nv=node.find('p:nvPicPr/p:cNvPr',NS)
                if nv is None:continue
                locator=f'slide:{page}/shape:{nv.get("id")}'
                if locator not in allowed or nv.get('hidden') in ('1','true'):continue
                transform=node.find('p:spPr/a:xfrm',NS);blip=node.find('p:blipFill/a:blip',NS)
                if transform is None or blip is None or transform.get('rot','0')!='0' or any(transform.get(k) in ('1','true') for k in ('flipH','flipV')):continue
                # Office's DPI hint changes layout scale, not image content.
                effects=[child for child in blip if child.tag!='{'+NS['a']+'}extLst']
                extension=blip.find('a:extLst',NS)
                if extension is not None:
                    effects += [leaf for ext in extension for leaf in ext if leaf.tag!='{http://schemas.microsoft.com/office/drawing/2010/main}useLocalDpi']
                if effects or node.find('p:spPr/a:effectLst/*',NS) is not None:continue
                def box(el):
                    x=el.find('.//a:xfrm',NS)
                    if x is None:return None
                    off=x.find('a:off',NS);ext=x.find('a:ext',NS)
                    if off is None or ext is None:return None
                    a,b=int(off.get('x')),int(off.get('y'));return [a,b,a+int(ext.get('cx')),b+int(ext.get('cy'))]
                bounds=box(node)
                if not bounds:continue
                # Unknown geometry of a later visible shape is conservatively held.
                overlay=False
                for other in nodes[index+1:]:
                    other_nv=other.find('.//p:cNvPr',NS)
                    if other_nv is None or other_nv.get('hidden') in ('1','true'):continue
                    b=box(other)
                    if b is None or (min(bounds[2],b[2])>max(bounds[0],b[0]) and min(bounds[3],b[3])>max(bounds[1],b[1])):
                        overlay=True;break
                if overlay:continue
                target=refs.get(blip.get('{'+R+'}embed'))
                if not target:continue
                imagepart=posixpath.normpath(posixpath.join(posixpath.dirname(part),target)) if not target.startswith('/') else target[1:]
                if not imagepart.startswith('ppt/media/') or package.getinfo(imagepart).file_size>40_000_000:continue
                try:
                    with Image.open(io.BytesIO(package.read(imagepart))) as original:
                        if original.width*original.height>12_000_000:continue
                        image=original.convert('RGB')
                    crop=node.find('p:blipFill/a:srcRect',NS)
                    if crop is not None:
                        l,t,r,b=[int(crop.get(k,'0'))/100000 for k in ('l','t','r','b')]
                        if min(l,t,r,b)<0 or l+r>=1 or t+b>=1:continue
                        image=image.crop((round(l*image.width),round(t*image.height),round((1-r)*image.width),round((1-b)*image.height)))
                    dest=folder/(signature([digest_file(path),locator])+'.png')
                    if not dest.exists():image.save(dest)
                    found.append({'path':str(dest),'locator':locator,'slide':page,'source_part':part,'image_sha256':digest_file(dest)})
                except (OSError,ValueError):continue
    return found


def observe(path, root, document, check=lambda:None):
    root=Path(root)
    allowed={r['locator'] for r in document['issues'] if r['reason']=='image_or_graphic_requires_visual_extraction'}
    items=pictures(path,root/'images',allowed)
    config=None;runtime_error=None
    for attempt in range(2):
        try:
            config=local_ocr.runtime();break
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            runtime_error=ocr_error(exc)
            if not isinstance(exc,subprocess.SubprocessError):break
    for item in items:
        check()
        if config is None:
            item['error']=runtime_error or 'local_ocr_unavailable';continue
        for attempt in range(2):
            check();item['attempts']=attempt+1
            try:
                item['ocr']=picture_ocr.recognize(item['path'],root/'ocr',config,check)
                item.pop('error',None);break
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                item['error']=ocr_error(exc)
                if not isinstance(exc,subprocess.SubprocessError):break
    return items


def ocr_error(exc):
    if isinstance(exc,subprocess.TimeoutExpired):return 'local_ocr_timeout'
    if isinstance(exc,PermissionError):return 'local_ocr_permission_denied'
    if isinstance(exc,FileNotFoundError) or str(exc)=='LOCAL_OCR_NOT_READY':return 'local_ocr_unavailable'
    if str(exc)=='LOCAL_OCR_CACHE_CHANGED':return 'local_ocr_cache_changed'
    return 'local_ocr_failed'


def enrich(path, root, document, chunks, held, evidence):
    before=digest_file(path)
    if before!=document['source_sha256']:raise ValueError('SOURCE_CHANGED')
    items=observe(path,root,document)
    completed={item['locator'] for item in items if item.get('ocr')}
    held=[r for r in held if r.get('locator') not in completed]
    for item in items:
        if not item.get('ocr'):
            # Preserve the picture hold and native text, while distinguishing a
            # runtime failure from text that was read but remained uncertain.
            for row in held:
                if row.get('locator')==item['locator']:
                    row['reason']=item.get('error','local_ocr_failed')
                    row['reasons']=[row['reason']]
            evidence.append({'locator':item['locator'],'policy':picture_ocr.POLICY,
                             'status':'held','error':item.get('error','local_ocr_failed'),
                             'attempts':item.get('attempts',0),'api_calls':0})
            continue
        base={'document_type':'pptx','source_sha256':before,'source_file':document['source_file'],
              'slide_number':item['slide'],'source_part':item['source_part'],'quality':picture_ocr.POLICY,
              'image_sha256':item['image_sha256'],'semantic_verified':False,'kind':'prose'}
        for region in item['ocr']['regions']:
            locator=item['locator']+'/'+region['id']
            row={**base,**region,'id':before[:16]+':'+locator,'source_locator':locator,'modality':'visual',
                 'context_text':region['text'],'image_region':region['bbox']}
            if row['eligible_for_chunking']:chunks.append(row)
            else:held.append({**row,'status':'held'})
        # Text OCR cannot infer arrow/edge topology. This is one explicit picture
        # coverage item; it does not discard any accepted text region.
        held.append({**base,'source_locator':item['locator'],'text':'','status':'held',
                     'eligible_for_chunking':False,'reasons':['picture_structure_not_interpreted'],
                     'modality':'visual'})
        evidence.append({'locator':item['locator'],'policy':picture_ocr.POLICY,'image_sha256':item['image_sha256'],
                         'receipt_hash':item['ocr']['payload_hash'],'regions':len(item['ocr']['regions']),'api_calls':0})
    if digest_file(path)!=before:raise ValueError('SOURCE_CHANGED')
    return chunks,held,evidence
