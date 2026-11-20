"""Reuse OCR observations only where an authorized PPT image matches video pixels.

The matched video pixels are an independent source of the text. No hidden PPT
text, native slide text or inferred diagram relationships are copied into video.
"""
from pathlib import Path
import cv2
import numpy as np
from lerny import ppt_pictures
from rag_mvp.document_ingest import extract
from video_extraction.shared.common import digest_file


def prepare(references, root, check):
    images=[]
    for ref in references:
        check()
        if digest_file(ref['path'])!=ref['sha256']:raise ValueError('SOURCE_CHANGED')
        document=extract(ref['path'],validate_tables=True)
        for item in ppt_pictures.observe(Path(ref['path']),root,document,check):
            if item.get('ocr'):
                item['reference']={k:ref[k] for k in ('material_id','version_id','sha256')}
                images.append(item)
    return images


def features(path):
    cv2.setNumThreads(1)
    image=cv2.imread(str(path))
    if image is None:return None
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    keypoints,descriptors=cv2.SIFT_create(nfeatures=1500).detectAndCompute(gray,None)
    return image,gray,keypoints,descriptors


def pixel_match(reference, frame, *, reference_features=None, frame_features=None):
    """Find scale/translation, then validate full overlap and individual pixels.

    Feature similarity alone never authorizes reuse. Rotation/perspective, small
    matches, color-only changes, occlusions and ambiguous repeated matches fail.
    """
    ref=reference_features if reference_features is not None else features(reference)
    observed=frame_features if frame_features is not None else features(frame)
    if ref is None or observed is None:return None
    a,gray_a,ka,da=ref;b,gray_b,kb,db=observed
    if da is None or db is None:return None
    pairs=cv2.BFMatcher().knnMatch(da,db,k=2)
    matches=[m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance<.65*n.distance]
    if len(matches)<12:return None
    src=np.float32([ka[m.queryIdx].pt for m in matches]);dst=np.float32([kb[m.trainIdx].pt for m in matches])
    matrix,inliers=cv2.estimateAffine2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=1.5)
    if matrix is None or inliers.sum()<20 or inliers.mean()<.45:return None
    inlier_points=src[inliers.ravel().astype(bool)]
    if np.ptp(inlier_points[:,0])<a.shape[1]*.3 or np.ptp(inlier_points[:,1])<a.shape[0]*.3:return None
    sx,sy=matrix[0,0],matrix[1,1]
    # PPT may stretch an image differently along the two axes. Rotation/shear
    # still fail; each region is subsequently checked against actual pixels.
    if not (.2<=sx<=4 and .2<=sy<=4 and .5<=sx/sy<=2) or abs(matrix[0,1])>.0005 or abs(matrix[1,0])>.0005:return None
    h,w=a.shape[:2];bh,bw=b.shape[:2]
    box=[matrix[0,2],matrix[1,2],matrix[0,2]+sx*w,matrix[1,2]+sy*h]
    if box[0]<-1 or box[1]<-1 or box[2]>bw+1 or box[3]>bh+1:return None
    left,top=max(0,int(np.floor(box[0]))),max(0,int(np.floor(box[1])))
    right,bottom=min(bw,int(np.ceil(box[2]))),min(bh,int(np.ceil(box[3])))
    transform=matrix.copy();transform[:,2]-=[left,top]
    # Compare at the observed video resolution, not sharp native pixels against
    # an upscaled, blurred video. The actual source-to-frame transform is retained.
    expected=cv2.warpAffine(a,transform,(right-left,bottom-top),borderValue=(255,255,255))
    aligned=b[top:bottom,left:right]
    diff=np.abs(expected.astype(np.float32)-aligned.astype(np.float32)).max(axis=2)
    # Compare color as well as structure so highlights/colored annotations count.
    if float(diff.mean())>12 or float((diff>35).mean())>.08:return None
    # Small changed letters must not disappear into a large white background's
    # mean score. Allow one-pixel resampling jitter, then compare ink components.
    ink_a=(cv2.cvtColor(expected,cv2.COLOR_BGR2GRAY)<150).astype(np.uint8)
    ink_b=(cv2.cvtColor(aligned,cv2.COLOR_BGR2GRAY)<150).astype(np.uint8)
    kernel=np.ones((3,3),np.uint8)
    changed_ink=((ink_a & (1-cv2.dilate(ink_b,kernel))) | (ink_b & (1-cv2.dilate(ink_a,kernel))))
    return {'matrix':matrix,'bbox':[box[0]/bw*1000,box[1]/bh*1000,box[2]/bw*1000,box[3]/bh*1000],
            'diff':diff,'changed_ink':changed_ink,'dimensions':[w,h],'frame_dimensions':[bw,bh],
            'comparison_transform':transform,
            'mean_pixel_error':float(diff.mean()),'changed_pixel_fraction':float((diff>35).mean())}


def region_matches(match, bbox):
    w,h=match['dimensions'];x1,y1,x2,y2=[int(round(v*s/1000)) for v,s in zip(bbox,[w,h,w,h])]
    if 'comparison_transform' in match:
        points=np.float32([[[x1,y1],[x2,y1],[x1,y2],[x2,y2]]])
        transformed=cv2.transform(points,match['comparison_transform'])[0]
        x1,y1=np.floor(transformed.min(axis=0)).astype(int);x2,y2=np.ceil(transformed.max(axis=0)).astype(int)
        h,w=match['diff'].shape
    region=match['diff'][max(0,y1-2):min(h,y2+2),max(0,x1-2):min(w,x2+2)]
    if not (region.size and float(region.mean())<=12 and float((region>35).mean())<=.08):return False
    ink=match['changed_ink'][max(0,y1-2):min(h,y2+2),max(0,x1-2):min(w,x2+2)]
    _,_,stats,_=cv2.connectedComponentsWithStats(ink,connectivity=8)
    return not len(stats[1:]) or int(stats[1:,cv2.CC_STAT_AREA].max())<6


def inside(line, box):
    a=line['bbox']
    return a[0]>=box[0]-1 and a[1]>=box[1]-1 and a[2]<=box[2]+1 and a[3]<=box[3]+1


def reuse(frame, images, start, end, seen, check):
    records=[];covered=[];proofs=[]
    frame_features=features(frame) if images else None
    for item in images:
        check()
        if '_features' not in item:item['_features']=features(item['path'])
        match=pixel_match(item['path'],frame,reference_features=item['_features'],frame_features=frame_features)
        if match is None:continue
        matching=[r for r in item['ocr']['regions'] if region_matches(match,r['bbox'])]
        if not matching:continue
        whole=len(matching)==len(item['ocr']['regions'])
        if whole:covered.append(match['bbox'])
        proof={'image_sha256':item['image_sha256'],'reference':item['reference'],
               'source_locator':item['locator'],'video_start_seconds':start,'video_end_seconds':end,
               'mean_pixel_error':match['mean_pixel_error'],'changed_pixel_fraction':match['changed_pixel_fraction'],
               'receipt_hash':item['ocr']['payload_hash'],'matched_regions':[r['id'] for r in matching]}
        proofs.append(proof)
        key=item['image_sha256'];w,h=match['dimensions'];fw,fh=match['frame_dimensions'];matrix=match['matrix']
        for r in matching:
            if not whole:
                x1,y1,x2,y2=r['bbox']
                covered.append([(matrix[0,0]*x1*w/1000+matrix[0,2])/fw*1000,
                                (matrix[1,1]*y1*h/1000+matrix[1,2])/fh*1000,
                                (matrix[0,0]*x2*w/1000+matrix[0,2])/fw*1000,
                                (matrix[1,1]*y2*h/1000+matrix[1,2])/fh*1000])
            region_key=key+':'+r['id']
            if region_key in seen:continue
            seen.add(region_key)
            records.append({**r,'id':key[:16]+'-'+r['id'],'modality':'visual','start_seconds':start,'end_seconds':end,
                            'source_locator':f'영상 {start:.1f}초 · PPT 그림 일치 영역 · '+item['locator'],
                            'picture_reuse':proof,'isolated':True})
        if key+':structure' in seen:continue
        seen.add(key+':structure')
        records.append({'id':key[:16]+'-structure','modality':'visual','text':'','start_seconds':start,'end_seconds':end,
                        'source_locator':f'영상 {start:.1f}초 · 그림 구조','reasons':['picture_structure_not_interpreted'],
                        'eligible_for_chunking':False,'picture_reuse':proof})
    return records,covered,proofs
