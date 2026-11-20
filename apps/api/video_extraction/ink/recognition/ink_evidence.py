"""Local image evidence, explicit transforms, and conservative frame selection."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
#오류검사,수정,재검사

def read_rgb(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB'))


def padded_box(box, size, padding=.25):
    w,h=size; a,b,c,d=box
    if not 0 <= a < c <= 1000 or not 0 <= b < d <= 1000:
        raise ValueError('invalid_source_box')
    dx=max(12,(c-a)*w/1000*padding);dy=max(12,(d-b)*h/1000*padding)
    return [max(0,int(a*w/1000-dx)),max(0,int(b*h/1000-dy)),
            min(w,int(np.ceil(c*w/1000+dx))),min(h,int(np.ceil(d*h/1000+dy)))]


def foreground(rgb):
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    return ((gray<150)|((hsv[:,:,1]>90)&(hsv[:,:,2]>50))).astype(np.uint8)


def similarity(a,b):
    if a.shape!=b.shape:return {'eligible':False,'reason':'size_change'}
    fa,fb=foreground(a),foreground(b)
    kernel=np.ones((3,3),np.uint8)
    lost=np.count_nonzero((fa>0)&(cv2.dilate(fb,kernel)==0))/max(1,np.count_nonzero(fa))
    added=np.count_nonzero((fb>0)&(cv2.dilate(fa,kernel)==0))/max(1,np.count_nonzero(fb))
    difference=float(np.mean(np.abs(a.astype(float)-b.astype(float))))/255
    # Only near-identical states may substitute. Neither occlusion nor ink change
    # is automatically repaired by merging pixels from different times.
    return {'eligible':bool(lost<=.04 and added<=.04 and difference<=.035),
            'lost_foreground':float(lost),'added_foreground':float(added),'rgb_difference':difference}


def quality(rgb):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    return {'sharpness':float(cv2.Laplacian(gray,cv2.CV_64F).var()),
            'contrast':float(np.percentile(gray,95)-np.percentile(gray,5))}


def choose_frame(current,candidates,rect):
    ref=read_rgb(current);a,b,c,d=rect;crop=ref[b:d,a:c]
    rows=[]
    for path in dict.fromkeys([str(current)]+[str(p) for p in candidates]):
        rgb=read_rgb(path)
        local=similarity(crop,rgb[b:d,a:c]) if rgb.shape==ref.shape else {'eligible':False,'reason':'size_change'}
        global_state=similarity(ref,rgb)
        eligible=local['eligible'] and global_state['eligible']
        q=quality(rgb[b:d,a:c]) if rgb.shape==ref.shape else {'sharpness':0,'contrast':0}
        rows.append({'path':path,'eligible':eligible,'local_state':local,'global_state':global_state,**q})
    selected=max((r for r in rows if r['eligible']),key=lambda r:r['sharpness'])
    return selected['path'],rows


def prepare_views(task,folder):
    folder=Path(folder);folder.mkdir(parents=True)
    rgb=read_rgb(task['current_image']);h,w=rgb.shape[:2]
    rect=padded_box(task['bbox'],(w,h))
    chosen,candidates=choose_frame(task['current_image'],[task['before_image'],task['after_image']],rect)
    # Crops use one selected state. The wider crop is reserved for bounded recovery.
    result={'selected_frame':chosen,'frame_candidates':candidates,'source_size':[w,h],'views':{}}
    source=read_rgb(chosen)
    for name,region in [('original',rect),('expanded',padded_box(task['bbox'],(w,h),.65))]:
        a,b,c,d=region;crop=source[b:d,a:c];path=folder/(name+'.png');Image.fromarray(crop).save(path)
        result['views'][name]={'path':str(path.resolve()),'crop_in_source':[a/w,b/h,c/w,d/h],
                              'size':[c-a,d-b],'eligible':True,'operation':'crop_only'}
        if name!='original':continue
        lab=cv2.cvtColor(crop,cv2.COLOR_RGB2LAB)
        lab[:,:,0]=cv2.createCLAHE(clipLimit=1.5,tileGridSize=(4,4)).apply(lab[:,:,0])
        variants={'contrast':cv2.cvtColor(lab,cv2.COLOR_LAB2RGB),
                  'denoise':cv2.bilateralFilter(crop,5,25,25)}
        gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        _,bw=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        variants['binary']=cv2.cvtColor(bw,cv2.COLOR_GRAY2RGB)
        original_fg=foreground(crop)
        for variant,arr in variants.items():
            target=folder/(variant+'.png');Image.fromarray(arr).save(target)
            retained=np.count_nonzero((original_fg>0)&(cv2.dilate(foreground(arr),np.ones((3,3),np.uint8))>0))/max(1,np.count_nonzero(original_fg))
            result['views'][variant]={'path':str(target.resolve()),'crop_in_source':[a/w,b/h,c/w,d/h],
                'size':[c-a,d-b],'foreground_retention':float(retained),'eligible':bool(retained>=.98),
                'operation':variant,'never_replaces_original':True}
    return result


def box_pixels(named,size):
    w,h=size
    a,b,c,d=[named[k] for k in ('left','top','right','bottom')]
    if not all(type(x) in (int,float) and np.isfinite(x) for x in (a,b,c,d)):
        raise ValueError('invalid_named_box')
    if not 0<=a<c<=1000 or not 0<=b<d<=1000:raise ValueError('invalid_named_box')
    return [int(a*w/1000),int(b*h/1000),min(w,int(np.ceil(c*w/1000))),min(h,int(np.ceil(d*h/1000)))]


def pixel_evidence(path,named):
    rgb=read_rgb(path);h,w=rgb.shape[:2];a,b,c,d=box_pixels(named,(w,h))
    roi=rgb[b:d,a:c]
    return {'foreground_pixels':int(np.count_nonzero(foreground(roi))),
            'area_pixels':int((c-a)*(d-b)),
            'interpretation':'Foreground presence is necessary evidence, never proof of glyph/mark identity.'}
