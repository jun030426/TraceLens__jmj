"""Editable 16:9 Lerny slides, with a reserved presenter/caption safe area."""
from typing import Literal
import unicodedata
from pydantic import Field, model_validator
from lerny.lecture_contract import StrictModel
from lerny.lecture_theme import COLORS


class TeachingSlide(StrictModel):
    heading: str = Field(min_length=1, max_length=28)
    key_point: str = Field(min_length=1, max_length=64)
    kind: Literal["keypoints", "steps", "compare", "code"]
    items: list[str] = Field(min_length=1, max_length=4)
    code: str = Field(default="", max_length=260)
    caption: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def fits(self):
        if any(not x.strip() or len(x) > 38 or "\n" in x for x in self.items):
            raise ValueError("SLIDE_TEXT_OVERFLOW")
        if any("\n" in x for x in (self.heading, self.key_point, self.caption)):
            raise ValueError("SLIDE_TEXT_OVERFLOW")
        if self.kind == "code":
            lines = self.code.splitlines()
            if not lines or len(lines) > 6 or any(len(x) > 40 for x in lines) or len(self.items) > 2:
                raise ValueError("SLIDE_TEXT_OVERFLOW")
        elif self.code:
            raise ValueError("SLIDE_UNEXPECTED_CODE")
        if self.kind == "compare" and len(self.items) != 2:
            raise ValueError("SLIDE_COMPARISON_REQUIRED")
        return self


class TeachingPlan(StrictModel):
    slides: list[TeachingSlide] = Field(min_length=1, max_length=50)


def generation_schema():
    # Keep model grammar small. Nested cardinality/length bounds can exceed the
    # Interactions compiler's state budget. The strict local models enforce them.
    fields={name:{'type':'string'} for name in ('heading','key_point','code','caption')}
    fields['kind']={'type':'string','enum':['keypoints','steps','compare','code']}
    fields['items']={'type':'array','items':{'type':'string'}}
    return {'type':'object','properties':{'slides':{'type':'array','items':{
        'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}},
        'required':['slides'],'additionalProperties':False}


def rgb(hex_color):
    return dict(zip(("red", "green", "blue"), (int(hex_color[i:i+2],16)/255 for i in (0,2,4))))


def slide_requests(slide, page_id, position, total, scale=1):
    """960×540 design coordinates scaled to the native deck. No arbitrary model geometry."""
    requests = [{"createSlide": {"objectId":page_id,"slideLayoutReference":{"predefinedLayout":"BLANK"}}},
        {"updatePageProperties":{"objectId":page_id,"pageProperties":{"pageBackgroundFill":{
            "solidFill":{"color":{"rgbColor":rgb(COLORS['background'])},"alpha":1}}},"fields":"pageBackgroundFill"}}]
    counter=0
    def shape(text,x,y,w,h,size=18,fill=None,color=COLORS['ink'],bold=False,mono=False):
        nonlocal counter
        counter+=1; oid=f"{page_id}_e{counter}"
        requests.append({"createShape":{"objectId":oid,"shapeType":"ROUND_RECTANGLE" if fill else "TEXT_BOX",
            "elementProperties":{"pageObjectId":page_id,"size":{"width":{"magnitude":w,"unit":"PT"},
                "height":{"magnitude":h,"unit":"PT"}},"transform":{"scaleX":scale,"scaleY":scale,
                    "translateX":x*scale,"translateY":y*scale,"unit":"PT"}}}})
        props={"outline":{"propertyState":"NOT_RENDERED"},"contentAlignment":"MIDDLE"}
        if fill:props["shapeBackgroundFill"]={"solidFill":{"color":{"rgbColor":rgb(fill)},"alpha":1}}
        requests.append({"updateShapeProperties":{"objectId":oid,"shapeProperties":props,"fields":','.join(props)}})
        if text:
            requests.extend([{"insertText":{"objectId":oid,"text":text}},
                {"updateTextStyle":{"objectId":oid,"textRange":{"type":"ALL"},"style":{
                    "fontFamily":"Roboto Mono" if mono and not any(unicodedata.east_asian_width(c) in {'W','F'} for c in text) else "Noto Sans KR",
                    "fontSize":{"magnitude":size*scale,"unit":"PT"},
                    "foregroundColor":{"opaqueColor":{"rgbColor":rgb(color)}},"bold":bold},
                    "fields":"fontFamily,fontSize,foregroundColor,bold"}},
                {"updateParagraphStyle":{"objectId":oid,"textRange":{"type":"ALL"},"style":{
                    "spaceAbove":{"magnitude":0,"unit":"PT"},"spaceBelow":{"magnitude":0,"unit":"PT"},
                    "lineSpacing":110,"alignment":"START"},"fields":"spaceAbove,spaceBelow,lineSpacing,alignment"}}])
    # Avatar region x<390 and caption region y>465 remain empty.
    shape("",398,38,526,422,fill=COLORS['paper'])
    shape(f"LERNY  /  {position:02d} · {total:02d}",418,48,480,28,11,color=COLORS['accent'],bold=True)
    shape(slide.heading,418,84,480,58,22,bold=True)
    shape(slide.key_point,418,146,480,68,18,color=COLORS['ink'])
    if slide.kind == "code":
        # A Korean comment can be twice as wide as an ASCII code token. Keep all
        # six allowed lines on screen instead of relying on automatic wrapping.
        widest=max(sum(1 if unicodedata.east_asian_width(c) in {'W','F'} else .62 for c in line)
                   for line in slide.code.splitlines())
        code_size=min(15,460/max(1,widest))
        shape(slide.code,418,226,480,146,code_size,fill=COLORS['code'],color=COLORS['paper'],mono=True)
        shape("\n".join(slide.items),418,374,480,40,13)
    elif slide.kind == "compare":
        for i,item in enumerate(slide.items):
            shape(("01  " if i==0 else "02  ")+item,418+i*246,232,234,155,18,
                  fill=COLORS['accent'] if i==1 else COLORS['background'],
                  color=COLORS['paper'] if i==1 else COLORS['ink'])
    else:
        for i,item in enumerate(slide.items):
            shape((f"{i+1:02d}  " if slide.kind=="steps" else "•  ")+item,
                  418,225+i*46,480,44,16,fill=COLORS['background'])
    shape(slide.caption,418,416,480,34,11,color=COLORS['muted'])
    return requests
