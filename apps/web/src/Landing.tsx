import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import "./landing.css";
const chapters = [
  {
    label: "SOURCE",
    title: "모든 이해의 시작은,\n교수님의 수업에서.",
    text: "흩어진 검색 결과 대신, 우리 수업의 강의 자료에서 시작하세요. 배운 맥락 안에서 질문하고 답변의 근거를 확인합니다.",
    tag: "강의 자료",
    body: "자료구조 · 연결 리스트",
    detail: "강의 자료를 읽고, 궁금했던 개념을 발견하세요.",
  },
  {
    label: "QUESTION",
    title: "지나쳤던 물음표를,\n이해의 연결점으로.",
    text: "이 부분은 왜 그럴까? 작은 질문도 괜찮아요. AI와 대화하며 개념을 풀어보고, 답변이 시작된 자료까지 돌아가 보세요.",
    tag: "AI 질문",
    body: "배열과 연결 리스트는 어떻게 다를까?",
    detail: "자료의 근거와 함께, 개념 사이의 차이를 확인해요.",
  },
  {
    label: "UNDERSTAND",
    title: "아는 것 같은 순간에서,\n설명할 수 있는 순간으로.",
    text: "오늘의 퀴즈로 이해를 확인하세요. 결과와 해설을 살펴보고, 헷갈렸던 개념을 다시 만나며 나의 배움으로 만들어갑니다.",
    tag: "퀴즈와 복습",
    body: "한 번 더 생각하고, 한 걸음 더 앞으로.",
    detail: "퀴즈 → 결과 확인 → 개념 복습. 배움이 이어집니다.",
  },
];
export function Landing() {
  const story = useRef<HTMLDivElement>(null);
  const [chapter, setChapter] = useState(0);
  const scene = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting)
            setChapter(Number((entry.target as HTMLElement).dataset.chapter));
      },
      { rootMargin: "-30% 0px -30% 0px" },
    );
    story.current
      ?.querySelectorAll(".ln-chapter")
      .forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!scene.current) return;
        const progress = Math.min(
          1,
          Math.max(0, window.scrollY / (window.innerHeight * 0.9)),
        );
        scene.current.style.setProperty("--journey", String(progress));
      });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => {
      window.removeEventListener("scroll", update);
      cancelAnimationFrame(frame);
    };
  }, []);
  const current = chapters[chapter];
  return (
    <div className="ln-page" ref={scene}>
      <section className="ln-hero">
        <div className="ln-grid" aria-hidden="true" />
        <div className="ln-hero-top">
          <span>
            <i /> A NEW WAY TO UNDERSTAND
          </span>
          <span>YOUR CLASS. YOUR CLARITY.</span>
        </div>
        <div className="ln-hero-copy">
          <p className="ln-kicker">수업과 이해 사이, Lerny</p>
          <h1>
            흩어진 배움이,
            <br />
            <span>하나의 이해로.</span>
          </h1>
          <p className="ln-description">
            수업에서 놓친 연결고리, 여기서 찾으세요.
            <br />
            교수님의 자료로 질문하고, 퀴즈로 나의 이해를 완성해요.
          </p>
          <div className="ln-hero-actions">
            <Link to="/home" className="ln-cta">
              내 강의실로 가기 <span>↗</span>
            </Link>
            <a href="#learning-story" className="ln-text-link">
              Lerny 알아보기 ↓
            </a>
          </div>
        </div>
        <div className="ln-universe" aria-hidden="true">
          <div className="ln-paper">
            <div className="ln-paper-top">
              <span>LERNY / CLASS NOTES</span>
              <span>03</span>
            </div>
            <span className="ln-paper-course">자료구조</span>
            <h3>연결 리스트</h3>
            <div className="ln-paper-rule" />
            <p>
              데이터는 흩어져 있어도,
              <br />
              <mark>연결되면 하나의 흐름이 된다.</mark>
            </p>
            <div className="ln-paper-chain">
              <span>A</span>
              <i>→</i>
              <span>B</span>
              <i>→</i>
              <span>C</span>
            </div>
            <span className="ln-paper-foot">강의 자료 예시 · 개념의 연결</span>
          </div>
          <div className="ln-fragment ln-fragment-one" />
          <div className="ln-fragment ln-fragment-two" />
          <div className="ln-orbit ln-orbit-one" />
          <div className="ln-orbit ln-orbit-two" />
          <div className="ln-orbit ln-orbit-three" />
          <svg className="ln-connections" viewBox="0 0 600 600">
            <path d="M110 170 Q320 80 320 300 T510 435 M120 440 Q140 300 320 300 T470 130" />
          </svg>
          <div className="ln-core">
            <div className="ln-core-inner">
              <span>l</span>
              <span className="ln-core-dot" />
            </div>
          </div>
          <div className="ln-satellite ln-source">
            <b>▤</b>
            <div>
              <small>THE STARTING POINT</small>
              <strong>한 문장에서 출발해</strong>
              <span>강의 자료 속 개념 발견</span>
            </div>
          </div>
          <div className="ln-satellite ln-question">
            <b>?</b>
            <div>
              <small>MAKE A CONNECTION</small>
              <strong>“연결은 어떻게 될까?”</strong>
              <span>근거를 따라가는 질문</span>
            </div>
          </div>
          <div className="ln-satellite ln-understand">
            <b>✓</b>
            <div>
              <small>MAKE IT YOURS</small>
              <strong>이제 설명할 수 있어요.</strong>
              <span>확인하고, 나의 것으로</span>
            </div>
          </div>
          <span className="ln-star ln-star-one">✦</span>
          <span className="ln-star ln-star-two">✦</span>
        </div>
        <div className="ln-hero-bottom">
          <span>FROM INFORMATION TO UNDERSTANDING</span>
          <a href="#learning-story">SCROLL TO CONNECT ↓</a>
          <span>01 — 03</span>
        </div>
      </section>
      <div className="ln-manifesto">
        <span>LESS GUESSING.</span>
        <p>
          그냥 외우는 공부를 넘어,
          <br />
          <strong>이유를 이해하는 배움으로.</strong>
        </p>
        <span>MORE UNDERSTANDING.</span>
      </div>
      <div className="ln-story" id="learning-story" ref={story}>
        <div>
          {chapters.map((item, index) => (
            <section
              className={`ln-chapter ${chapter === index ? "is-active" : ""}`}
              data-chapter={index}
              key={item.label}
            >
              <span className="ln-kicker">
                0{index + 1} / {item.label}
              </span>
              <h2>{item.title}</h2>
              <p>{item.text}</p>
              <div className="ln-chapter-line">
                <span>0{index + 1}</span>
                <i />
                <span>03</span>
              </div>
            </section>
          ))}
        </div>
        <div className="ln-stage">
          <div className={`ln-demo ln-demo-${chapter}`}>
            <div className="ln-demo-bar">
              <span>● LERNY / LEARNING SPACE</span>
              <span>예시 화면</span>
            </div>
            <div className="ln-demo-content" key={chapter}>
              <span className="ln-demo-tag">{current.tag}</span>
              <h3>
                {current.label.toLowerCase()}
                <span>.</span>
              </h3>
              <div
                className={`ln-concept-map ln-map-${chapter}`}
                aria-hidden="true"
              >
                <div className="ln-map-topic">연결 리스트</div>
                <div className="ln-map-stem" />
                <div className="ln-map-branches">
                  <span>데이터</span>
                  <span>연결</span>
                  <span>순서</span>
                </div>
                <div className="ln-map-insight">
                  {chapter === 0
                    ? "수업에서 만난 개념의 조각들"
                    : chapter === 1
                      ? "연속하지 않아도, 어떻게 이어질까?"
                      : "각 노드는 다음 노드의 위치를 기억해요."}
                </div>
              </div>
              <div className="ln-demo-art" aria-hidden="true">
                <span>자료</span>
                <i />
                <b>
                  {chapter === 0 ? "개념" : chapter === 1 ? "질문" : "이해"}
                </b>
                <i />
                <span>{chapter === 2 ? "복습" : "연결"}</span>
              </div>
              <div className="ln-demo-answer">
                <small>0{chapter + 1}</small>
                <div>
                  <strong>{current.body}</strong>
                  <p>{current.detail}</p>
                </div>
              </div>
              <div className="ln-demo-progress">
                {chapters.map((_, i) => (
                  <span key={i} className={i <= chapter ? "filled" : ""} />
                ))}
              </div>
              <p className="ln-demo-caption">
                학습 흐름을 소개하는 예시입니다.
              </p>
            </div>
          </div>
          <span className="ln-stage-caption">ONE CLASS. MANY CONNECTIONS.</span>
        </div>
      </div>
      <section className="ln-learning-experiences" aria-labelledby="learning-experiences-title">
        <span className="ln-kicker">SEE IT. UNDERSTAND IT. BUILD IT.</span>
        <h2 id="learning-experiences-title">보고 이해하고,<br />직접 연결하는 배움.</h2>
        <div className="ln-experience-grid">
          <article><span className="ln-experience-number">01 / AI CLASS</span><h3>개념 하나, 짧은 강의 하나.</h3><p>AI 강사가 칠판의 도표와 예시로 수업의 핵심을 설명하는 개념별 강의를 준비하고 있어요.</p><small>영상 콘텐츠 준비 중</small></article>
          <article><span className="ln-experience-number">02 / CODE &amp; VISUAL</span><h3>내 코드가 움직이는 순간.</h3><p>핵심 로직을 직접 작성하고, 실행 흐름을 시각화로 확인하는 실습을 준비하고 있어요.</p><small>격리 실행·시각화 연결 예정</small></article>
        </div>
      </section>
      <section className="ln-destinations">
        <div className="ln-section-heading">
          <span className="ln-kicker">FIND YOUR NEXT STEP</span>
          <h2>이제, 어디서 시작할까요?</h2>
          <p>오늘의 배움으로 이어지는 가장 짧은 길.</p>
        </div>
        <div className="ln-destination-grid">
          {[
            [
              "/home",
              "START",
              "오늘의 학습",
              "내 홈에서 오늘 이어갈 학습을 확인하세요.",
            ],
            [
              "/courses",
              "EXPLORE",
              "내 강의",
              "수강 중인 강의에서 자료와 학습을 만나세요.",
            ],
            [
              "/login",
              "CONNECT",
              "로그인",
              "내 계정으로 들어가 배움을 이어가세요.",
            ],
          ].map(([url, label, title, text], i) => (
            <Link to={url} key={url}>
              <span className="ln-destination-number">
                0{i + 1} / {label}
              </span>
              <h3>
                {title}
                <span>↗</span>
              </h3>
              <p>{text}</p>
            </Link>
          ))}
        </div>
      </section>
      <section className="ln-finale">
        <span className="ln-kicker">CONNECT THE DOTS. MAKE IT YOURS.</span>
        <h2>
          오늘의 물음표가,
          <br />
          <span>내일의 이해가 되도록.</span>
        </h2>
        <Link to="/home" className="ln-cta">
          Lerny에서 시작하기 <span>↗</span>
        </Link>
        <div className="ln-finale-word" aria-hidden="true">
          Lerny
        </div>
      </section>
    </div>
  );
}

