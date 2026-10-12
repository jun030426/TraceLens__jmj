import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, post, setCsrf, type User } from "./api";
import { Form, Input, Notice, field } from "./components";
export const Auth = createContext<{
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
}>({ user: null, loading: true, refresh: async () => {} });
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
  const refresh = async () => {
    try {
      const u = await api<User>("/me");
      const c = await api<{ csrf_token: string }>("/auth/csrf");
      setCsrf(c.csrf_token);
      setUser(u);
    } catch {
      setUser(null);
      setCsrf("");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  return (
    <Auth.Provider value={{ user, loading, refresh }}>{children}</Auth.Provider>
  );
}
export function Guard({
  children,
  allowChange = false,
}: {
  children: ReactNode;
  allowChange?: boolean;
}) {
  const { user, loading } = useContext(Auth);
  if (loading) return <Notice>로그인 확인 중…</Notice>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password && !allowChange)
    return <Navigate to="/change-password" replace />;
  return children;
}
export function Login() {
  const [showPassword, setShowPassword] = useState(false);
  const { refresh, user } = useContext(Auth);
  if (user)
    return (
      <Navigate
        to={user.must_change_password ? "/change-password" : "/home"}
        replace
      />
    );
  return (
    <div className="login-layout">
      <aside className="login-story">
        <Link to="/" className="login-back">
          ← Lerny 알아보기
        </Link>
        <div className="login-story-copy">
          <span className="login-kicker">PICK UP WHERE YOU LEFT OFF</span>
          <h1>
            다시 연결되는
            <br />
            <span>나의 배움.</span>
          </h1>
          <p>
            어제의 질문에서 오늘의 이해까지.
            <br />
            나만의 강의실에서 이어가세요.
          </p>
        </div>
        <div className="login-art" aria-hidden="true">
          <div className="login-art-orbit" />
          <div className="login-note">
            <span>MY LEARNING SPACE</span>
            <strong>오늘도, 한 걸음.</strong>
            <div className="login-note-line" />
            <div className="login-note-line short" />
            <div className="login-note-nodes">
              <i>자료</i>
              <b>→</b>
              <i>질문</i>
              <b>→</b>
              <i>이해</i>
            </div>
          </div>
          <div className="login-art-mark">
            l<span>.</span>
          </div>
          <span className="login-art-star">✦</span>
        </div>
        <span className="login-story-foot">YOUR CLASS. YOUR CLARITY.</span>
      </aside>
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-form-wrap">
          <span className="login-kicker">WELCOME BACK</span>
          <h2 id="login-title">다시 만나 반가워요</h2>
          <p className="login-intro">로그인하고 배움을 이어가세요.</p>
          <Form
            label="로그인 →"
            onSubmit={async (f) => {
              const r = await api<{ csrf_token: string }>(
                "/auth/login",
                post({
                  login_id: field(f, "login_id"),
                  password: field(f, "password"),
                }),
              );
              setCsrf(r.csrf_token);
              await refresh();
            }}
          >
            <label>
              아이디
              <input
                name="login_id"
                autoComplete="username"
                placeholder="아이디를 입력해 주세요"
                maxLength={100}
                required
                autoCapitalize="none"
                spellCheck={false}
              />
            </label>
            <label htmlFor="login-password">비밀번호</label>
            <div className="login-password">
              <input
                id="login-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="비밀번호를 입력해 주세요"
                maxLength={128}
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
                aria-pressed={showPassword}
              >
                {showPassword ? "숨기기" : "보기"}
              </button>
            </div>
            <Link className="login-reset" to="/reset">
              비밀번호를 잊으셨나요?
            </Link>
          </Form>
          <div className="login-signup">
            <span>아직 Lerny 계정이 없나요?</span>
            <Link to="/signup">학생 회원가입 ↗</Link>
          </div>
          <p className="login-teacher-note">
            교수님은 발급받은 계정으로 로그인해 주세요.
          </p>
        </div>
      </section>
    </div>
  );
}
export function Signup() {
  const navigate = useNavigate();
  const [showPassword, setShowPassword] = useState(false);
  return (
    <div className="login-layout signup-layout">
      <aside className="login-story signup-story">
        <Link to="/login" className="login-back">
          ← 로그인으로 돌아가기
        </Link>
        <div className="login-story-copy">
          <span className="login-kicker">YOUR FIRST CONNECTION</span>
          <h1>
            나의 이해가
            <br />
            <span>시작되는 곳.</span>
          </h1>
          <p>
            수업 속 궁금증을 질문으로,
            <br />
            배운 내용을 나만의 이해로 연결하세요.
          </p>
        </div>
        <div className="signup-path" aria-label="가입 후 학습 흐름">
          <div>
            <span>01</span>
            <p>
              <strong>나만의 계정 만들기</strong>
              <small>학습을 이어갈 첫 번째 준비</small>
            </p>
          </div>
          <div>
            <span>02</span>
            <p>
              <strong>수강 코드로 강의 신청</strong>
              <small>참여할 수업과 연결되기</small>
            </p>
          </div>
          <div>
            <span>03</span>
            <p>
              <strong>질문하고, 확인하고, 복습하기</strong>
              <small>우리 수업의 자료로 시작하는 배움</small>
            </p>
          </div>
        </div>
        <span className="login-story-foot">
          EVERY CONNECTION STARTS SOMEWHERE.
        </span>
      </aside>
      <section
        className="login-panel signup-panel"
        aria-labelledby="signup-title"
      >
        <div className="login-form-wrap">
          <span className="login-kicker">JOIN LERNY</span>
          <h2 id="signup-title">학생 회원가입</h2>
          <p className="login-intro">
            배움의 첫걸음을 함께. 내 강의를 만나보세요.
          </p>
          <Form
            label="학생 계정 만들기 →"
            onSubmit={async (f) => {
              await api(
                "/auth/signup",
                post({
                  login_id: field(f, "login_id"),
                  display_name: field(f, "name"),
                  major: field(f, "major"),
                  student_number: field(f, "student_number"),
                  email: field(f, "email"),
                  password: field(f, "password"),
                  privacy_notice_version: "2026-10-12",
                }),
              );
              navigate("/login");
            }}
          >
            <label>
              아이디
              <input
                name="login_id"
                placeholder="영문·숫자 3자 이상"
                minLength={3}
                maxLength={100}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
              />
            </label>
            <label>
              이름
              <input
                name="name"
                placeholder="이름을 입력해 주세요"
                maxLength={100}
                autoComplete="name"
                required
              />
            </label>
            <label>이메일<input name="email" type="email" autoComplete="email" maxLength={254} placeholder="name@example.com" required /></label>
            <div className="signup-academic-fields">
              <label>전공<input name="major" placeholder="예: 컴퓨터공학과" maxLength={100} required /></label>
              <label>학번<input name="student_number" placeholder="학번을 입력해 주세요" maxLength={40} autoCapitalize="none" spellCheck={false} required /></label>
            </div>
            <p className="signup-photo-note">프로필 사진은 가입 후 내 정보에서 등록할 수 있어요.</p>
            <label htmlFor="signup-password">비밀번호</label>
            <div className="login-password">
              <input
                id="signup-password"
                name="password"
                type={showPassword ? "text" : "password"}
                placeholder="12자 이상 입력해 주세요"
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
                aria-pressed={showPassword}
              >
                {showPassword ? "숨기기" : "보기"}
              </button>
            </div>
            <div className="signup-privacy">
              <span className="signup-privacy-title">
                가입 전, 학습 기록 안내
              </span>
              <ul>
                <li>
                  교수님은 답안·코드·취약점과 질문 개념·횟수를 볼 수 있어요.
                </li>
                <li>전공·학번은 계정 프로필에 저장됩니다.</li>
                <li>개인 대화 전체는 이름과 연결해 공개하지 않아요.</li>
                <li>
                  학기 종료 후에도 학습 기록을 열람할 수 있어요. 질문 원문은 90일 보존합니다.
                </li>
              </ul>
            </div>
            <label className="signup-consent">
              <input type="checkbox" required />{" "}
              <span>학습 기록 열람·보존 안내를 확인했습니다.</span>
            </label>
          </Form>
          <div className="login-signup">
            <span>이미 계정이 있나요?</span>
            <Link to="/login">로그인 ↗</Link>
          </div>
          <p className="login-teacher-note">
            교수 계정은 운영 담당자가 발급합니다.
          </p>
        </div>
      </section>
    </div>
  );
}
export function Reset() {
  const [done, setDone] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  return (
    <div className="login-layout reset-layout">
      <aside className="login-story reset-story">
        <Link to="/login" className="login-back">
          ← 로그인으로 돌아가기
        </Link>
        <div className="login-story-copy">
          <span className="login-kicker">FIND YOUR WAY BACK</span>
          <h1>
            잠시 멈춘 배움을,
            <br />
            <span>다시 이어가세요.</span>
          </h1>
          <p>
            새 비밀번호로 계정에 돌아와
            <br />
            나의 학습을 이어갈 수 있어요.
          </p>
        </div>
        <div className="reset-illustration" aria-hidden="true">
          <div className="reset-orbit" />
          <div className="reset-lock">
            <span className="reset-lock-loop" />
            <div className="reset-lock-body">
              <i />
            </div>
          </div>
          <span className="reset-spark">✦</span>
          <span className="reset-illustration-label">
            BACK TO YOUR LEARNING SPACE
          </span>
        </div>
        <span className="login-story-foot">YOUR NEXT CHAPTER IS WAITING.</span>
      </aside>
      <section
        className="login-panel reset-panel"
        aria-labelledby="reset-title"
      >
        <div className="login-form-wrap">
          <span className="login-kicker">ACCOUNT RECOVERY</span>
          <h2 id="reset-title">
            {done ? "비밀번호를 변경했어요" : "비밀번호 초기화"}
          </h2>
          {done ? (
            <div className="reset-success" role="status">
              <span className="reset-success-icon" aria-hidden="true">
                ✓
              </span>
              <p>
                새 비밀번호로 로그인하고
                <br />
                배움을 이어가세요.
              </p>
              <Link className="ln-cta" to="/login">
                로그인으로 이동 <span>↗</span>
              </Link>
            </div>
          ) : (
            <>
              <p className="login-intro">
                운영 담당자에게 받은 코드로
                <br />새 비밀번호를 설정해 주세요.
              </p>
              <div className="reset-help">
                <strong>아직 코드를 받지 못했나요?</strong>
                <p>
                  운영 담당자에게 비밀번호 초기화를 요청해 주세요. 받은 코드를
                  아래에 입력하면 됩니다.
                </p>
              </div>
              <Form
                label="새 비밀번호 설정 →"
                onSubmit={async (f) => {
                  await api(
                    "/auth/reset-password",
                    post({
                      one_time_token: field(f, "token"),
                      new_password: field(f, "password"),
                    }),
                  );
                  setDone(true);
                }}
              >
                <label>
                  비밀번호 재설정 코드
                  <input
                    name="token"
                    placeholder="운영 담당자에게 받은 코드"
                    maxLength={200}
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                  />
                </label>
                <label htmlFor="reset-password">새 비밀번호</label>
                <div className="login-password">
                  <input
                    id="reset-password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="12자 이상 입력해 주세요"
                    minLength={12}
                    maxLength={128}
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    aria-label={
                      showPassword ? "비밀번호 숨기기" : "비밀번호 보기"
                    }
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? "숨기기" : "보기"}
                  </button>
                </div>
              </Form>
              <div className="login-signup">
                <span>비밀번호가 기억났나요?</span>
                <Link to="/login">로그인 ↗</Link>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
export function ChangePassword() {
  const { refresh } = useContext(Auth);
  const navigate = useNavigate();
  const [visible, setVisible] = useState({ old: false, new: false });
  return (
    <div className="login-layout change-layout">
      <aside className="login-story change-story">
        <span className="login-kicker">YOUR ACCOUNT. YOUR SPACE.</span>
        <div className="login-story-copy">
          <h1>
            나만의 배움,
            <br />
            <span>나만의 비밀번호로.</span>
          </h1>
          <p>
            계정을 안전하게 준비하고
            <br />
            Lerny에서 첫 수업을 시작하세요.
          </p>
        </div>
        <div className="reset-illustration" aria-hidden="true">
          <div className="reset-orbit" />
          <div className="reset-lock">
            <span className="reset-lock-loop" />
            <div className="reset-lock-body">
              <i />
            </div>
          </div>
          <span className="reset-spark">✦</span>
          <span className="reset-illustration-label">
            MAKE THIS SPACE YOURS
          </span>
        </div>
        <span className="login-story-foot">
          A SMALL STEP BEFORE YOUR FIRST CLASS.
        </span>
      </aside>
      <section
        className="login-panel change-panel"
        aria-labelledby="change-title"
      >
        <div className="login-form-wrap">
          <span className="login-kicker">ACCOUNT SETUP</span>
          <h2 id="change-title">초기 비밀번호 변경</h2>
          <p className="login-intro">
            발급받은 비밀번호를
            <br />
            직접 사용할 새 비밀번호로 바꿔 주세요.
          </p>
          <div className="reset-help">
            <strong>처음 사용하기 전에 준비해 주세요</strong>
            <p>
              현재 비밀번호에는 발급받은 비밀번호를 입력하세요. 변경을 마치면 새
              비밀번호로 다시 로그인합니다.
            </p>
          </div>
          <Form
            label="비밀번호 변경하고 다시 로그인 →"
            onSubmit={async (f) => {
              await api(
                "/auth/change-password",
                post({
                  current_password: field(f, "old"),
                  new_password: field(f, "new"),
                }),
              );
              await refresh();
              navigate("/login");
            }}
          >
            {(
              [
                {
                  key: "old",
                  label: "현재 비밀번호",
                  placeholder: "발급받은 비밀번호",
                  complete: "current-password",
                },
                {
                  key: "new",
                  label: "새 비밀번호",
                  placeholder: "12자 이상 입력해 주세요",
                  complete: "new-password",
                },
              ] as const
            ).map((item) => (
              <div className="change-field" key={item.key}>
                <label htmlFor={`change-${item.key}`}>{item.label}</label>
                <div className="login-password">
                  <input
                    id={`change-${item.key}`}
                    name={item.key}
                    type={visible[item.key] ? "text" : "password"}
                    placeholder={item.placeholder}
                    autoComplete={item.complete}
                    minLength={item.key === "new" ? 12 : undefined}
                    maxLength={item.key === "new" ? 128 : 200}
                    required
                  />
                  <button
                    type="button"
                    aria-label={`${item.label} ${visible[item.key] ? "숨기기" : "보기"}`}
                    aria-pressed={visible[item.key]}
                    onClick={() =>
                      setVisible((v) => ({ ...v, [item.key]: !v[item.key] }))
                    }
                  >
                    {visible[item.key] ? "숨기기" : "보기"}
                  </button>
                </div>
              </div>
            ))}
          </Form>
          <p className="change-footnote">
            변경 후에는 새 비밀번호로 로그인해 주세요.
          </p>
        </div>
      </section>
    </div>
  );
}
