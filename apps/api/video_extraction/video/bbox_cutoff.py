"""Conservative native-pixel cutoff evidence, not an OCR correctness verdict.

Require compact neutral-dark strokes continuing across a boundary at two
thresholds. Colored annotations and long straight rules are not text evidence.
White-on-dark text and heavily merged glyphs are outside this detector's scope.
"""
from collections import deque

import numpy as np


def remove_rules(mask, minimum):
    removed=np.zeros_like(mask)
    for transposed in (False,True):
        source=mask.T if transposed else mask
        target=removed.T if transposed else removed
        for y,row in enumerate(source):
            changes=np.diff(np.r_[False,row,False].astype(np.int8))
            for start,end in zip(np.flatnonzero(changes==1),np.flatnonzero(changes==-1)):
                if end-start>=minimum:target[y,start:end]=True
    return mask & ~removed


def components(mask):
    remaining=mask.copy();height,width=mask.shape
    for y,x in zip(*np.nonzero(mask)):
        if not remaining[y,x]:continue
        pending=deque([(int(x),int(y))]);remaining[y,x]=False;points=[]
        while pending:
            a,b=pending.popleft();points.append((a,b))
            for yy in range(max(0,b-1),min(height,b+2)):
                for xx in range(max(0,a-1),min(width,a+2)):
                    if remaining[yy,xx]:remaining[yy,xx]=False;pending.append((xx,yy))
        yield np.asarray(points)


def cutoff_evidence(image, box):
    x0,y0,x1,y1=box
    scale=max(1,image.width/1280)
    padding=max(8,round(10*scale))
    left=max(0,x0-padding);top=max(0,y0-padding)
    right=min(image.width,x1+padding);bottom=min(image.height,y1+padding)
    rgb=np.asarray(image.convert('RGB').crop((left,top,right,bottom)),dtype=np.int16)
    if not rgb.size:return None
    dark=rgb.max(axis=2);neutral=rgb.max(axis=2)-rgb.min(axis=2)<=35
    trials=[]
    for threshold in (110,160):
        mask=remove_rules((dark<threshold)&neutral,max(20,round(24*scale)))
        hits=[]
        for points in components(mask):
            lo=points.min(axis=0);hi=points.max(axis=0)+1;w,h=hi-lo
            if not (3<=w<=48*scale and 5<=h<=42*scale and 8<=len(points)<=1200*scale*scale
                    and .15<=w/h<=5):continue
            xs=points[:,0]+left;ys=points[:,1]+top
            for edge,axis,boundary,inverted in [('left',xs,x0,False),('right',xs,x1,True),
                                               ('top',ys,y0,False),('bottom',ys,y1,True)]:
                if boundary==0 or boundary==(image.width if edge in ('left','right') else image.height):continue
                if axis.min()>boundary-2 or axis.max()<boundary+1:continue
                inside=(axis<boundary) if inverted else (axis>=boundary)
                if not .15<=float(inside.mean())<=.85:continue
                other=ys if edge in ('left','right') else xs
                low,high=(y0,y1) if edge in ('left','right') else (x0,x1)
                if not np.any((other>=low)&(other<high)):continue
                hits.append({'edge':edge,'component_bbox_pixels':[int(lo[0]+left),int(lo[1]+top),int(hi[0]+left),int(hi[1]+top)],
                             'inside_pixels':int(inside.sum()),'outside_pixels':int((~inside).sum())})
        trials.append(hits)
    supported=[]
    for a in trials[0]:
        if any(a['edge']==b['edge'] and max(abs(x-y) for x,y in zip(a['component_bbox_pixels'],b['component_bbox_pixels']))<=2
               for b in trials[1]):supported.append(a)
    if not supported:return None
    return {'method':'neutral_stroke_crosses_boundary_v2','thresholds':[110,160],
            'native_bbox_pixels':list(box),'supported_crossings':supported,
            'note':'Possible cutoff only; matching a stroke to the intended text still needs source review.'}
