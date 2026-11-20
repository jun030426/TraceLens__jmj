"""Conservative Korean ASR proposals. Scores rank candidates; they are not probabilities.

This module never rewrites lesson facts. Audio evidence is required for application.
The phonetic transform deliberately implements only simple liaison, not a full G2P.
"""
import re
import unicodedata

VERSION = 3
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
JONG = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'
# Only common particles/copula endings. Unknown morphology is held rather than invented.
SUFFIXES = sorted({'', '은', '는', '이', '가', '을', '를', '의', '도', '만', '에', '로',
    '과', '와', '부터', '까지', '에서', '으로', '이라고', '라고', '이라는', '라는',
    '이라', '라', '이다', '다', '입니다', '들이', '들은', '들을', '들도', '들',
    '하고', '랑', '이라든가', '라든가', '에서의', '에서도', '으로는', '에서는',
    '에요', '예요', '이나', '나', '든', '이든', '에다가', '에도'}, key=lambda x:(-len(x), x))
TOKEN = re.compile(r'[가-힣]+')
PROTECTED = re.compile(r'\d|[+*=<>]|불가능|가능|불가|않|없|아니|못|더하기|빼기|곱하기|나누기')
# Valid technical variants are protected, never forcibly normalized to another term.
VALID_VARIANTS = {'메소드', '메서드', '인덱싱', '슬라이싱'}


def letters(text, liaison=False):
    syllables=[]
    for c in unicodedata.normalize('NFC', text):
        n=ord(c)-0xAC00
        if 0 <= n < 11172:
            syllables.append([CHO[n//588],JUNG[n%588//28],JONG[n%28].strip()])
        else:
            syllables.append([c.lower()])
    if liaison:
        for left,right in zip(syllables,syllables[1:]):
            # Single final consonant + vowel initial: 대답을 -> 대다블.
            # Excludes 겹받침, ㅇ, ㅎ and all cross-word guesses.
            if len(left)==len(right)==3 and right[0]=='ㅇ' and left[2] in 'ㄱㄲㄴㄷㄹㅁㅂㅅㅆㅈㅊㅋㅌㅍ':
                right[0]=left[2];left[2]=''
    return ''.join(''.join(s) for s in syllables)


def distance(a,b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):
            row.append(min(prev[j]+1,row[-1]+1,prev[j-1]+(x!=y)))
        prev=row
    return prev[-1]


def phonetic_similarity(a,b):
    versions=[(letters(a),letters(b)),(letters(a,True),letters(b,True))]
    return max(1-distance(x,y)/max(len(x),len(y),1) for x,y in versions)


def split_known(token, terms):
    return [(t,token[len(t):]) for t in terms
            if token.startswith(t) and token[len(t):] in SUFFIXES]


def propose(text, context, lexicon):
    """Return at most one proposal per token. No expected answer/misspelling table."""
    terms={r['term'] for r in lexicon}
    proposals=[]
    for match in TOKEN.finditer(text):
        token=match.group()
        # Preserve an already recognized stem regardless of particle complexity.
        if len(token)<2 or PROTECTED.search(token) or any(token.startswith(t) for t in terms|VALID_VARIANTS):
            continue
        choices=[]
        for entry in lexicon:
            term=entry['term']
            anchors=sorted({x for x in entry.get('anchors',[]) if x in context})
            if not anchors:continue
            best=None
            for suffix in SUFFIXES:
                target=term+suffix
                exact_liaison=letters(token,True)==letters(target,True)
                if suffix and not token.endswith(suffix) and not exact_liaison:continue
                stem=token[:-len(suffix)] if suffix else token
                if not exact_liaison and (len(stem)<2 or abs(len(stem)-len(term))>1):continue
                sim=phonetic_similarity(token,target)
                # Orthographic length alone cannot make a remote word a candidate.
                stem_sim=1.0 if exact_liaison else phonetic_similarity(stem,term)
                if stem_sim < .64 or sim < .72:continue
                score=.65*stem_sim+.25*min(1,len(anchors)/3)+.10*entry.get('importance',1)/3
                candidate={'before':token,'after':target,'term':term,
                    'start':match.start(),'end':match.end(),'phonetic_score':round(sim,4),
                    'rank_score':round(score,4),'context_matches':anchors,
                    'importance':entry.get('importance',1),'source_refs':entry.get('source_refs',[])}
                if best is None or score>best['rank_score']:best=candidate
            if best:choices.append(best)
        choices.sort(key=lambda x:(-x['rank_score'],x['after']))
        if not choices:continue
        top=choices[0]
        top['margin']=round(top['rank_score']-choices[1]['rank_score'],4) if len(choices)>1 else 1.0
        top['ambiguous']=top['margin']<.06
        top['alternatives']=[x['after'] for x in choices[1:3]]
        proposals.append(top)
    return proposals


def evidence(text, word_spans, expected, start, end):
    """Require the full inflected form at this time; a shared stem is insufficient."""
    local=[w for w in word_spans if start-.45 <= (w['start_seconds']+w['end_seconds'])/2 <= end+.45]
    for i in range(len(local)):
        for n in range(1,4):
            cleaned=''.join(''.join(TOKEN.findall(w['word'])) for w in local[i:i+n])
            # Orthographic restoration of an EXACT liaison equivalent is allowed.
            # Approximate vowel/consonant similarity cannot satisfy this audio gate.
            if cleaned==expected or (cleaned and letters(cleaned,True)==letters(expected,True)):return True
    return False


def token_time(segment, proposal):
    # Map immutable character offsets to the original word timestamps.
    cursor=0;matches=[]
    for w in segment.get('words',[]):
        raw=w['word'].strip()
        found=segment['text'].find(raw,cursor)
        if found<0:continue
        cursor=found+len(raw)
        if found<proposal['end'] and proposal['start']<cursor:matches.append(w)
    if not matches:return None
    return min(w['start_seconds'] for w in matches),max(w['end_seconds'] for w in matches)


def apply(segment, proposals, plain, hinted, witness=None):
    accepted=[];held=[]
    for p in proposals:
        p=dict(p);span=token_time(segment,p);reason=None
        if p.get('ambiguous'):reason='competing_candidates'
        elif p['rank_score']<.73:reason='insufficient_context_or_rank'
        elif PROTECTED.search(p['before']) or PROTECTED.search(p['after']):reason='protected_content'
        elif not span:reason='missing_word_alignment'
        elif not evidence(plain.get('text',''),plain.get('all_words',plain['words']),p['after'],*span):reason='unhinted_audio_disagrees'
        elif not evidence(hinted.get('text',''),hinted.get('all_words',hinted['words']),p['after'],*span):reason='hinted_audio_disagrees'
        elif witness is not None and not evidence(witness.get('text',''),witness.get('all_words',witness['words']),p['after'],*span):reason='second_model_disagrees'
        if reason:held.append({**p,'reason':reason})
        else:accepted.append({**p,'audio_span':list(span),'status':'machine_supported_not_gold'})
    result=segment['text']
    for p in sorted(accepted,key=lambda p:p['start'],reverse=True):
        assert result[p['start']:p['end']]==p['before']
        result=result[:p['start']]+p['after']+result[p['end']:]
    return result,accepted,held
