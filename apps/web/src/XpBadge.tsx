/* [헤더] 강의실 메뉴 왼쪽 XP 등급 캐릭터 — 지금 등급의 마스코트만 보여요.
   마우스를 올리거나 누르면 등급판(다음 등급까지 남은 XP, XP를 받은 곳)이 열려요.
   강의실 안의 화면(강의실 · AI 강의 · AI 질문 · 퀴즈 · 학습 기록 · 실습)에서만 보여요 — App.tsx
   규칙·등급 기준: xp/xpRules.ts · 실습 기록: xp/practiceXp.ts · 스타일: xp-badge.css */
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "./api";
import { computeXp, GRADES, XP_RULES, type StreakInfo, type TheoryRecord, type XpSummary } from "./xp/xpRules";
import { practiceCounts, XP_CHANGED } from "./xp/practiceXp";
import "./xp-badge.css";

// 등급마다 움직임이 달라요 — 높은 등급은 통통 뛰고, 낮은 등급은 느릿하게 출렁여요 (xp-badge.css)
const tierOf = (label: string) => (["A+", "A0", "B+"].includes(label) ? "high" : ["D", "F"].includes(label) ? "low" : "mid");

type Page = { items: TheoryRecord[]; has_more?: boolean };

async function loadTheory() {
  const items: TheoryRecord[] = [];
  for (let offset = 0, i = 0; i < 20; i++, offset += 100) {
    const page = await api<Page>(`/my/learning-sessions?limit=100&offset=${offset}`);
    items.push(...page.items);
    if (!page.has_more || page.items.length === 0) break;
  }
  return items;
}

export function XpBadge({ userId }: { userId: string }) {
  const { pathname } = useLocation();
  const [server, setServer] = useState<{ theory: TheoryRecord[]; streak?: StreakInfo }>();
  const [failed, setFailed] = useState(false);
  const [practiceRev, setPracticeRev] = useState(0);
  const [open, setOpen] = useState(false);
  // 'XP 받는 방법'은 판을 열 때마다 접힌 채로 시작해요
  const [rulesOpen, setRulesOpen] = useState(false);
  useEffect(() => {
    if (!open) setRulesOpen(false);
  }, [open]);
  // 마우스를 올려서 연 판은 마우스가 벗어나면 닫히고, 눌러서 연 판은 바깥을 누를 때까지 열려 있어요
  const [pinned, setPinned] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const hoverOpen = () => {
    window.clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const hoverClose = () => {
    if (pinned) return;
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(false), 180);
  };
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);
  const [levelUp, setLevelUp] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  // 화면을 옮길 때마다 서버 기록을 다시 읽어요 (퀴즈를 제출하고 돌아오면 바로 반영)
  useEffect(() => {
    let active = true;
    // 서버 기록 하나를 못 불러와도 캐릭터는 보이게, 불러온 것만으로 계산해요
    Promise.allSettled([loadTheory(), api<StreakInfo>("/my/learning-streak")]).then(([theory, streak]) => {
      if (!active) return;
      setServer({
        theory: theory.status === "fulfilled" ? theory.value : [],
        streak: streak.status === "fulfilled" ? streak.value : undefined,
      });
      setFailed(theory.status === "rejected" && streak.status === "rejected");
    });
    return () => {
      active = false;
    };
  }, [userId, pathname]);

  // 실습에서 정답을 맞히면 바로 다시 계산해요
  useEffect(() => {
    const bump = () => setPracticeRev((v) => v + 1);
    window.addEventListener(XP_CHANGED, bump);
    window.addEventListener("storage", bump);
    return () => {
      window.removeEventListener(XP_CHANGED, bump);
      window.removeEventListener("storage", bump);
    };
  }, []);

  useEffect(() => {
    setOpen(false);
    setPinned(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) {
        setOpen(false);
        setPinned(false);
      }
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setPinned(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const xp: XpSummary | null = server
    ? computeXp(server.theory, server.streak, practiceCounts(userId))
    : null;
  void practiceRev;

  // 등급이 올라가면 배지가 한 번 통통 튀어요 (마지막으로 본 등급을 이 브라우저에 기억)
  useEffect(() => {
    if (!xp) return;
    const key = `lerny-xp-seen-grade:${userId}`;
    const now = GRADES.indexOf(xp.grade);
    try {
      const seen = localStorage.getItem(key);
      const before = seen == null ? now : GRADES.findIndex((g) => g.label === seen);
      if (before >= 0 && now > before) setLevelUp(true);
      localStorage.setItem(key, xp.grade.label);
    } catch {
      /* 저장이 막힌 브라우저 */
    }
  }, [xp?.grade.label, userId]);

  if (!xp)
    return (
      <div className="xp-badge" aria-hidden="true">
        <span className="xp-badge-trigger is-loading" />
      </div>
    );

  const remaining = xp.next ? xp.next.min - xp.total : 0;
  return (
    <div
      className="xp-badge"
      ref={box}
      data-open={open}
      data-levelup={levelUp}
      data-tier={tierOf(xp.grade.label)}
      onPointerEnter={(e) => e.pointerType === "mouse" && hoverOpen()}
      onPointerLeave={(e) => e.pointerType === "mouse" && hoverClose()}
    >
      <button
        ref={trigger}
        type="button"
        className="xp-badge-trigger"
        data-keep-menu
        aria-expanded={open}
        aria-controls="xp-badge-panel"
        aria-label={`내 학습 등급 ${xp.grade.label}, ${xp.total} XP`}
        title={`${xp.grade.label} · ${xp.total.toLocaleString()} XP`}
        onClick={() => {
          // 마우스로 이미 열린 판을 누르면 고정, 고정된 판을 다시 누르면 닫혀요
          if (open && !pinned) setPinned(true);
          else {
            setOpen(!open);
            setPinned(!open);
          }
          setLevelUp(false);
        }}
        onAnimationEnd={() => setLevelUp(false)}
      >
        <span className="xp-badge-jelly"><img src={xp.grade.image} alt="" width={42} height={42} /></span>
      </button>

      <div id="xp-badge-panel" className="xp-badge-panel" role="dialog" aria-label="내 학습 등급">
        <div className="xp-badge-head">
          <span className="xp-badge-jelly is-big"><img src={xp.grade.image} alt="" width={76} height={76} /></span>
          <div>
            <span className="xp-badge-kicker">내 학습 등급</span>
            <strong>
              {xp.grade.label} <small>{xp.total.toLocaleString()} XP</small>
            </strong>
            <p>{xp.grade.title}</p>
            {failed && <p className="xp-badge-note">학습 기록을 불러오지 못해 실습 기록만 반영했어요.</p>}
          </div>
        </div>

        <div className="xp-badge-progress">
          <div className="xp-badge-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(xp.progress * 100)}>
            <i style={{ width: `${Math.round(xp.progress * 100)}%` }} />
          </div>
          <span>{xp.next ? `${xp.next.label}까지 ${remaining.toLocaleString()} XP 남았어요` : "가장 높은 등급이에요. 지금처럼만!"}</span>
        </div>

        {/* 등급별 필요 XP — 지금 등급은 강조, 아직 못 간 등급은 흐리게 */}
        <span className="xp-badge-ladder-title">등급별 필요 XP</span>
        <ol className="xp-badge-ladder" aria-label="등급별 필요 XP">
          {[...GRADES].reverse().map((g) => (
            <li key={g.label} data-state={g === xp.grade ? "now" : g.min <= xp.total ? "done" : "next"}>
              <img src={g.image} alt="" width={30} height={30} />
              <b>{g.label}</b>
              <span>{g.min.toLocaleString()}</span>
            </li>
          ))}
        </ol>

        <ul className="xp-badge-parts">
          {xp.parts.map((p) => (
            <li key={p.key}>
              <div>
                <b>{p.label}</b>
                <span>{p.detail}</span>
              </div>
              <em>+{p.xp.toLocaleString()}</em>
            </li>
          ))}
        </ul>

        <details className="xp-badge-rules" open={rulesOpen} onToggle={(e) => setRulesOpen(e.currentTarget.open)}>
          <summary>XP 받는 방법</summary>
          <ul>
            <li>오늘의 이론 퀴즈를 모두 제출 +{XP_RULES.theoryDaily}</li>
            <li>실습 문제 최종 제출 +{XP_RULES.practiceSubmit}</li>
            <li>학습한 날마다 +{XP_RULES.studyDay}</li>
            <li>연속으로 학습하면 보너스 ({XP_RULES.streakMilestones.map((m) => `${m.days}일 +${m.xp}`).join(", ")})</li>
            <li>꾸준히 참여할수록 등급이 올라가요</li>
          </ul>
        </details>
      </div>
    </div>
  );
}
