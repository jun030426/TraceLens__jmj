"""Common record envelope shared by all modality specialists."""

def base_record(t,suffix,modality,kind,text):
    return {'id':t['id']+':'+suffix,'source_id':t['source_id'],'source_sha256':t['source_id'],'source_file':t['source_file'],
        'unit_id':t['id'],'modality':modality,'kind':kind,'location':t['location'],'observed_text':text,
        'original_text':text,'eligible_for_chunking':False,'gold_approved':False,'judgment':'held','reasons':[]}
