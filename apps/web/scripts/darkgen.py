"""Generate lerny-dark.css: mirror every color declaration of the app CSS under :root[data-theme="dark"]
with OKLab lightness inverted. 
다시 만들 때 (apps/web 에서):
  python3 scripts/darkgen.py src src/lerny-dark.css student-lists.css professor-analysis.css learning-progress.css landing.css instructor.css student-home.css style.css workspace-refinements.css lerny-theme.css lerny-design.css visualization/visualization.css
파일 순서 = 브라우저가 CSS 를 불러오는 순서예요. 앱 CSS 색을 바꾼 뒤 한 번 다시 돌리면 다크 모드도 따라 바뀌어요."""
import re, sys, math

SRC, OUT, FILES = sys.argv[1], sys.argv[2], sys.argv[3:]
PFX = ':root[data-theme="dark"]'

COLOR_PROPS = re.compile(r'^(background(-color|-image)?|color|border(-(top|right|bottom|left|block|inline)(-start|-end)?)?(-color)?|outline(-color)?|fill|stroke|box-shadow|text-shadow|caret-color|accent-color|text-decoration(-color)?|column-rule(-color)?|scrollbar-color|stop-color|-webkit-text-fill-color|-webkit-tap-highlight-color)$', re.I)
SHADOW = re.compile(r'shadow', re.I)

NAMED = {'white': (255, 255, 255, 1), 'black': (0, 0, 0, 1)}

# ---------- color math ----------
def s2l(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def l2s(c):
    c = max(0, min(1, c))
    v = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return round(max(0, min(1, v)) * 255)
def to_oklab(r, g, b):
    r, g, b = s2l(r), s2l(g), s2l(b)
    l = 0.4122214708*r + 0.5363325363*g + 0.0514459929*b
    m = 0.2119034982*r + 0.6806995451*g + 0.1073969566*b
    s = 0.0883024619*r + 0.2817188376*g + 0.6299787005*b
    l, m, s = l ** (1/3), m ** (1/3), s ** (1/3)
    return (0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
            1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
            0.0259040371*l + 0.7827717662*m - 0.8086757660*s)
def from_oklab(L, a, b):
    l = (L + 0.3963377774*a + 0.2158037573*b) ** 3
    m = (L - 0.1055613458*a - 0.0638541728*b) ** 3
    s = (L - 0.0894841775*a - 1.2914855480*b) ** 3
    return (l2s(4.0767416621*l - 3.3077115913*m + 0.2309699292*s),
            l2s(-1.2684380046*l + 2.6097574011*m - 0.3413193965*s),
            l2s(-0.0041960863*l - 0.7034186147*m + 1.7076147010*s))

# ---------- 다크 팔레트 (밝은 모드의 보라 · 라일락 계열을 밤하늘 톤으로 옮겨요) ----------
# 밝은 모드: 라일락 종이 바탕 + 자두빛 보라 포인트  →  다크 모드: 보랏빛 밤 바탕 + 라일락으로 빛나는 포인트
HUE = 308       # 무채색(회색)도 이 보라 쪽으로 살짝 물들여요 — 회색 글씨 · 회색 선이 따로 놀지 않게
MODE = 'generic'  # 'bg' | 'text' | 'generic' | 'keep'

def lch(L, C, h):
    return from_oklab(L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h)))

def map_rgb(r, g, b):
    L, A, B = to_oklab(r, g, b)
    C = (A * A + B * B) ** 0.5
    h = math.degrees(math.atan2(B, A)) % 360 if C > 0.012 else HUE
    if MODE == 'keep':
        return int(r), int(g), int(b)
    if MODE == 'text' and L >= 0.93:
        return int(r), int(g), int(b)  # 흰 글씨는 (색 버튼 · 짙은 카드 위라서) 그대로
    if MODE == 'bg' and L < 0.4:
        # 원래 짙은 면(밤색 카드) → 바탕보다 한 단계 떠 보이는 자두빛 면
        return lch(max(L, 0.29), min(0.075, C * 1.15 + 0.01), h)
    if C > 0.07 and 0.3 < L < 0.85:
        # 보라 포인트: 글씨는 밝은 라일락, 버튼 면은 맑은 보라, 선 · 아이콘은 그 사이
        if MODE == 'text':
            return lch(0.81, min(0.13, C * 1.05), h)
        if MODE == 'bg':
            return lch(min(0.66, max(0.57, L + 0.08)), min(0.15, C * 1.15), h)
        return lch(min(0.72, max(0.63, L + 0.1)), min(0.14, C * 1.1), h)
    if L >= 0.93 and MODE == 'bg' and C >= 0.015 and L < 0.975:
        # 옅은 보라 물 (강조 칸 · 선택된 칩) → 같은 보라를 머금은 짙은 칸
        return lch(0.28, min(0.075, C * 1.6 + 0.02), h)
    if L >= 0.93:
        # 종이 · 카드 · 흰 면 → 보랏빛 밤 (원래 밝을수록 살짝 더 밝게: 카드가 바탕보다 떠 보이게)
        L2 = 0.165 + (L - 0.93) * 1.25
        return lch(L2, 0.028 + min(C, 0.03) * 0.5, h if C > 0.012 else HUE)
    if L >= 0.8 and MODE == 'bg':
        # 옅게 물든 면(배지 · 강조 칸 · 연보라 칸) → 같은 색을 머금은 짙은 칸
        return lch(0.255 + (0.93 - L) * 0.45, min(0.075, C * 1.1 + 0.02), h)
    if L >= 0.8:
        # 연한 선 · 구분선 → 바탕 위에서 보이는 보랏빛 선
        return lch(0.30 + (0.93 - L) * 0.5, min(0.06, C + 0.025), h)
    # 그 밖은 밝기를 뒤집어요 (진한 글씨 → 밝은 글씨) — 라일락 기운을 조금 남겨요
    L2 = min(0.95, 1.13 - 0.95 * L)
    if MODE == 'bg' and L2 > 0.5:
        # 진한 면(채워진 칩 · 막대)은 너무 하얘지지 않게
        L2 = 0.5 + (L2 - 0.5) * 0.6
    C2 = min(0.09, max(C, 0.02)) if L2 > 0.5 else min(0.06, C * 0.9 + 0.02)
    return lch(L2, C2, h)

def fmt(r, g, b, a):
    if a >= 1:
        return '#%02x%02x%02x' % (r, g, b)
    return 'rgba(%d, %d, %d, %s)' % (r, g, b, ('%.3f' % a).rstrip('0').rstrip('.'))

def parse_hex(h):
    h = h[1:]
    if len(h) in (3, 4):
        h = ''.join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(h[6:8], 16) / 255 if len(h) == 8 else 1
    return r, g, b, a

COLOR_RE = re.compile(r'#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|rgba?\(\s*[\d.]+%?\s*[, ]\s*[\d.]+%?\s*[, ]\s*[\d.]+%?\s*(?:[,/]\s*[\d.]+%?\s*)?\)|\b(?:white|black)\b', re.I)

def conv(mt):
    t = mt.group(0)
    if t.startswith('#'):
        r, g, b, a = parse_hex(t)
    elif t.lower() in NAMED:
        r, g, b, a = NAMED[t.lower()]
    else:
        nums = re.findall(r'[\d.]+%?', t)
        def ch(v):
            return float(v[:-1]) * 2.55 if v.endswith('%') else float(v)
        r, g, b = (ch(v) for v in nums[:3])
        a = 1
        if len(nums) > 3:
            a = float(nums[3][:-1]) / 100 if nums[3].endswith('%') else float(nums[3])
    # 아주 투명한 검정 선 · 그림자는 밝은 선으로, 투명한 흰색은 어두운 막으로
    nr, ng, nb = map_rgb(r, g, b)
    return fmt(nr, ng, nb, a)

BG_PROP = re.compile(r'^background', re.I)
KEEP_VAR = re.compile(r'night|on-dark', re.I)
BG_VAR = re.compile(r'ground|surface|pearl|paper|wash|soft$|step|mist|rose|beige|-bg|panel|card|secondary$|secondary-hover', re.I)
TEXT_VAR = re.compile(r'ink|text|muted|faint|grey|gray', re.I)

def map_value(prop, val):
    global MODE
    if prop.startswith('--'):
        # 변수는 이름으로 쓰임새를 짐작해요 (면 · 글씨 · 그 밖)
        MODE = ('keep' if KEEP_VAR.search(prop) else
                'text' if TEXT_VAR.search(prop) else
                'bg' if BG_VAR.search(prop) else 'generic')
    else:
        MODE = 'bg' if BG_PROP.match(prop) else 'text' if prop.lower() in ('color', '-webkit-text-fill-color', 'caret-color') else 'generic'
    if SHADOW.search(prop):
        # 그림자는 그대로 검게 두되 조금 진하게 — 어두운 바탕에서도 보이게
        def sh(mt):
            t = mt.group(0)
            return t
        return val
    # url(...) 안은 건드리지 않아요
    parts = re.split(r'(url\([^)]*\))', val)
    return ''.join(p if p.startswith('url(') else COLOR_RE.sub(conv, p) for p in parts)

# ---------- tiny CSS parser ----------
def strip_comments(s):
    return re.sub(r'/\*.*?\*/', '', s, flags=re.S)

def parse_block(s, i):
    """returns list of (prelude, body|children) until matching } ; body is str for declarations"""
    items = []
    buf = ''
    while i < len(s):
        c = s[i]
        if c in '"\'':
            j = s.index(c, i + 1)
            buf += s[i:j + 1]
            i = j + 1
            continue
        if c == '{':
            prelude = buf.strip()
            buf = ''
            if prelude.startswith('@') and re.match(r'@(media|supports|layer|container)', prelude):
                children, i = parse_block(s, i + 1)
                items.append((prelude, children))
            else:
                depth, j = 1, i + 1
                while depth:
                    if s[j] in '"\'':
                        j = s.index(s[j], j + 1)
                    elif s[j] == '{':
                        depth += 1
                    elif s[j] == '}':
                        depth -= 1
                    j += 1
                items.append((prelude, s[i + 1:j - 1]))
                i = j
            continue
        if c == '}':
            return items, i + 1
        if c == ';' and buf.strip().startswith('@'):
            buf = ''
            i += 1
            continue
        buf += c
        i += 1
    return items, i

def split_decls(body):
    out, buf, depth, q = [], '', 0, None
    for c in body:
        if q:
            buf += c
            if c == q:
                q = None
            continue
        if c in '"\'':
            q = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ';' and depth == 0:
            out.append(buf)
            buf = ''
        else:
            buf += c
    if buf.strip():
        out.append(buf)
    return out

def split_selectors(pre):
    out, buf, depth = [], '', 0
    for c in pre:
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(buf.strip())
            buf = ''
        else:
            buf += c
    out.append(buf.strip())
    return out

def prefix(sel):
    if re.match(r'^:root\b', sel):
        return PFX + sel[5:]
    if re.match(r'^html\b', sel):
        return 'html[data-theme="dark"]' + sel[4:]
    return PFX + ' ' + sel

def emit(items, ind=''):
    out = []
    for pre, body in items:
        if isinstance(body, list):
            inner = emit(body, ind + '  ')
            if inner:
                out.append(f'{ind}{pre} {{\n' + '\n'.join(inner) + f'\n{ind}}}')
            continue
        if pre.startswith('@') or re.match(r'^(from|to|\d+%)', pre):
            continue  # @font-face · @keyframes 등은 건너뛰어요
        decls = []
        for d in split_decls(body):
            if ':' not in d:
                continue
            p, v = d.split(':', 1)
            p, v = p.strip(), v.strip()
            if p.startswith('--'):
                # 색이 든 변수 + 다른 변수를 가리키는 변수(var(...))도 따라 써요 — 뒤에서 덮어쓴 밝은 값이 다크에서도 이기게
                if not (COLOR_RE.search(v) or 'var(' in v) or 'url(' in v:
                    continue
            elif not COLOR_PROPS.match(p):
                continue
            imp = ''
            if re.search(r'!\s*important\s*$', v, re.I):
                v = re.sub(r'\s*!\s*important\s*$', '', v, flags=re.I)
                imp = ' !important'
            decls.append(f'{p}: {map_value(p, v)}{imp};')
        if not decls:
            continue
        # 이미 다크 모드용으로 손으로 쓴 규칙(data-theme)은 건너뛰어요 — 두 번 뒤집지 않게
        sel_list = [s for s in split_selectors(pre) if 'data-theme' not in s]
        if not sel_list:
            continue
        sels = ', '.join(prefix(s) for s in sel_list)
        out.append(f'{ind}{sels} {{ ' + ' '.join(decls) + ' }')
    return out

chunks = ['/* [다크 모드] 자동 생성 파일 — 손으로 고치지 마세요.\n   앱 CSS 의 색 선언을 그대로 따라 쓰면서 보랏빛 밤 팔레트로 옮겨요 (OKLab · 보라 계열 유지).\n   :root[data-theme="dark"] 일 때만 적용돼요. 다시 만들 때: darkgen.py */']
for f in FILES:
    src = strip_comments(open(f'{SRC}/{f}', encoding='utf-8').read())
    items, _ = parse_block(src, 0)
    rules = emit(items)
    chunks.append(f'\n/* ---- {f} ---- */\n' + '\n'.join(rules))
open(OUT, 'w', encoding='utf-8').write('\n'.join(chunks) + '\n')
print('written', OUT)
