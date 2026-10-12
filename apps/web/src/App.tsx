import { useContext, useEffect, useRef, useState } from "react";
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
import { PracticeWorkspace, PracticeResults } from "./Practice";
import { StudentExamPrep } from "./ExamPrep";
import { Landing } from "./Landing";
import { InstructorClass } from "./Instructor";
import { StudentToday } from "./StudentToday";

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
  const { user, refresh } = useContext(Auth);
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
  const isStudentHome =
    pathname === "/student" ||
    ((pathname === "/professor" || pathname === "/professor/notices" || pathname === "/professor/students" || pathname.startsWith("/professor/courses/")) && user?.role === "teacher") ||
    ((pathname === "/courses" ||
      pathname === "/ai" ||
      pathname === "/attendance" ||
      pathname === "/exam-prep" ||
      pathname === "/mypage" ||
      /^\/classrooms\/[^/]+\/lectures$/.test(pathname) ||
      /^\/classrooms\/[^/]+\/practice(?:\/results)?$/.test(pathname) ||
      pathname === "/quiz" ||
      /^\/quiz\/(?:results\/)?[^/]+$/.test(pathname) ||
      /^\/classrooms\/[^/]+$/.test(pathname)) &&
      user?.role === "student");
  const isLogin = ["/login", "/signup", "/reset", "/change-password"].includes(
    pathname,
  );
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
          "app-header " + (classroom
            ? "ln-header lesson-header"
            : isLanding || isStudentHome
              ? "ln-header"
              : isLogin
                ? "ln-header login-header"
                : "")
        }
      >
        <Link className="brand" to={user ? "/home" : "/"}>
          Lerny<span>●</span>
        </Link>
        {classroom && (
          <Link className="lesson-exit" to="/courses">
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5m6-6-6 6 6 6" /></svg>
            <span>내 강의로</span>
          </Link>
        )}
        <button ref={menuButton} type="button" className="mobile-menu-toggle" aria-expanded={menuOpen} aria-controls="app-navigation" onClick={() => setOpenMenu(menuOpen ? null : menuKey)}>
          <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span> {menuOpen ? "메뉴 닫기" : "메뉴"}
        </button>
        <nav id="app-navigation" data-open={menuOpen} aria-label={classroom ? "강의실 학습 메뉴" : "주 메뉴"} onClick={event => { if ((event.target as Element).closest("a, button")) setOpenMenu(null); }}>
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
                  : [["/classrooms", "운영 관리"]]
              ).map(([path, label]) => (
                <NavLink
                  key={path}
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
              ))}
              <NavLink to="/mypage">내 정보</NavLink>
              {!classroom && <span>{user.display_name}</span>}
              <button
                onClick={async () => {
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
              >
                로그아웃
              </button>
            </>
          ) : (
            <>
              <Link to="/login">로그인</Link>
              <Link to="/signup">학생 가입</Link>
            </>
          )}
        </nav>
      </header>

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
          <Route path="/classrooms/:sectionId/lectures" element={<Guard><StudentOnly><InstructorClass /></StudentOnly></Guard>} />
          <Route path="/classrooms/:sectionId/practice/results" element={<Guard><StudentOnly><PracticeResults /></StudentOnly></Guard>} />
          <Route path="/classrooms/:sectionId/practice" element={<Guard><StudentOnly><PracticeWorkspace /></StudentOnly></Guard>} />
          <Route path="/" element={<Landing />} />
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
        <Shell />
      </AuthProvider>
    </BrowserRouter>
  );
}

