import { XpBadge } from "./XpBadge";
import { Fragment, lazy, Suspense, useContext, useEffect, useRef, useState } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import {
  Auth,
  AuthProvider,
  Guard,
  Login,
  Signup,
  Reset,
  ChangePassword,
} from "./Auth";
import { Dashboard, TeacherCourse, StudentClass } from "./Courses";
import {
  StudentOnly,
  RoleHome,
  QuizCatalog,
  QuizTakeFlow,
  QuizResults,
  CourseWorkspace,
  Profile,
  ProfessorWorkspace,
} from "./Flow";
import { api, post, type Classroom } from "./api";
import { QuizArchive } from "./QuizArchive";
import { PracticeWorkspace, PracticeResults } from "./Practice";
import { StudentExamPrep } from "./ExamPrep";
import { InstructorClass } from "./Instructor";
import { StudentToday } from "./StudentToday";
import { isTestUser, setTestRole } from "./testAccess";
import { UserMenu } from "./UserMenu";
import { ChatFab } from "./ChatFab";
import { applyTheme, setTheme, useTheme } from "./theme";
import { AdminPage } from "./AdminRoute";
import { MaterialViewer } from "./MaterialViewer";
import { ServiceBanner } from "./ServiceBanner";
import { ServiceStatusProvider } from "./ServiceStatus";

const Landing = lazy(() => import("./Landing").then(({ Landing }) => ({ default: Landing })));

function useClassroomContext(userId?: string) {
  const location = useLocation();
  const routeKey = location.pathname + location.search;
  const [context, setContext] = useState<{ key: string; room: Classroom; userId: string }>();
  useEffect(() => {
    if (!userId) return;
    let active = true;
    const path = location.pathname;
    const resultId = path.match(/^\/quiz\/results\/([^/]+)$/)?.[1];
    const sectionId =
      path.match(/^\/quiz\/([^/]+)\/archive(?:\/|$)/)?.[1] ||
      path.match(/^\/(?:classrooms|quiz)\/([^/]+)$/)?.[1] ||
      path.match(/^\/classrooms\/([^/]+)\/(?:practice(?:\/results)?|lectures)$/)?.[1] ||
      (["/ai", "/quiz", "/attendance"].includes(path)
        ? new URLSearchParams(location.search).get("section")
        : null);
    if (!sectionId && !resultId) return;
    async function resolve() {
      try {
        const id = resultId
          ? (
              await api<{ section_id: string }>(
                `/learning-sessions/${resultId}`,
              )
            ).section_id
          : sectionId;
        const rooms = await api<{ items: Classroom[] }>("/classrooms");
        const room = rooms.items.find(
          (r) => r.status === "active" && r.section.id === id,
        );
        if (active && room) setContext({ key: routeKey, room, userId: userId! });
      } catch {
        /* The page itself displays loading and access errors. */
      }
    }
    void resolve();
    return () => {
      active = false;
    };
  }, [routeKey, location.pathname, location.search, userId]);
  return userId && context?.userId === userId && context.key === routeKey ? context.room : undefined;
}

function Shell() {
  const { user, loading, refresh } = useContext(Auth);
  const location = useLocation();
  const pathname = location.pathname;
  const menuKey = `${user?.id || "guest"}:${pathname}${location.search}`;
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuOpen = openMenu === menuKey;
  const menuButton = useRef<HTMLButtonElement>(null);
  const headerRef = useRef<HTMLElement>(null);
  useEffect(() => setOpenMenu(null), [menuKey]);
  useEffect(() => {
    if (!menuOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) setOpenMenu(null);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [menuOpen]);
  const classroom = useClassroomContext(
    user?.role === "student" ? user.id : undefined,
  );
  const isLanding = pathname === "/";
  const [theme] = useTheme();
  // 로그인하지 않은 화면(로그아웃 뒤, 세션 만료 포함)은 항상 기본(밝은) 모드예요
  const loggedOut = !loading && !user;
  useEffect(() => applyTheme(loggedOut ? "light" : theme, pathname), [theme, pathname, loggedOut]);
  // 학생 화면에만 버튼 색(student-buttons.css)을 입히려고 <html data-role> 에 역할을 적어 둬요
  useEffect(() => {
    if (user?.role) document.documentElement.dataset.role = user.role;
    else delete document.documentElement.dataset.role;
  }, [user?.role]);
  const isStudentHome =
    pathname === "/student" ||
    ((pathname === "/professor" || pathname === "/professor/notices" || pathname === "/professor/students" || pathname.startsWith("/professor/courses/")) && user?.role === "teacher") ||
    ((pathname === "/courses" ||
      pathname === "/ai" ||
      pathname === "/attendance" ||
      pathname === "/exam-prep" ||
      /^\/materials\/[^/]+\/view$/.test(pathname) ||
      pathname === "/mypage" ||
      /^\/classrooms\/[^/]+\/lectures$/.test(pathname) ||
      /^\/classrooms\/[^/]+\/practice(?:\/results)?$/.test(pathname) ||
      /^\/quiz\/[^/]+\/archive(?:\/|$)/.test(pathname) ||
      pathname === "/quiz" ||
      /^\/quiz\/(?:results\/)?[^/]+$/.test(pathname) ||
      /^\/classrooms\/[^/]+$/.test(pathname)) &&
      user?.role === "student");
  const isLogin = ["/login", "/signup", "/reset", "/change-password"].includes(
    pathname,
  );
  // 스크롤을 내리면 상단 바를 숨기고, 올리면 다시 보여줘요 (11-16)
  const [headerHidden, setHeaderHidden] = useState(false);
  useEffect(() => {
    let last = window.scrollY;
    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const y = window.scrollY;
        const delta = y - last;
        if (y < 80) { setHeaderHidden(false); last = y; }
        else if (delta > 6) { setHeaderHidden(true); last = y; }
        else if (delta < -6) { setHeaderHidden(false); last = y; }
        ticking = false;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => setHeaderHidden(false), [pathname]);
  return (
    <>
      <header
        ref={headerRef}
        onKeyDown={event => {
          if (event.key === "Escape" && menuOpen) {
            setOpenMenu(null);
            menuButton.current?.focus();
          }
        }}
        className={
          "app-header " + (headerHidden && !menuOpen ? "is-scroll-hidden " : "") + (classroom
            ? "ln-header lesson-header"
            : isLanding || isStudentHome
              ? "ln-header"
              : isLogin
                ? "ln-header login-header"
                : "")
        }
      >
        <Link className="brand" to={user ? "/home" : "/"}>
          <img className="app-logo" src="/lerny-logo.png" alt="Lerny" />
        </Link>
        {/* 강의실 첫 화면에서는 '내 강의로'를 강의명 위에 따로 보여줘요 (11-14) */}
        {classroom && !/^\/classrooms\/[^/]+(\/lectures)?\/?$/.test(pathname) && pathname !== "/ai" && pathname !== "/quiz" && pathname !== "/attendance" && !/^\/classrooms\/[^/]+\/practice\/?$/.test(pathname) && !/^\/quiz\/results\//.test(pathname) && !/^\/classrooms\/[^/]+\/practice\/results\/?$/.test(pathname) && (
          <Link className="lesson-exit" to="/courses">
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5m6-6-6 6 6 6" /></svg>
            <span>내 강의로</span>
          </Link>
        )}
        <button ref={menuButton} type="button" className="mobile-menu-toggle" aria-expanded={menuOpen} aria-controls="app-navigation" onClick={() => setOpenMenu(menuOpen ? null : menuKey)}>
          <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span> {menuOpen ? "메뉴 닫기" : "메뉴"}
        </button>
        <nav id="app-navigation" data-open={menuOpen} aria-label={classroom ? "강의실 학습 메뉴" : "주 메뉴"} onClick={event => { if ((event.target as Element).closest("a, button:not([data-keep-menu])")) setOpenMenu(null); }}>
          {user ? (
            <>
              {(user.role === "student"
                ? classroom
                  ? [
                      [`/classrooms/${classroom.section.id}`, "강의실"],
                      [`/classrooms/${classroom.section.id}/lectures`, "AI 강의"],
                      [`/ai?section=${classroom.section.id}`, "AI 질문"],
                      [`/quiz?section=${classroom.section.id}`, "퀴즈"],
                      [
                        `/attendance?section=${classroom.section.id}`,
                        "학습 기록",
                      ],
                    ]
                  : [
                      ["/student", "홈"],
                      ["/courses", "내 강의"],
                    ]
                : user.role === "teacher"
                  ? [
                      ["/professor", "강의 목록"],
                      ["/professor/notices", "강의 자료"],
                      ["/professor/students", "수강생"],
                    ]
                  : [["/admin", "운영 관리"]]
              ).map(([path, label]) => (
                <Fragment key={path}>
                  {classroom && label === "강의실" && (
                    <XpBadge key={`${user.id}:${classroom.section.id}`} userId={user.id} sectionId={classroom.section.id} />
                  )}
                <NavLink
                  to={path}
                  end={
                    path === "/professor" ||
                    label === "강의실" ||
                    label === "퀴즈"
                  }
                  className={
                    classroom &&
                    label === "퀴즈" &&
                    (pathname.startsWith("/quiz/") || /^\/classrooms\/[^/]+\/practice(?:\/results)?$/.test(pathname))
                      ? "active"
                      : undefined
                  }
                >
                  {label}
                </NavLink>
                </Fragment>
              ))}
              <UserMenu
                user={user}
                compact={!!classroom}
                onLogout={async () => {
                  setTheme("light"); // 로그아웃하면 다크 모드 설정을 지우고 기본으로 돌아가요
                  if (isTestUser(user)) {
                    setTestRole(null);
                    await refresh();
                    return;
                  }
                  await api("/auth/logout", post({}));
                  try {
                    for (const key of Object.keys(sessionStorage))
                      if (key.startsWith(`lerny-quiz:${user.id}:`))
                        sessionStorage.removeItem(key);
                  } catch {
                    /* Storage may be disabled. */
                  }
                  await refresh();
                }}
              />
            </>
          ) : (
            <>
              <Link to="/login">로그인</Link>
              <Link to="/signup">학생 가입</Link>
            </>
          )}
        </nav>
      </header>

      <ServiceBanner />
      <main
        className={
          isLanding
            ? "app ln-main"
            : isStudentHome
              ? "app student-main"
              : isLogin
                ? "app login-main"
                : "app"
        }
      >
        <Routes>
          <Route path="/quiz/:sectionId/archive/:week?" element={<Guard><StudentOnly><QuizArchive /></StudentOnly></Guard>} />
          <Route path="/quiz/:sectionId/archive/:week/theory" element={<Guard><StudentOnly><QuizArchive theory /></StudentOnly></Guard>} />
          <Route path="/quiz/:sectionId/archive/:week/theory/:dayIndex" element={<Guard><StudentOnly><QuizTakeFlow /></StudentOnly></Guard>} />
          <Route path="/materials/:materialId/view" element={<Guard><StudentOnly><MaterialViewer /></StudentOnly></Guard>} />
          <Route path="/classrooms/:sectionId/lectures" element={<Guard><StudentOnly><InstructorClass /></StudentOnly></Guard>} />
          <Route path="/classrooms/:sectionId/practice/results" element={<Guard><StudentOnly><PracticeResults /></StudentOnly></Guard>} />
          <Route path="/classrooms/:sectionId/practice" element={<Guard><StudentOnly><PracticeWorkspace /></StudentOnly></Guard>} />
          <Route path="/" element={<Suspense fallback={<p role="status">첫 화면을 불러오는 중이에요.</p>}><Landing /></Suspense>} />
          <Route
            path="/home"
            element={
              <Guard>
                <RoleHome />
              </Guard>
            }
          />
          <Route
            path="/student"
            element={
              <Guard>
                <StudentOnly>
                  <StudentToday />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/courses"
            element={
              <Guard>
                <StudentOnly>
                  <Dashboard />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/quiz"
            element={
              <Guard>
                <StudentOnly>
                  <QuizCatalog />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/quiz/:sectionId"
            element={
              <Guard>
                <StudentOnly>
                  <QuizTakeFlow />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/quiz/results/:learningId"
            element={
              <Guard>
                <StudentOnly>
                  <QuizResults />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/ai"
            element={
              <Guard>
                <StudentOnly>
                  <CourseWorkspace mode="chat" />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/attendance"
            element={
              <Guard>
                <StudentOnly>
                  <CourseWorkspace mode="progress" />
                </StudentOnly>
              </Guard>
            }
          />
          <Route
            path="/mypage"
            element={
              <Guard>
                <Profile />
              </Guard>
            }
          />
          <Route
            path="/professor"
            element={
              <Guard>
                <Dashboard />
              </Guard>
            }
          />
          <Route
            path="/professor/courses/:courseId"
            element={
              <Guard>
                <TeacherCourse />
              </Guard>
            }
          />
          <Route
            path="/professor/notices"
            element={
              <Guard>
                <ProfessorWorkspace mode="materials" />
              </Guard>
            }
          />
          <Route
            path="/professor/students"
            element={
              <Guard>
                <ProfessorWorkspace mode="students" />
              </Guard>
            }
          />

          <Route path="/admin" element={<Guard><AdminPage /></Guard>} />
          <Route path="/exam-prep" element={<Guard><StudentOnly><StudentExamPrep /></StudentOnly></Guard>} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/reset" element={<Reset />} />
          <Route
            path="/change-password"
            element={
              <Guard allowChange>
                <ChangePassword />
              </Guard>
            }
          />
          <Route
            path="/classrooms"
            element={
              <Guard>
                <Dashboard />
              </Guard>
            }
          />
          <Route
            path="/teach/courses/:courseId"
            element={
              <Guard>
                <TeacherCourse />
              </Guard>
            }
          />
          <Route
            path="/classrooms/:sectionId"
            element={
              <Guard>
                <StudentClass />
              </Guard>
            }
          />
          <Route
            path="*"
            element={
              <section>
                <h1>페이지를 찾을 수 없어요</h1>
                <Link to="/">처음으로</Link>
              </section>
            }
          />
        </Routes>
      </main>
      {/* 학생이 강의실에 들어간 뒤 화면 오른쪽 아래 AI 질문 아이콘 (실습 퀴즈 아이콘과 같은 모양) — AI 질문·실습 화면에서는 숨겨요 */}
      {classroom && pathname !== "/ai" && !/^\/classrooms\/[^/]+\/practice(?:\/results)?$/.test(pathname) && <ChatFab sectionId={classroom.section.id} />}
      <footer
        className={
          isLanding || isStudentHome
            ? "ln-footer"
            : isLogin
              ? "ln-footer login-footer"
              : undefined
        }
      >
        <span>Lerny · 알고보자</span>
        <span>교수님의 자료로부터, 나의 이해까지.</span>
      </footer>
    </>
  );
}
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ServiceStatusProvider><Shell /></ServiceStatusProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

