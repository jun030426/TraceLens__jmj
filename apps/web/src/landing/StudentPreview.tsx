/**
 * [랜딩 · 하루의 학습] 학생용 페이지 미리보기 (11/18)
 *   실제 학생 화면(AI 강의 · 오늘의 이론 · 오늘의 실습 · AI 질문 · 학습 기록 취약도)을 작게 다시 그린 축소판이에요.
 *   progress(0 → 1) 에 맞춰 화면 안에서 실제로 쓰는 것처럼 움직여요.
 *     자료   — AI 강의: 강의 단계가 차례로 켜지고, 칠판에 스택이 쌓이고, 자막이 써져요
 *     이론   — 오늘의 이론: 보기를 고르고 '정답 확인' → 정답 · 해설이 펼쳐져요
 *     실습   — 오늘의 실습: 빈칸 두 개를 채우고 '코드 실행' → 실행 결과가 나와요
 *     AI 질문 — 질문이 올라가고, 답변이 써지고, 강의 자료 근거가 붙어요
 *     학습 기록 — 취약도: 점수 고리와 막대가 차올라요
 * - 화면은 1120 × 700 크기로 그린 뒤, 받침 크기에 맞춰 통째로 줄여요 (글자 비율이 그대로 유지돼요)
 * - 스타일: landing/lerny-student-preview.css (모든 클래스는 sp- 로 시작)
 * - 되돌리기: LandingNew.tsx 의 USE_STUDENT_PREVIEW 를 false 로 바꾸면 예전 데모로 돌아가요
 */
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  lazy,
  Suspense,
} from "react";
import "./lerny-student-preview.css";
import type { Stage3DVar } from "./Stage3DPreview";

// 11/18: 실습 시각화는 실제 앱 3D 무대로 — three.js 가 커서 미리보기가 그 단계에 닿을 때 따로 불러와요
const USE_3D_STAGE = true;
const Stage3DPreview = lazy(() => import("./Stage3DPreview"));

const W = 1000; // 11/18 밤: 1120 → 1000 (같은 칸에 더 좁게 그려서, 줄였을 때 글자 · 칸이 더 커 보여요)
const H = 900; // 11/18: 700 → 820 → 900 (하루의 학습 화면을 세로로 더 길게)
// 11/18: 창 틀 · 앱 위 막대 없이 페이지 내용(위 막대 아래)만 보여줘요. false 면 브라우저 창 + 앱 위 막대까지 보여요
const CONTENT_ONLY = true;
const TOP_H = 56; // 앱 위 막대 높이
const CHROME_H = 34; // 브라우저 창 위 막대 높이
const VIEW_H = CONTENT_ONLY ? H - TOP_H : H + CHROME_H;

const clamp = (v: number) => Math.min(1, Math.max(0, v));
/** p 가 a → b 를 지나는 동안 0 → 1 */
const seg = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
/** 타자 치듯 글자가 하나씩 */
const typed = (text: string, p: number, a: number, b: number) =>
  text.slice(0, Math.round(text.length * seg(p, a, b)));
const ease = (t: number) => 1 - Math.pow(1 - t, 3);

type StepKey = "material" | "quiz" | "code" | "chat" | "stats";

const NAV = ["강의실", "AI 강의", "AI 질문", "퀴즈", "학습 기록"];
const ACTIVE: Record<StepKey, string> = {
  material: "AI 강의",
  quiz: "퀴즈",
  code: "퀴즈",
  chat: "AI 질문",
  stats: "학습 기록",
};
const URL: Record<StepKey, string> = {
  material: "lerny.app/classrooms/lectures",
  quiz: "lerny.app/quiz/today",
  code: "lerny.app/classrooms/practice",
  chat: "lerny.app/ai",
  stats: "lerny.app/attendance",
};

export default function StudentPreview({
  step,
  progress,
}: {
  step: string;
  progress: number;
}) {
  const key = (step in ACTIVE ? step : "material") as StepKey;
  const boxRef = useRef<HTMLDivElement>(null);
  const [k, setK] = useState(0.7);

  // 받침 크기에 맞춰 1120 × 700(+ 창 위 막대) 화면을 통째로 줄여요
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const fit = () => {
      const r = el.getBoundingClientRect();
      if (r.width && r.height) setK(Math.min(r.width / W, r.height / VIEW_H));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div className="sp-box" ref={boxRef}>
      <div
        className={`sp-win${CONTENT_ONLY ? " is-content" : ""}`}
        style={{ width: W * k, height: VIEW_H * k }}
      >
        <div className="sp-scale" style={{ transform: `scale(${k})` }}>
          {!CONTENT_ONLY && (
            <div className="sp-chrome">
              <i />
              <i />
              <i />
              <span className="sp-url">{URL[key]}</span>
            </div>
          )}
          <div
            className="sp-canvas"
            style={{ width: W, height: CONTENT_ONLY ? H - TOP_H : H }}
          >
            {!CONTENT_ONLY && (
              <div className="sp-top">
                <img className="sp-logo" src="/lerny-logo.png" alt="" />
                <div className="sp-nav">
                  {NAV.map((n) => (
                    <span
                      key={n}
                      className={n === ACTIVE[key] ? "on" : undefined}
                    >
                      {n}
                    </span>
                  ))}
                  <b className="sp-avatar">학</b>
                </div>
              </div>
            )}
            <div className="sp-body">
              {key === "material" && <LecturePage p={progress} />}
              {key === "quiz" && <QuizPage p={progress} />}
              {key === "code" && <PracticePage p={progress} />}
              {key === "chat" && <ChatPage p={progress} />}
              {key === "stats" && <WeakPage p={progress} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type CursorPoint = {
  at: number;
  x?: number;
  y?: number;
  to?: string;
  click?: boolean;
};

/** 화면 위를 움직이는 마우스 — 지점들 사이를 부드럽게 옮겨 가고, 누를 때 살짝 작아져요.
 *  to 에 data-cur 이름을 주면 그 버튼 · 칸의 가운데를 찾아가요 (x, y 는 직접 좌표) */
function Cursor({ p, path }: { p: number; path: CursorPoint[] }) {
  const ref = useRef<SVGSVGElement>(null);
  const [pts, setPts] = useState<{ x: number; y: number }[]>(() =>
    path.map((pt) => ({ x: pt.x ?? 0, y: pt.y ?? 0 })),
  );
  useLayoutEffect(() => {
    const root = ref.current?.parentElement;
    if (!root) return;
    const rr = root.getBoundingClientRect();
    const k = rr.width / root.offsetWidth || 1;
    const next = path.map((pt) => {
      if (!pt.to) return { x: pt.x ?? 0, y: pt.y ?? 0 };
      const el = root.querySelector(`[data-cur="${pt.to}"]`);
      if (!el) return { x: pt.x ?? 0, y: pt.y ?? 0 };
      const r = el.getBoundingClientRect();
      return {
        x: (r.left - rr.left + Math.min(r.width * 0.5, 60)) / k,
        y: (r.top - rr.top + r.height * 0.55) / k,
      };
    });
    if (
      next.some(
        (n, i) =>
          Math.abs(n.x - pts[i].x) > 0.5 || Math.abs(n.y - pts[i].y) > 0.5,
      )
    )
      setPts(next);
  });
  let x = pts[0].x;
  let y = pts[0].y;
  let down = false;
  for (let i = 1; i < path.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    if (p >= path[i].at) {
      x = b.x;
      y = b.y;
      if (path[i].click && p < path[i].at + 0.04) down = true;
    } else if (p > path[i - 1].at) {
      const t = ease(seg(p, path[i - 1].at, path[i].at));
      x = a.x + (b.x - a.x) * t;
      y = a.y + (b.y - a.y) * t;
      break;
    } else break;
  }
  return (
    <svg
      ref={ref}
      className={`sp-cursor${down ? " is-down" : ""}`}
      style={{ left: x, top: y }}
      width="22"
      height="26"
      viewBox="0 0 22 26"
      aria-hidden="true"
    >
      <path
        d="M2 2 L2 21 L7.5 16 L11 24 L14.5 22.5 L11 14.8 L18.5 14.5 Z"
        fill="#2b2230"
        stroke="#fff"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PageHead({
  title,
  sub,
  right,
}: {
  title: string;
  sub: string;
  right?: ReactNode;
}) {
  return (
    <div className="sp-head">
      <h4>{title}</h4>
      <span>{sub}</span>
      {right && <em>{right}</em>}
    </div>
  );
}

/* ───────── 자료 — AI 강의 ─────────
 * 화면 속 마우스가 1주차를 눌러 펼치고 → 영상을 누르면 → 왼쪽 플레이어에서 자동 재생돼요.
 * 영상은 public/lecture-demo.mp4 (바꾸려면 아래 LECTURE_VIDEO_SRC 의 주소만 바꾸면 돼요). */
const LECTURE_VIDEO_SRC = "/lecture-demo.mp4"; // AI 강사가 len() 을 설명하는 5초 영상 (소리 없이, 반복 재생)

const WEEKS = [
  { w: 1, t: "파이썬 문자열", n: "영상 2개" },
  { w: 2, t: "배열과 리스트", n: "영상 2개" },
  { w: 3, t: "연결 리스트", n: "영상 1개" },
  { w: 4, t: "스택", n: "영상 2개" },
  { w: 5, t: "큐와 덱", n: "영상 3개" },
];

// 11/18 밤: 영상 소리 — 브라우저는 소리 있는 자동 재생을 막아서 처음엔 꺼 두고, 스피커 아이콘을 누르면 켜져요 (단계가 바뀌어도 기억해요)
let lectureSoundOn = false;

function SoundIcon({ on }: { on: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 15h-2a1 1 0 0 1 -1 -1v-4a1 1 0 0 1 1 -1h2l3.5 -4.5a.8 .8 0 0 1 1.5 .5v14a.8 .8 0 0 1 -1.5 .5l-3.5 -4.5" />
      {on ? (
        <>
          <path d="M15 8a5 5 0 0 1 0 8" />
          <path d="M17.7 5a9 9 0 0 1 0 14" />
        </>
      ) : (
        <path d="M16 10l4 4m0 -4l-4 4" />
      )}
    </svg>
  );
}

function LecturePage({ p }: { p: number }) {
  const open = p >= 0.14; // 1주차를 눌러 펼침
  const picked = p >= 0.3; // 영상을 골라요 (첫 장면 + 가운데 재생 버튼)
  const playing = p >= 0.44; // 재생 버튼을 눌러 재생 시작
  const full = p >= 0.46; // 누르자마자 영상만 화면 가득 (11/18)
  const played = seg(p, 0.44, 1);
  const sec = Math.min(5, Math.floor(played * 5.5)); // 5초 영상
  const time = `0:${String(sec).padStart(2, "0")}`;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [soundOn, setSoundOn] = useState(lectureSoundOn);
  const toggleSound = () => {
    const next = !soundOn;
    lectureSoundOn = next;
    setSoundOn(next);
    const v = videoRef.current;
    if (v) {
      v.muted = !next;
      if (next && playing) v.play().catch(() => {});
    }
  };
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (playing) v.play().catch(() => {});
    else {
      v.pause();
      v.currentTime = 0;
    }
  }, [playing]);
  return (
    <div className={`sp-lecture${full ? " is-full" : ""}`}>
      <PageHead
        title="AI 강의"
        sub="개념을 보고, 직접 풀어보세요."
        right="자료구조 · 2026학년도 2학기 · 01분반"
      />
      <div className="sp-lecture-grid">
        <div className={`sp-player${playing ? " is-playing" : ""}${full ? " is-full" : ""}`}>
          <div className="sp-player-top">
            <span>Lerny 강의실</span>
            <b>
              {playing
                ? "1주차 · len()으로 문자열 길이 세기"
                : "강의를 선택해 주세요"}
            </b>
          </div>
          {/* 영상 칸 — 비어 있어요 (LECTURE_VIDEO_SRC) */}
          <div className="sp-video">
            {LECTURE_VIDEO_SRC && (
              <video
                ref={videoRef}
                src={LECTURE_VIDEO_SRC}
                muted={!soundOn}
                playsInline
                loop
                preload="auto"
                style={{ opacity: picked ? 1 : 0 }}
              />
            )}
            {picked && LECTURE_VIDEO_SRC && (
              <button
                type="button"
                className={`sp-sound${soundOn ? " on" : ""}`}
                onClick={toggleSound}
                aria-label={soundOn ? "소리 끄기" : "소리 켜기"}
                title={soundOn ? "소리 끄기" : "소리 켜기"}
              >
                <SoundIcon on={soundOn} />
                <span>{soundOn ? "소리 끄기" : "소리 켜기"}</span>
              </button>
            )}
            {!picked && (
              <div className="sp-video-idle">
                <b className="sp-play big" />
                <span>왼쪽 목록에서 주차와 영상을 골라 주세요</span>
              </div>
            )}
            {picked && !playing && (
              <div className="sp-video-ready">
                <b
                  className={`sp-play big${p >= 0.42 ? " pressed" : ""}`}
                  data-cur="play"
                />
              </div>
            )}
          </div>
          <div className="sp-player-bar">
            <b className={playing ? "sp-pause" : "sp-play"} />
            <span className="sp-time">
              <i style={{ width: `${Math.min(1, played * 1.1) * 100}%` }} />
            </span>
            <small>{playing ? `${time} / 0:05` : "0:00 / 0:05"}</small>
          </div>
        </div>
        <aside className="sp-weeks">
          <h5>
            AI 강의 자료 <small>16개 주차</small>
          </h5>
          {WEEKS.map((wk) => {
            const isOpen = wk.w === 1 && open;
            return (
              <div
                key={wk.w}
                className={`sp-week-wrap${isOpen ? " open" : ""}`}
              >
                <div className="sp-week" data-cur={`week${wk.w}`}>
                  <small>0{wk.w}</small>
                  <span>
                    {wk.w}주차 <b>{wk.t}</b>
                  </span>
                  <em>
                    {wk.n} {isOpen ? "−" : "+"}
                  </em>
                </div>
                {wk.w === 1 && (
                  <div className="sp-week-videos">
                    <div
                      className={`sp-video-item${picked ? " on" : ""}`}
                      data-cur="video1"
                    >
                      <b>01</b>
                      <span>
                        len()으로 문자열 길이 세기
                        <small>{playing ? "재생 중" : "0:05"}</small>
                      </span>
                    </div>
                    <div className="sp-video-item">
                      <b>02</b>
                      <span>
                        인덱스로 글자 꺼내기<small>3:20</small>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </aside>
      </div>
      <Cursor
        p={p}
        path={[
          { at: 0, x: 560, y: 600 },
          { at: 0.12, to: "week1", click: true },
          { at: 0.28, to: "video1", click: true },
          { at: 0.41, to: "play", click: true },
          { at: 0.7, x: 860, y: 560 },
          { at: 1, x: 900, y: 590 },
        ]}
      />
    </div>
  );
}

/* ───────── 이론 — 오늘의 이론 ─────────
 * 마우스가 '힌트 보기' → 힌트가 펼쳐지고 → 보기 3을 고르고 → '정답 확인' → 정답 표시와 해설까지 보여줘요. */
function QuizPage({ p }: { p: number }) {
  const hint = ease(seg(p, 0.14, 0.24));
  const picked = p >= 0.42;
  const checked = p >= 0.6;
  const reveal = ease(seg(p, 0.6, 0.74));
  const opts = [
    "1이 나온다",
    "2가 나온다",
    "3이 나온다",
    "아무것도 나오지 않는다",
  ];
  return (
    <div className="sp-quiz">
      <PageHead
        title="오늘의 이론"
        sub="한 문항씩 풀고 '정답 확인'을 누르면 바로 정답과 해설이 나와요."
        right={`${checked ? 1 : 0} / 3문항 확인`}
      />
      <div className="sp-tabs">
        {["1번", "2번", "3번"].map((t, i) => (
          <span key={t} className={i === 0 ? "on" : undefined}>
            {i === 0 && checked ? "1번 정답" : t}
          </span>
        ))}
      </div>
      <div className="sp-card sp-quiz-card">
        <small>1 / 3 · 객관식 · 4주차 스택</small>
        <h5>
          스택에 1, 2, 3을 차례로 push 한 뒤 pop 을 한 번 하면 나오는 값은?
        </h5>
        <div className="sp-opts">
          {opts.map((o, i) => (
            <div
              key={o}
              className={`sp-opt${picked && i === 2 ? " on" : ""}${checked && i === 2 ? " ok" : ""}`}
              data-cur={`opt${i + 1}`}
            >
              <i />
              <b>{i + 1}</b>
              {o}
              {checked && i === 2 && <em>정답</em>}
            </div>
          ))}
        </div>
        <div className={`sp-hint${hint > 0 ? " open" : ""}`}>
          <div className="sp-hint-row">
            <b>힌트</b>
            <span className="sp-hint-pill">
              <i style={{ width: `${hint * 100}%` }} />
            </span>
            <small>남은 힌트 {hint >= 1 ? 0 : 1}</small>
            <span
              className={`sp-btn small line${p >= 0.12 && p < 0.16 ? " pressed" : ""}`}
              data-cur="hint"
            >
              {hint > 0 ? "힌트 닫기" : "힌트 보기"}
            </span>
          </div>
          <div
            className="sp-hint-body"
            style={{ maxHeight: hint * 60, opacity: hint }}
          >
            스택은 <b>가장 나중에 넣은 값</b>이 맨 위에 있어요. pop 은 맨 위에서
            꺼내요.
          </div>
        </div>
        <div
          className="sp-explain"
          style={{
            opacity: reveal,
            transform: `translateY(${(1 - reveal) * 10}px)`,
            maxHeight: reveal * 120,
          }}
        >
          <b>정답 3번 · 해설</b> 스택은 마지막에 넣은 값을 가장 먼저 꺼내는 LIFO
          구조예요. 1, 2, 3 순서로 넣었으니 pop 하면 3이 나와요.
          <span className="sp-src">근거 · 4주차 스택 3쪽</span>
        </div>
        <div className="sp-quiz-foot">
          <span className="sp-btn ghost">이전 문항</span>
          <span
            className={`sp-btn${p >= 0.58 && p < 0.62 ? " pressed" : ""}`}
            data-cur="check"
          >
            {checked ? "다음 문항 →" : "정답 확인"}
          </span>
        </div>
      </div>
      <Cursor
        p={p}
        path={[
          { at: 0, x: 760, y: 640 },
          { at: 0.12, to: "hint", click: true },
          { at: 0.4, to: "opt3", click: true },
          { at: 0.58, to: "check", click: true },
          { at: 1, to: "check" },
        ]}
      />
    </div>
  );
}

/* ───────── 실습 — 오늘의 실습 ─────────
 * 앞 절반: 문제 1 빈칸 채우기 + 시각화 ① 배열 장면 (빈칸 앞에서 멈추고, 값이 쌓이는 걸 보며 채워요)
 * 뒤 절반: 문제 2 직접 작성(풀코딩) + 시각화 ② 한 줄씩 실행 흐름 (지금 줄 · 변수 표 · 최댓값 왕관) */
const SCORES = [80, 95, 70, 88];
const NUMS = [3, 8, 2, 12];
const FULL_CODE = [
  "def find_max(nums):",
  "    best = nums[0]",
  "    for n in nums:",
  "        if n > best:",
  "            best = n",
  "    return best",
  "",
  "print(find_max([3, 8, 2, 12]))",
];

function PracticePage({ p }: { p: number }) {
  const second = p >= 0.5;
  return (
    <div className="sp-practice">
      <PageHead
        title="오늘의 실습"
        sub="자료구조 · 01분반 · 수업 언어 Python"
        right={second ? "2 / 2" : "1 / 2"}
      />
      {second ? (
        <FullCoding r={seg(p, 0.5, 1)} />
      ) : (
        <BlankCoding q={seg(p, 0, 0.5)} />
      )}
    </div>
  );
}

function PracticeTabs({ second, kind }: { second: boolean; kind: string }) {
  return (
    <div className="sp-code-tabs">
      <span className={second ? undefined : "on"}>문제 1</span>
      <span className={second ? "on" : undefined}>문제 2</span>
      <em>{kind}</em>
    </div>
  );
}

/* 실행하면 줄마다 위에 붙는 초록 주석 — 실제 앱(visualization/screen/lineComment.ts)이 만드는 문장 그대로예요 */
const BLANK_CMT = [
  "scores에 리스트를 만들어 담아요",
  "total에 0을(를) 넣어요",
  "scores에서 값을 하나씩 꺼내 s에 담으며 반복해요",
  "total에 total + s의 값을 넣어요",
  "average에 total / len(scores)의 값을 넣어요",
  "average을(를) 화면에 출력해요",
];
const FULL_CMT = [
  "함수 find_max(nums)를 만들어요",
  "best에 nums[0]의 값을 넣어요",
  "nums에서 값을 하나씩 꺼내 n에 담으며 반복해요",
  "n > best이(가) 참인지 확인해요",
  "best에 n의 값을 넣어요",
  "best의 값을 돌려주고 함수를 끝내요",
  "",
  "find_max([3, 8, 2, 12])을(를) 화면에 출력해요",
];

/** 힌트 칸 — 실제 앱의 힌트 카드처럼 '힌트' 제목 · 연 힌트/남은 힌트 칸 · [힌트 n 보기] 버튼. 누르면 첫 힌트가 열려요 */
function HintBox({
  open,
  total,
  name,
  text,
}: {
  open: boolean;
  total: number;
  name: (n: number) => string;
  text: string;
}) {
  const used = open ? 1 : 0;
  return (
    <div className={`sp-phint${open ? " open" : ""}`}>
      <div className="sp-phint-head">
        <b>힌트</b>
        <span className="sp-phint-meter">
          {Array.from({ length: total }, (_, i) => (
            <i key={i} className={i < used ? "on" : undefined} />
          ))}
        </span>
        <small>
          남은 힌트 <b>{total - used}</b>
        </small>
        <span
          className={`sp-btn small soft${open ? "" : " glow"}`}
          data-cur="hint"
        >
          {name(used + 1)} 보기
        </span>
      </div>
      {open && (
        <p className="sp-phint-body">
          <em>{name(1)}</em>
          {text}
        </p>
      )}
    </div>
  );
}

function BlankCoding({ q }: { q: number }) {
  // 힌트 열기 → 빈칸 ① · ② 채우기 → 코드 실행 → 줄 주석 + 캐릭터가 한 바퀴씩 움직여요
  const hint = q >= 0.09;
  const b1 = typed("0", q, 0.17, 0.2);
  const b2 = typed("total + s", q, 0.25, 0.35);
  const filled = (b1 ? 1 : 0) + (b2.length === 9 ? 1 : 0);
  const ran = q >= 0.42;
  const looping = seg(q, 0.46, 0.86);
  const idx = q < 0.46 ? -1 : Math.min(3, Math.floor(looping * 4));
  const done = q >= 0.88;
  const total =
    !ran ? null : idx < 0 ? 0 : SCORES.slice(0, idx + 1).reduce((x, y) => x + y, 0);
  const line: number = !ran ? 0 : idx < 0 ? 2 : done ? 6 : (looping * 4) % 1 < 0.4 ? 3 : 4;
  const caption = !ran
    ? q < 0.17
      ? "빈칸 ① 앞에서 멈춰 있어요. 힌트를 열어 봐요."
      : "빈칸을 채우고 실행하면 캐릭터가 움직여요."
    : done
      ? "평균 83.25 — 출력이 정답과 같아요."
      : idx < 0
        ? "total 로봇이 0 을 들고 시작해요."
        : `젤리 ${idx}번(${SCORES[idx]})을 꺼내 total = ${total}`;
  const step = (looping * 4) % 1;
  return (
    <div className="sp-practice-grid">
      <div className="sp-card sp-code-card">
        <PracticeTabs second={false} kind="빈칸 채우기" />
        <div className="sp-code-q">
          <h5>문제1. 점수 평균 구하기</h5>
          <p>점수를 모두 더한 뒤 개수로 나눠 평균을 구해요. 두 빈칸을 채워 보세요.</p>
        </div>
        <HintBox
          open={hint}
          total={3}
          name={(n) => `힌트 ${n}`}
          text="강의 4주차 9쪽 · 합계는 아무것도 더하지 않은 값에서 시작해, 반복마다 지금 값을 더해요."
        />
        <div className="sp-code-bar">
          <b>빈칸 채우기</b>
          <span
            className={`sp-btn small${q >= 0.4 && q < 0.45 ? " pressed" : ""}`}
            data-cur="run"
          >
            코드 실행
          </span>
          <span className="sp-btn small ghost">최종 제출 →</span>
        </div>
        <div className="sp-code-file">
          <span>main.py</span>
          <span>{ran ? "실행했어요 · 줄마다 설명이 붙었어요" : `빈칸 ${filled}/2 채움`}</span>
        </div>
        <pre className={`sp-code${ran ? " has-cmt" : ""}`}>
          <code>
            <CodeLine n={1} on={line === 1} cmt={ran ? BLANK_CMT[0] : ""}>
              scores = [80, 95, 70, 88]
            </CodeLine>
            <CodeLine n={2} on={line === 2} cmt={ran ? BLANK_CMT[1] : ""}>
              total = <Blank v={b1} w={44} mark="①" cur="blank1" />
            </CodeLine>
            <CodeLine n={3} on={line === 3} cmt={ran ? BLANK_CMT[2] : ""}>
              <span className="kw">for</span> s <span className="kw">in</span>{" "}
              scores:
            </CodeLine>
            <CodeLine n={4} on={line === 4} cmt={ran ? BLANK_CMT[3] : ""} indent={4}>
              {"    "}total = <Blank v={b2} w={110} mark="②" cur="blank2" />
            </CodeLine>
            <CodeLine n={5} on={line === 5} cmt={ran ? BLANK_CMT[4] : ""}>
              average = total / len(scores)
            </CodeLine>
            <CodeLine n={6} on={line === 6} cmt={ran ? BLANK_CMT[5] : ""}>
              <span className="fn">print</span>(average)
            </CodeLine>
          </code>
        </pre>
      </div>
      <div className="sp-card sp-run">
        <div className="sp-code-tabs">
          <span>실행 결과</span>
          <span className="on">시각화</span>
          <em className="soft">① 빈칸 앞에서 멈춤</em>
        </div>
        <div className="sp-viz">
          <VizStage
            name="scores"
            arr={SCORES}
            cur={idx}
            hop={idx >= 0 && !done && step < 0.5}
            robots={[
              {
                name: "total",
                v: total,
                tag: !ran ? undefined : idx < 0 ? "신규" : done ? undefined : "변경",
                talk: idx >= 0 && !done && step >= 0.4,
              },
              {
                name: "s",
                v: idx >= 0 ? SCORES[idx] : null,
                tag: idx === 0 && !done ? "신규" : idx > 0 && !done ? "변경" : undefined,
                talk: idx >= 0 && !done && step < 0.4,
              },
              { name: "average", v: done ? 83.25 : null, tag: done ? "신규" : undefined, talk: done },
            ]}
          />
          <p className="sp-viz-cap">{caption}</p>
        </div>
      </div>
      <Cursor
        p={q}
        path={[
          { at: 0, x: 420, y: 620 },
          { at: 0.07, to: "hint", click: true },
          { at: 0.15, to: "blank1", click: true },
          { at: 0.23, to: "blank2", click: true },
          { at: 0.38, to: "run", click: true },
          { at: 0.5, x: 760, y: 560 },
          { at: 1, x: 700, y: 600 },
        ]}
      />
    </div>
  );
}

function FullCoding({ r }: { r: number }) {
  // 1단계 힌트 열기 → 코드가 한 글자씩 써지고 → 실행 → 줄 주석 + 한 줄씩 따라가요
  const hint = r >= 0.07;
  const all = FULL_CODE.join("\n");
  const written = typed(all, r, 0.1, 0.34);
  const ran = r >= 0.4;
  const t = seg(r, 0.43, 0.9);
  const k = ran ? Math.min(3, Math.floor(t * 4)) : -1; // 지금 보는 n 의 위치
  const sub = ran ? (t * 4) % 1 : 0;
  const done = r >= 0.92;
  const best = k < 0 ? null : Math.max(...NUMS.slice(0, k + 1));
  const prevBest = k <= 0 ? null : Math.max(...NUMS.slice(0, k));
  const bigger = prevBest !== null && NUMS[k] > prevBest; // 첫 바퀴는 best 가 자기 자신이라 바뀌지 않아요
  const line = !ran
    ? 0
    : done
      ? 8
      : sub < 0.35
        ? 3
        : sub < 0.7 || !bigger
          ? 4
          : 5;
  const shownBest = k < 0 ? null : sub >= 0.7 || k === 0 ? best : prevBest;
  const lines = written.split("\n");
  const bestIdx = shownBest === null ? -1 : NUMS.indexOf(shownBest);
  return (
    <div className="sp-practice-grid">
      <div className="sp-card sp-code-card">
        <PracticeTabs second kind="직접 작성" />
        <div className="sp-code-q">
          <h5>문제2. 가장 큰 값 찾기</h5>
          <p>리스트에서 가장 큰 값을 돌려주는 함수 find_max 를 처음부터 작성해 보세요.</p>
        </div>
        <HintBox
          open={hint}
          total={3}
          name={(n) => `${n}단계`}
          text="첫 값을 best 에 넣어 두고, 나머지 값과 하나씩 비교해 더 크면 바꿔요."
        />
        <div className="sp-code-bar">
          <b>코드 작성</b>
          <span
            className={`sp-btn small${r >= 0.37 && r < 0.42 ? " pressed" : ""}`}
            data-cur="run"
          >
            코드 실행
          </span>
          <span className="sp-btn small ghost">최종 제출 →</span>
        </div>
        <div className="sp-code-file">
          <span>main.py</span>
          <span>{ran ? "실행했어요 · 줄마다 설명이 붙었어요" : `${lines.length}줄`}</span>
        </div>
        <pre className={`sp-code${ran ? " has-cmt" : ""}`}>
          <code>
            {FULL_CODE.map((src, i) => (
              <CodeLine
                key={i}
                n={i + 1}
                on={line === i + 1}
                cmt={ran ? FULL_CMT[i] : ""}
                indent={src.length - src.trimStart().length}
              >
                {lines[i] ?? ""}
                {!ran && i === lines.length - 1 && <i className="sp-caret" />}
              </CodeLine>
            ))}
          </code>
        </pre>
      </div>
      <div className="sp-card sp-run">
        <div className="sp-code-tabs">
          <span>실행 결과</span>
          <span className="on">시각화</span>
          <em className="soft">② 한 줄씩 실행</em>
        </div>
        <div className="sp-viz">
          <VizStage
            name="nums"
            arr={NUMS}
            cur={done ? -1 : k}
            crown={bestIdx}
            hop={k >= 0 && !done && sub < 0.35}
            robots={[
              {
                name: "n",
                v: k >= 0 ? NUMS[k] : null,
                tag: k === 0 && !done ? "신규" : k > 0 && !done && sub < 0.35 ? "변경" : undefined,
                talk: k >= 0 && !done && sub < 0.7,
              },
              {
                name: "best",
                v: shownBest,
                tag: k === 0 && !done ? "신규" : k > 0 && bigger && sub >= 0.7 && !done ? "변경" : undefined,
                talk: (k >= 0 && sub >= 0.7 && !done) || done,
              },
            ]}
          />
          <p className="sp-viz-cap">
            {!ran
              ? "코드를 다 쓰면 실행해서 흐름을 따라가 봐요."
              : done
                ? "출력 12 — 반복이 끝나고 best 가 가장 큰 값이에요."
                : `${line}번 줄 · n = ${NUMS[k]}${line === 4 ? ` · ${NUMS[k]} > ${prevBest ?? NUMS[0]} → ${bigger ? "참" : "거짓"}` : `, best = ${shownBest}`}`}
          </p>
        </div>
      </div>
      <Cursor
        p={r}
        path={[
          { at: 0, x: 300, y: 600 },
          { at: 0.06, to: "hint", click: true },
          { at: 0.33, x: 330, y: 600 },
          { at: 0.37, to: "run", click: true },
          { at: 1, x: 760, y: 610 },
        ]}
      />
    </div>
  );
}

/* ───────── 캐릭터 시각화 (실제 앱 visualization/screen/CharacterStage 를 2D 로 옮겼어요) ─────────
 * 리스트 칸 = 민트 젤리 (머리 위 흰 값 배지, 선반 아래 번호), 변수 = 로봇 (이름표 + 말풍선 값).
 * 지금 보는 칸은 파랑으로 통통 튀고, 새로 생긴 값은 '신규', 바뀐 값은 '변경' 꼬리표가 붙어요 */
type RobotVar = { name: string; v: number | null; tag?: "신규" | "변경"; talk?: boolean };

/** USE_3D_STAGE 면 3D 무대, 아니면 2D 젤리·로봇 */
function VizStage(props: Parameters<typeof CharStage>[0]) {
  if (!USE_3D_STAGE) return <CharStage {...props} />;
  const vars: Stage3DVar[] = props.robots.map(({ name, v, tag }) => ({ name, v, tag }));
  const stepKey = vars.map((x) => `${x.name}=${x.v}`).join("|");
  return (
    <Suspense fallback={<div className="sp-stage3d" />}>
      <Stage3DPreview name={props.name} arr={props.arr} vars={vars} cur={props.cur} stepKey={stepKey} />
    </Suspense>
  );
}

function CharStage({
  name,
  arr,
  cur,
  crown = -1,
  hop,
  robots,
}: {
  name: string;
  arr: number[];
  cur: number;
  crown?: number;
  hop?: boolean;
  robots: RobotVar[];
}) {
  return (
    <div className="sp-stage">
      <div className="sp-shelf">
        <span className="sp-shelf-name">{name}</span>
        <div className="sp-jellies">
          {arr.map((v, i) => (
            <div
              key={i}
              className={`sp-jelly${i === cur ? " cur" : ""}${i === cur && hop ? " hop" : ""}`}
            >
              {i === crown && <span className="sp-crown">👑</span>}
              <span className="sp-badge">{v}</span>
              <svg viewBox="0 0 64 58" width="58" height="52" aria-hidden="true">
                <path
                  className="body"
                  d="M5 50 C5 22 17 4 32 4 C47 4 59 22 59 50 Q59 56 53 56 H11 Q5 56 5 50Z"
                />
                <ellipse cx="22" cy="18" rx="7" ry="4" fill="#fff" opacity=".55" />
                <circle cx="24" cy="34" r="3.2" fill="#2b2230" />
                <circle cx="40" cy="34" r="3.2" fill="#2b2230" />
                <path d="M28 41 Q32 45 36 41" stroke="#2b2230" strokeWidth="2" fill="none" strokeLinecap="round" />
                <ellipse cx="17" cy="40" rx="4" ry="2.4" fill="#ff9fb8" opacity=".5" />
                <ellipse cx="47" cy="40" rx="4" ry="2.4" fill="#ff9fb8" opacity=".5" />
              </svg>
              <small>{i}</small>
            </div>
          ))}
        </div>
      </div>
      <div className="sp-robots">
        {robots.map((rb) => (
          <div key={rb.name} className={`sp-robot${rb.v === null ? " wait" : ""}${rb.talk ? " talk" : ""}`}>
            <span className="sp-bubble">{rb.v === null ? "?" : rb.v}</span>
            <svg viewBox="0 0 64 70" width="60" height="66" aria-hidden="true">
              <line x1="32" y1="3" x2="32" y2="12" stroke="#b58ad6" strokeWidth="3" strokeLinecap="round" />
              <circle cx="32" cy="4" r="4" fill="#b58ad6" />
              <rect x="8" y="12" width="48" height="34" rx="12" className="head" />
              <rect x="15" y="19" width="34" height="20" rx="8" fill="#3b3150" />
              <circle cx="25" cy="29" r="3.4" className="eye" />
              <circle cx="39" cy="29" r="3.4" className="eye" />
              <rect x="18" y="49" width="28" height="17" rx="7" className="head" />
              <rect x="6" y="52" width="9" height="5" rx="2.5" className="head" />
              <rect x="49" y="52" width="9" height="5" rx="2.5" className="head" />
            </svg>
            <span className="sp-nametag">{rb.name}</span>
            {rb.tag && <em className={`sp-tag${rb.tag === "변경" ? " chg" : ""}`}>{rb.tag}</em>}
          </div>
        ))}
      </div>
    </div>
  );
}

function CodeLine({
  n,
  on,
  cmt,
  indent = 0,
  children,
}: {
  n: number;
  on?: boolean;
  cmt?: string;
  indent?: number;
  children: ReactNode;
}) {
  return (
    <>
      {cmt ? (
        <span className="sp-line sp-cmt">
          <span className="ln" />
          {" ".repeat(indent)}# {cmt}
        </span>
      ) : null}
      <span className={`sp-line${on ? " on" : ""}`}>
        <span className="ln">{n}</span>
        {children}
        {"\n"}
      </span>
    </>
  );
}

function Blank({
  v,
  w,
  mark,
  cur,
}: {
  v: string;
  w: number;
  mark?: string;
  cur?: string;
}) {
  return (
    <>
      {!v && mark && <span className="sp-blank-mark">{mark}</span>}
      <span
        className={`sp-blank${v ? " on" : ""}`}
        style={{ minWidth: w }}
        data-cur={cur}
      >
        {v}
      </span>
    </>
  );
}

/* ───────── AI 질문 ───────── */
function ChatPage({ p }: { p: number }) {
  const q = p >= 0.04;
  const thinking = p >= 0.14 && p < 0.26;
  const answer = typed(
    "스택은 마지막에 넣은 것을 먼저 꺼내야 할 때(되돌리기, 함수 호출), 큐는 먼저 들어온 순서대로 처리할 때(대기열, 너비 우선 탐색) 써요.",
    p,
    0.26,
    0.68,
  );
  const src = p >= 0.7;
  const picked = p >= 0.86; // 마우스가 '이해했어요' 상태를 눌러요
  return (
    <div className="sp-chat">
      <aside className="sp-card sp-side">
        <h5>내 강의</h5>
        <div className="sp-course">
          <b>자료구조</b>
          <small>테스트 교수 · 01분반</small>
        </div>
        <div className="sp-prev">이전 질문 찾아보기</div>
        <ul>
          <li>해시 테이블은 왜 빨라요?</li>
          <li>연결 리스트 삽입이 O(1)인 이유</li>
        </ul>
      </aside>
      <div className="sp-card sp-chat-main">
        <div className="sp-chat-head">
          <h5>AI 질문</h5>
          <span>수업 자료에서 답변의 근거를 함께 확인해요.</span>
        </div>
        <div className="sp-msgs">
          <div className="sp-msg me">충돌이 나면 어떻게 해요?</div>
          <div className="sp-msg ai">
            <small>AI 강사</small>
            해시 충돌이 나면 같은 칸에 연결 리스트로 이어 붙이거나, 비어 있는
            다음 칸을 찾아 넣어요.
            <span className="sp-src">6주차 · 해시 테이블 · 7쪽 →</span>
          </div>
          <div className={`sp-msg me${q ? " in" : " hide"}`}>
            스택이랑 큐는 언제 다르게 써요?
          </div>
          {thinking && (
            <div className="sp-msg ai sp-dots">
              <i />
              <i />
              <i />
            </div>
          )}
          {p >= 0.26 && (
            <div className="sp-msg ai in">
              <small>AI 강사</small>
              {answer}
              <span className={`sp-src${src ? "" : " off"}`}>
                4주차 · 스택과 큐 · 3쪽 →
              </span>
            </div>
          )}
          <div className={`sp-react${src ? " on" : ""}`}>
            <span
              className={`sp-state is-understood${picked ? " picked" : ""}`}
              data-cur="state"
            >
              💡 이해했어요
            </span>
            <span className="sp-state is-confused">❓ 헷갈려요</span>
            <span className="sp-state is-stop">🤯 모르겠어요</span>
          </div>
          <div className={`sp-toast${picked ? " on" : ""}`}>
            이해했어요로 기록했어요 · 학습 기록에 반영돼요
          </div>
        </div>
        <div className="sp-input">
          <span>
            {p < 0.04
              ? typed("스택이랑 큐는 언제 다르게 써요?", p, 0, 0.035) ||
                "궁금한 점을 적거나 마이크를 눌러 말해 보세요."
              : "궁금한 점을 적거나 마이크를 눌러 말해 보세요."}
          </span>
          <b>↵</b>
        </div>
      </div>
      <Cursor
        p={p}
        path={[
          { at: 0, x: 900, y: 650 },
          { at: 0.7, x: 860, y: 600 },
          { at: 0.84, to: "state", click: true },
          { at: 1, to: "state" },
        ]}
      />
    </div>
  );
}

/* ───────── 학습 기록 — 취약도 ───────── */
/* ───────── 학습 기록 — 이론 → 실습 → 취약도 탭을 차례로 눌러 보여요 (취약도가 메인이라 가장 길게) ───────── */
const THEORY_REVIEW = [
  { n: "배열과 리스트", d: "최근 독립 풀이에 오답이 있어요. 답안과 해설을 비교해 보세요." },
  { n: "연결 리스트", d: "최근 독립 풀이에 오답이 있어요. 답안과 해설을 비교해 보세요." },
  { n: "스택", d: "최근 독립 풀이에 오답이 있어요. 답안과 해설을 비교해 보세요." },
];
const THEORY_ALL = [
  { w: "1주차", n: "자료구조 개요", s: "기준 충족", ok: true },
  { w: "2주차", n: "배열과 리스트", s: "복습 권장", ok: false },
  { w: "3주차", n: "연결 리스트", s: "복습 권장", ok: false },
];
const PRACTICE_RECENT = [
  { n: "문제2. 가장 큰 값 찾기", k: "직접 작성", r: "통과", ok: true, d: "오늘" },
  { n: "문제1. 점수 평균 구하기", k: "빈칸 채우기", r: "통과", ok: true, d: "오늘" },
  { n: "스택으로 괄호 검사", k: "직접 작성", r: "실행 오류 · IndexError", ok: false, d: "어제" },
  { n: "연결 리스트 뒤집기", k: "빈칸 채우기", r: "결과 다름", ok: false, d: "11/16" },
];

function WeakPage({ p }: { p: number }) {
  const tab = p < 0.26 ? 0 : p < 0.48 ? 1 : 2; // 마우스가 '실습' → '취약도' 탭을 눌러요
  return (
    <div className="sp-weak">
      <div className="sp-card sp-weak-card">
        <div className="sp-head in-card">
          <h4>학습 기록과 복습</h4>
          <span>
            배운 만큼 쌓이는 나의 이해. 개념별 학습과 복습할 내용을 확인해
            보세요.
          </span>
        </div>
        <div className="sp-weak-tabs">
          <span className={tab === 0 ? "on" : undefined}>이론</span>
          <span className={tab === 1 ? "on" : undefined} data-cur="tab-prac">실습</span>
          <span className={tab === 2 ? "on" : undefined} data-cur="weak">
            취약도
          </span>
        </div>
        {tab === 0 && (
          <div className="sp-rec" key="t">
            <div className="sp-rec-pills">
              <span className="on">개념별 학습</span>
              <span>날짜별 기록</span>
            </div>
            <div className="sp-rec-box">
              <small>6주차 학습 중</small>
              <div className="sp-rec-boxh">
                <b>다시 살펴볼 개념</b>
                <small>복습 권장 5개</small>
              </div>
              {THEORY_REVIEW.map((c, i) => (
                <div key={c.n} className="sp-rec-row" style={{ animationDelay: `${i * 90}ms` }}>
                  <span>
                    <b>{c.n}</b>
                    <small>{c.d}</small>
                  </span>
                  <span className="sp-btn small line">강의 자료 보기 →</span>
                </div>
              ))}
            </div>
            <div className="sp-rec-all">
              <b>
                전체 개념 찾아보기 <small>16</small>
              </b>
              {THEORY_ALL.map((c) => (
                <div key={c.n} className="sp-rec-line">
                  <small>{c.w}</small>
                  <b>{c.n}</b>
                  <em className={c.ok ? "ok" : "warn"}>{c.s}</em>
                </div>
              ))}
            </div>
          </div>
        )}
        {tab === 1 && (
          <div className="sp-rec" key="p">
            <div className="sp-rec-boxh plain">
              <span>
                <b>개념별 실습과 복습</b>
                <small>수업에서 배운 개념을 적용한 기록과 다시 살펴볼 내용을 확인해요.</small>
              </span>
              <em className="sp-rec-lang">수업 언어 · Python</em>
            </div>
            <div className="sp-rec-stats">
              <div>
                <small>제출한 문제</small>
                <b>12</b>
              </div>
              <div>
                <small>검증 완료</small>
                <b>9</b>
              </div>
              <div>
                <small>복습할 개념</small>
                <b className="warn">2</b>
              </div>
            </div>
            <div className="sp-rec-all">
              <b>최근 실습 제출</b>
              {PRACTICE_RECENT.map((c, i) => (
                <div key={c.n} className="sp-rec-line" style={{ animationDelay: `${i * 80}ms` }}>
                  <small>{c.d}</small>
                  <b>{c.n}</b>
                  <span className="sp-rec-kind">{c.k}</span>
                  <em className={c.ok ? "ok" : "bad"}>{c.r}</em>
                </div>
              ))}
            </div>
          </div>
        )}
        {tab === 2 && <WeakStats p={seg(p, 0.48, 1)} />}
      </div>
      <Cursor
        p={p}
        path={[
          { at: 0, x: 700, y: 420 },
          { at: 0.22, to: "tab-prac", click: true },
          { at: 0.44, to: "weak", click: true },
          { at: 0.85, to: "review", click: false },
          { at: 1, to: "review" },
        ]}
      />
    </div>
  );
}

function WeakStats({ p }: { p: number }) {
  const tab = true;
  const t = ease(seg(p, 0.16, 0.62));
  const score = Math.round(44 * t);
  const C = 2 * Math.PI * 54;
  const top = [
    { n: "배열과 리스트", w: "2주차", s: 82, tone: "bad", label: "취약해요" },
    { n: "스택", w: "4주차", s: 63, tone: "mid", label: "조금 약해요" },
    { n: "큐와 덱", w: "5주차", s: 47, tone: "mid", label: "조금 약해요" },
  ];
  const rings = [
    { n: "연결 리스트", s: 34, tone: "mid" },
    { n: "해시 테이블", s: 28, tone: "good" },
    { n: "자료구조 개요", s: 12, tone: "good" },
  ];
  return (
    <>
        <div className={`sp-weak-main${tab ? " on" : ""}`}>
          <div className="sp-weak-hero">
            <svg
              width="150"
              height="150"
              viewBox="0 0 150 150"
              aria-hidden="true"
            >
              <circle
                cx="75"
                cy="75"
                r="54"
                fill="none"
                stroke="#f3e3c6"
                strokeWidth="16"
              />
              <circle
                cx="75"
                cy="75"
                r="54"
                fill="none"
                stroke="#fbd96b"
                strokeWidth="16"
                strokeLinecap="round"
                strokeDasharray={`${C * 0.44 * t} ${C}`}
                transform="rotate(-90 75 75)"
              />
              <text x="75" y="80" textAnchor="middle" className="sp-ring-num">
                {score}
                <tspan className="sp-ring-unit">점</tspan>
              </text>
              <text x="75" y="102" textAnchor="middle" className="sp-ring-cap">
                평균 취약도
              </text>
            </svg>
            <div className="sp-weak-copy">
              <h5>
                지금 가장 약한 개념은 <mark>배열과 리스트</mark>예요
              </h5>
              <p>
                최근 <b>26</b>문제 중 <b>18</b>문제를 맞혔어요
              </p>
              <div className="sp-tri">
                <i style={{ flex: 0.3 * t + 0.001 }} />
                <i style={{ flex: 0.45 * t + 0.001 }} />
                <i style={{ flex: 0.15 * t + 0.001 }} />
                <span style={{ flex: 1 - 0.9 * t }} />
              </div>
              <span
                className={`sp-btn soft${p > 0.7 ? " glow" : ""}`}
                data-cur="review"
              >
                「배열과 리스트」 바로 복습하기 →
              </span>
            </div>
          </div>
          <div className="sp-weak-sub">
            먼저 복습할 개념 <b>TOP 3</b>
          </div>
          <div className="sp-top3">
            {top.map((c, i) => {
              const tt = ease(seg(p, 0.24 + i * 0.08, 0.66 + i * 0.08));
              return (
                <div key={c.n} className={`sp-topc tone-${c.tone}`}>
                  <div className="sp-top-h">
                    <strong>0{i + 1}</strong>
                    <b>{c.n}</b>
                    <small>{c.w}</small>
                    <em>{c.label}</em>
                  </div>
                  <div className="sp-top-bar">
                    <i style={{ width: `${c.s * tt}%` }} />
                  </div>
                  <div className="sp-top-s">
                    {Math.round(c.s * tt)}
                    <small>점</small>
                  </div>
                </div>
              );
            })}
            {rings.map((r, i) => {
              const tt = ease(seg(p, 0.34 + i * 0.06, 0.8 + i * 0.05));
              const c = 2 * Math.PI * 16;
              return (
                <div key={r.n} className={`sp-mini tone-${r.tone}`}>
                  <svg
                    width="40"
                    height="40"
                    viewBox="0 0 40 40"
                    aria-hidden="true"
                  >
                    <circle
                      cx="20"
                      cy="20"
                      r="16"
                      fill="none"
                      stroke="#efe9f1"
                      strokeWidth="5"
                    />
                    <circle
                      cx="20"
                      cy="20"
                      r="16"
                      fill="none"
                      strokeWidth="5"
                      strokeLinecap="round"
                      strokeDasharray={`${(c * r.s * tt) / 100} ${c}`}
                      transform="rotate(-90 20 20)"
                    />
                  </svg>
                  <span>
                    <b>{r.n}</b>
                    <small>{Math.round(r.s * tt)}점</small>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
    </>
  );
}
