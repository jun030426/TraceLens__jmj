import { Link, useNavigate } from "react-router-dom";
import "./landing/lerny-landing.css";
import "./landing/lerny-landing-new.css";
import "./landing/lerny-landing-lilac.css"; // 랜딩 전체 색: 바이올렛 블러시 (이 줄을 지우면 예전 색으로 돌아가요)
import "./landing/lerny-landing-fit.css"; // 11/25: 화면 크기별 맞춤 (첫 화면 글자 가독성 · 하루의 학습 가운데 정렬 · 휴대폰 배치)
import LandingNew from "./landing/LandingNew";
import ScrollDots from "./landing/ScrollDots";
import { BackgroundGradientAnimation } from "./landing/BackgroundGradientAnimation";
import { IconArrowRight } from "@tabler/icons-react";

// 하단 움직이는 그라데이션 색 — 랜딩의 라일락 바탕 위에 보라 · 블러시 덩어리 (원본: 진한 보라 → 남색 바탕에 파랑 · 분홍 · 하늘 · 빨강 · 노랑)
const GRAD = {
  gradientBackgroundStart: "#f7f0f8",
  gradientBackgroundEnd: "#ebdffa",
  // 11/18: 덩어리 색을 더 옅은 라일락 · 복숭아빛으로 (큰 Lerny 글씨가 잘 보이게)
  firstColor: "226, 214, 255",
  secondColor: "205, 186, 255",
  thirdColor: "248, 222, 232",
  fourthColor: "240, 215, 210",
  fifthColor: "232, 222, 255",
  pointerColor: "169, 129, 255",
};

/* 첫 랜딩 페이지. 위쪽은 따뜻한 종이 위의 소개(landing/LandingNew.tsx)이고, 마무리 문장은 보라 · 블러시 색이 천천히 움직이는 바탕 위에 놓여요.
   맨 아래는 띠: 저작권 줄 · 가는 선 아래로 화면 너비를 꽉 채운 연보라 큰 Lerny.가 깔리고, 글자 아래쪽은 띠 바닥에서 잘려요. */
export function Landing() {
  const navigate = useNavigate();
  return (
    <div className="study-landing lerny-landing">
      <ScrollDots />
      <LandingNew onStart={() => navigate("/home")} onProfessorStart={() => navigate("/login")} />
      {/* 마무리 ~ 맨 아래 띠: 천천히 움직이는 그라데이션 배경 (landing/BackgroundGradientAnimation.tsx) — 물결 배경은 landing/WavyBackground.tsx 에 남아 있어요 */}
      <BackgroundGradientAnimation containerClassName="ln-page" className="ln-grad-content" {...GRAD}>
        <section className="ln-finale ln-closing">
          <div className="ln-closing-head">
            <h2>
              오늘의 물음표가,
              <br />
              <span>내일의 이해가 되도록.</span>
            </h2>
            <Link to="/home" className="ln-cta">
              Lerny에서 시작하기 <span><IconArrowRight size={18} stroke={2} aria-hidden="true" /></span>
            </Link>
          </div>
        </section>
        <section className="ln-band" aria-label="Lerny 바로가기">
          <div className="ln-band-bar">
            <span>모든 콘텐츠 © Lerny 2026 · 알고보자</span>
            <span>교수님의 자료로부터, 나의 이해까지.</span>
          </div>
          {/* 화면 너비를 꽉 채운 큰 Lerny — 글자 아래쪽은 띠 바닥에서 잘려요 (SVG textLength 로 어떤 너비에서도 양끝에 맞춰요) */}
          <div className="ln-band-word" aria-hidden="true">
            <svg viewBox="0 0 1000 266" preserveAspectRatio="xMidYMin meet">
              <defs>
                <linearGradient id="ln-band-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#b9a5ef" />
                  <stop offset="85%" stopColor="#e6dffa" />
                </linearGradient>
              </defs>
              <text x="0" y="330" textLength="1000" lengthAdjust="spacingAndGlyphs" fill="url(#ln-band-grad)">
                Lerny.
              </text>
            </svg>
          </div>
        </section>
      </BackgroundGradientAnimation>
    </div>
  );
}
