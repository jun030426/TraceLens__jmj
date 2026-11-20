"""Discover source evidence from current pixels; no lecture IDs/approved answers.

Only isolated neutral-dark dash rows and compact boundary-crossing glyphs are
eligible. Unsupported colors, merged strokes and ambiguous scope stay unresolved.
"""
import math
import re
import cv2
import numpy as np
from video_extraction.shared.common import bbox_pixels
from video_extraction.video.separator_pixels import count_dashes
from video_extraction.video.bbox_cutoff import cutoff_evidence


def runs(mask):
    edges=np.diff(np.r_[False,mask,False].astype(np.int8))
    return list(zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))


def separator(image,block):
    text=block.get('text','');matches=list(re.finditer(r'-{5,}',text))
    if len(matches)!=1:return {'status':'not_applicable','reason':'separator_anchor_not_unique'}
    m=matches[0];lines=[s for s in text.splitlines() if s.strip()]
    # Line ownership is counted from original pixel rows, not guessed coordinates.
    index=next((i for i,s in enumerate(lines) if m.group() in s),None)
    box=bbox_pixels(block['bbox'],image.size,pad=0)
    rgb=np.asarray(image.convert('RGB').crop(box),dtype=np.int16)
    neutral=rgb.max(2)-rgb.min(2)<35;dark=rgb.max(2)
    rows=runs(((dark<140)&neutral).sum(1)>0)
    if len(rows)!=len(lines) or index is None:
        return {'status':'needs_review','reason':'text_line_pixel_mapping_ambiguous'}
    y0,y1=rows[index];mask=((dark<140)&neutral)[y0:y1]
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype('uint8'),8)
    candidates=[]
    for x,y,w,h,area in stats[1:]:
        if w>=2 and w>=1.5*h and area>=2:
            candidates.append([int(x),int(y+y0),int(x+w),int(y+y0+h)])
    candidates.sort()
    # Contiguous horizontal runs with near-constant pitch; separate competing runs.
    groups=[]
    for b in candidates:
        if not groups:groups.append([b]);continue
        last=groups[-1][-1];width=last[2]-last[0]
        if b[0]-last[2]<=max(3,width*1.5) and abs(b[1]-last[1])<=1:
            groups[-1].append(b)
        else:groups.append([b])
    groups=[g for g in groups if len(g)>=5]
    if len(groups)!=1:return {'status':'needs_review','reason':'dash_run_not_unique'}
    group=groups[0]
    # Include a clear margin; quotes or adjacent characters contaminating it reject.
    x0=min(b[0] for b in group)-2;x1=max(b[2] for b in group)+2
    top=min(b[1] for b in group)-2;bottom=max(b[3] for b in group)+2
    roi=[box[0]+x0,box[1]+top,box[0]+x1,box[1]+bottom]
    if x0<0 or top<0 or x1>rgb.shape[1] or bottom>rgb.shape[0]:
        return {'status':'needs_review','reason':'dash_margin_outside_target'}
    # Try a bounded range of contrast bands. Conflicting stable results reject.
    stable=[]
    for thresholds in ((70,80,90),(90,100,110),(110,120,130),(130,140,150),(150,160,170)):
        trial=count_dashes(image,roi,thresholds)
        if trial['status']=='verified':stable.append(trial)
    if len(stable)<2 or len({s['count'] for s in stable})!=1:
        return {'status':'needs_review','reason':'dash_threshold_consensus_missing','roi':roi}
    # Known foreground positions must not vary across successful contrast bands.
    starts=[s['trials'][0]['segments'] for s in stable]
    if any(max(abs(a[0]-b[0]) for a,b in zip(starts[0],row))>1 for row in starts[1:]):
        return {'status':'needs_review','reason':'dash_positions_unstable'}
    return {'status':'supported','method':'discovered_native_dash_row_v1','roi':roi,
            'value':stable[0]['value'],'count':stable[0]['count'],'span':[m.start(),m.end()],
            'line_index':index,'trials':stable,'source_bbox':block['bbox']}


def bounds(image,block,neighbors):
    before=bbox_pixels(block['bbox'],image.size,pad=0)
    evidence=cutoff_evidence(image,before)
    if not evidence:return {'status':'not_applicable','reason':'no_crossing_stroke'}
    boxes=[h['component_bbox_pixels'] for h in evidence['supported_crossings']]
    a,b,c,d=before
    proposed=[max(0,min([a]+[r[0]-2 for r in boxes])),max(0,min([b]+[r[1]-2 for r in boxes])),
              min(image.width,max([c]+[r[2]+2 for r in boxes])),min(image.height,max([d]+[r[3]+2 for r in boxes]))]
    norm=[math.floor(proposed[0]*1000/image.width),math.floor(proposed[1]*1000/image.height),
          math.ceil(proposed[2]*1000/image.width),math.ceil(proposed[3]*1000/image.height)]
    actual=bbox_pixels(norm,image.size,pad=0)
    if (actual[2]-actual[0])*(actual[3]-actual[1])>1.5*(c-a)*(d-b):
        return {'status':'needs_review','reason':'expansion_too_large','crossings':evidence}
    for n in neighbors:
        if n['id']==block['id']:continue
        x,y,z,w=bbox_pixels(n['bbox'],image.size,pad=0)
        overlap=lambda q:max(0,min(q[2],z)-max(q[0],x))*max(0,min(q[3],w)-max(q[1],y))
        if overlap(actual)>overlap(before):
            return {'status':'needs_review','reason':'expansion_intersects_neighbor','crossings':evidence}
    if cutoff_evidence(image,actual):return {'status':'needs_review','reason':'crossing_remains_after_expansion'}
    return {'status':'candidate','method':'bounded_crossing_component_expansion_v1',
            'before':block['bbox'],'after':norm,'crossings':evidence,
            'requires_source_text_and_target_recheck':True}
