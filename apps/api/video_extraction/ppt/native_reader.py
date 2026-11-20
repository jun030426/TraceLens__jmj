"""python-pptx native source reader in its configured environment. No inference."""
import argparse
from pathlib import Path
from video_extraction.shared.common import digest_file,save


def extract(path):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    import importlib.metadata
    deck=Presentation(str(path));rows=[]
    def visit(shapes,number):
        for shape in shapes:
            if shape.shape_type==MSO_SHAPE_TYPE.GROUP:
                visit(shape.shapes,number);continue
            base={'slide_number':number,'shape_id':str(shape.shape_id)}
            if shape.has_table:rows.append({**base,'kind':'table','rows':[[c.text for c in r.cells] for r in shape.table.rows]})
            elif shape.has_text_frame and shape.text.strip():rows.append({**base,'kind':'text','text':shape.text})
    for n,slide in enumerate(deck.slides,1):visit(slide.shapes,n)
    return {'source':str(Path(path).resolve()),'source_sha256':digest_file(path),'tool':'python-pptx',
            'version':importlib.metadata.version('python-pptx'),'pages':len(deck.slides),'rows':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();save(args.output,extract(args.input))
