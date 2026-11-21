import type { Classroom, Concept, Course, Enrollment, Material, Section, Term } from "./api";
import { testJob } from "./testChat";

/* 테스트용 화면에서 쓰는 샘플 데이터.
   로그인 화면의 테스트 버튼으로 들어오면 서버 대신 여기 데이터로 화면을 채워요.
   저장 · 수정 같은 요청은 서버로 보내지 않아요. */

const TOPICS = [
  "자료구조 개요", "배열과 리스트", "연결 리스트", "스택", "큐와 덱", "해시 테이블",
  "재귀", "중간 정리", "트리", "이진 탐색 트리", "힙과 우선순위 큐", "그래프",
  "그래프 탐색", "정렬 알고리즘", "탐색 알고리즘", "기말 정리",
];
const CURRENT_WEEK = 6;

const term: Term = { id: "t1", name: "2026학년도 2학기", starts_on: "2026-09-01", ends_on: "2026-12-21" };
const course: Course = {
  id: "c1", title: "자료구조", term_id: "t1",
  teaching_language: "python", revision: 1, lead_teacher_id: "test-teacher",
};
const course2: Course = {
  id: "c2", title: "객체지향 프로그래밍 — 자바로 배우는 설계", term_id: "t1",
  teaching_language: "java", revision: 1, lead_teacher_id: "test-teacher",
};
const concepts: Concept[] = TOPICS.map((name, i) => ({
  id: `k${i + 1}`, name, description: `${i + 1}주차에 다루는 ${name} 핵심 개념`, revision: 1,
}));
const covered = concepts.slice(0, CURRENT_WEEK).map((c) => c.id);
const sections: Section[] = [
  { id: "s1", title: "01분반", course_id: "c1", revision: 1, progress: covered, progress_mode: "auto" },
  { id: "s2", title: "02분반", course_id: "c1", revision: 1, progress: covered, progress_mode: "auto" },
];
const sections2: Section[] = [
  { id: "s3", title: "01분반", course_id: "c2", revision: 1, progress: [], progress_mode: "auto" },
];

const NAMES = ["김하늘", "이서준", "박지민", "최유나", "정민호", "강서연", "윤도윤", "임채원", "한지우", "오세린"];
const roster: Record<string, Enrollment[]> = {
  s1: NAMES.slice(0, 5).map((n, i) => ({ id: `e1${i}`, student_id: `st${i}`, display_name: n, status: "active" })),
  s2: [
    ...NAMES.slice(5, 8).map((n, i) => ({ id: `e2${i}`, student_id: `st${i + 5}`, display_name: n, status: "active" })),
    ...NAMES.slice(8).map((n, i) => ({ id: `e2p${i}`, student_id: `st${i + 8}`, display_name: n, status: "pending" })),
  ],
  s3: [],
};

const materials: Material[] = TOPICS.map((name, i) => ({
  id: `m${i + 1}`, title: `${i + 1}주차 · ${name}`, kind: "lecture", week: i + 1,
  visibility: i < CURRENT_WEEK + 2 ? "public" : "private", internal_use: "allowed", revision: 1,
  learning_status: "ready",
  version: { id: `v${i + 1}`, status: "ready", filename: `week${String(i + 1).padStart(2, "0")}.pdf`, error_code: null },
  view_url: `/materials/m${i + 1}/view`,
}));

/* AI 강의 · 강의 자료 요약 샘플: 자료 비중 15% 이상 개념만 영상으로 만들어요. 12%짜리는 화면에서 걸러져요. */
const SUMMARY: Record<number, [string, number, string, string[]][]> = {
  1: [["자료구조가 필요한 이유", 0.34, "p.2–6", ["같은 데이터라도 저장 방식에 따라 찾기·넣기·지우기 속도가 크게 달라요.", "문제에 맞는 자료구조를 고르는 것이 알고리즘 효율의 출발점이에요.", "이번 학기에는 선형 구조(배열·리스트·스택·큐)에서 비선형 구조(트리·그래프)로 넓혀 가요."]],
      ["시간 복잡도와 빅오 표기", 0.27, "p.7–12", ["입력 크기 n이 커질 때 연산 횟수가 늘어나는 정도를 나타내요.", "상수와 낮은 차수 항은 버리고 가장 빠르게 커지는 항만 남겨요.", "O(1) < O(log n) < O(n) < O(n log n) < O(n²) 순서로 느려져요."]],
      ["추상 자료형(ADT)", 0.18, "p.13–15", ["무엇을 할 수 있는지(연산)와 어떻게 구현하는지를 나눠서 생각해요.", "같은 ADT를 배열로도, 연결 리스트로도 구현할 수 있어요."]],
      ["파이썬 개발 환경", 0.12, "p.16–17", ["실습 환경 설치 안내예요."]]],
  2: [["배열의 메모리 구조", 0.31, "p.3–8", ["원소가 메모리에 연속으로 놓여서 인덱스로 바로 접근할 수 있어요(O(1)).", "중간에 넣거나 지우면 뒤 원소를 모두 밀거나 당겨야 해서 O(n)이 걸려요."]],
      ["파이썬 리스트와 동적 배열", 0.26, "p.9–14", ["파이썬 list는 공간이 모자라면 더 큰 배열을 새로 잡고 옮겨 담는 동적 배열이에요.", "append는 대부분 O(1)이고, 가끔 생기는 확장 비용을 나눠 보면 평균 O(1)이에요.", "insert(0, x)나 pop(0)은 O(n)이라 자주 쓰면 느려져요."]],
      ["2차원 배열", 0.16, "p.15–18", ["행과 열로 표를 표현해요. arr[i][j]로 접근해요.", "[[0]*m]*n 처럼 만들면 모든 행이 같은 리스트를 가리키니 주의해요."]]],
  3: [["단순 연결 리스트", 0.38, "p.2–9", ["각 노드가 값과 다음 노드를 가리키는 링크를 가져요.", "앞에 넣기·지우기는 O(1)이지만, k번째 원소를 찾으려면 처음부터 따라가야 해서 O(n)이에요.", "head가 None이면 빈 리스트예요."]],
      ["노드 삽입과 삭제", 0.29, "p.10–16", ["삽입은 새 노드의 next를 먼저 연결하고, 그다음 앞 노드의 next를 바꿔요.", "삭제는 앞 노드의 next가 지울 노드의 다음 노드를 가리키게 해요.", "순서를 바꾸면 링크가 끊겨 뒤쪽 노드를 잃어버려요."]],
      ["이중 연결 리스트", 0.17, "p.17–20", ["노드가 이전·다음 링크를 모두 가져서 양쪽으로 이동할 수 있어요.", "링크가 두 개라 삽입·삭제 때 바꿀 포인터가 4개예요."]]],
  4: [["스택의 LIFO 원리", 0.33, "p.2–6", ["마지막에 넣은 것이 먼저 나와요(Last In, First Out).", "push·pop·peek 모두 O(1)이에요.", "파이썬에서는 list의 append와 pop으로 간단히 구현해요."]],
      ["괄호 검사", 0.24, "p.7–11", ["여는 괄호는 push, 닫는 괄호가 나오면 pop해서 짝이 맞는지 확인해요.", "끝났을 때 스택이 비어 있어야 올바른 괄호예요."]],
      ["후위 표기식 계산", 0.21, "p.12–17", ["피연산자는 push, 연산자가 나오면 두 개를 pop해서 계산한 값을 다시 push해요.", "pop 순서에 주의해요: 먼저 나온 값이 오른쪽 피연산자예요."]]],
  5: [["큐의 FIFO 원리", 0.30, "p.2–6", ["먼저 넣은 것이 먼저 나와요(First In, First Out).", "list.pop(0)은 O(n)이라 collections.deque를 써요."]],
      ["원형 큐", 0.27, "p.7–13", ["배열 끝에 닿으면 처음으로 돌아가며 공간을 다시 써요.", "front와 rear를 (i + 1) % 크기로 움직여요.", "꽉 찬 상태와 빈 상태를 구분하려고 한 칸을 비워 두기도 해요."]],
      ["덱(deque)", 0.19, "p.14–17", ["앞과 뒤 양쪽에서 넣고 뺄 수 있어요.", "appendleft·popleft 모두 O(1)이에요."]]],
  6: [["해시 함수", 0.29, "p.2–7", ["키를 배열 인덱스로 바꿔 주는 함수예요.", "같은 키는 항상 같은 값이 나와야 하고, 값이 고르게 퍼질수록 좋아요."]],
      ["충돌 해결: 체이닝", 0.25, "p.8–12", ["같은 칸에 들어온 키들을 연결 리스트로 이어서 보관해요.", "한 칸에 몰리면 찾는 시간이 O(n)까지 늘어나요."]],
      ["충돌 해결: 개방 주소법", 0.22, "p.13–18", ["빈 칸이 나올 때까지 다음 칸(선형 탐사) 등을 살펴 넣어요.", "지울 때는 '삭제됨' 표시를 남겨야 뒤쪽 탐색이 끊기지 않아요.", "적재율이 높아지면 테이블을 키워 다시 넣어요."]]],
};
function lectureSummary(materialId: string) {
  const week = Number(materialId.replace(/^m/, ""));
  const rows = SUMMARY[week] || [[`${TOPICS[week - 1] || "핵심 개념"} 핵심 정리`, 0.4, "p.2–10", [`${TOPICS[week - 1] || "이번 주"} 자료에서 가장 비중이 큰 부분을 정리했어요.`, "세부 요약은 영상이 만들어지면 함께 채워져요."]]] as [string, number, string, string[]][];
  return { items: rows.map(([concept, share, pages, points], i) => ({ concept, share, pages, points, video_status: week < CURRENT_WEEK ? "ready" : i === 0 ? "making" : "planned" })) };
}

const classrooms: Classroom[] = [
  { teacher_name: "테스트 교수", current_week: CURRENT_WEEK, enrollment_id: "e10", status: "active", section: sections[0], course, term },
  { teacher_name: "테스트 교수", current_week: null, enrollment_id: "e30", status: "pending", section: sections2[0], course: course2, term },
];

const kst = (offset: number) =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date(Date.now() - offset * 86400000));
const records = [1, 2, 3, 5, 6, 8, 9, 10].map((d, i) => ({
  id: `r${i}`, section_id: "s1", day: kst(d), total: 3, submitted: 3, pending: 0, valid: 3, correct: 2 + (i % 2),
}));

const counts = (participation: number, valid: number, correct: number) => ({
  participation, valid, correct, pending: 0, accuracy: valid ? Math.round((correct / valid) * 100) : null,
});
const analytics = (sectionId: string) => {
  const people = roster[sectionId]?.filter((e) => e.status === "active") || [];
  return {
    summary: counts(people.length, people.length * 18, people.length * 13),
    concepts: concepts.slice(0, CURRENT_WEEK).map((c, i) => ({ id: c.id, name: c.name, ...counts(people.length, people.length * 3, people.length * 3 - (i % 3) - 1) })),
    students: people.map((p, i) => ({ id: p.student_id, name: p.display_name, ...counts(1, 18, 10 + i) })),
  };
};

const weekly = {
  mode: "auto", actual_week: CURRENT_WEEK, calendar_week: CURRENT_WEEK, revision: 1, applied_ids: covered,
  schedule: TOPICS.map((_, i) => ({ week: i + 1, date: new Date(Date.UTC(2026, 8, 1 + i * 7)).toISOString().slice(0, 10) })),
  weeks: concepts.map((c, i) => ({ week: i + 1, concepts: [{ id: c.id, name: c.name, description: c.description }] })),
};

const plans = [
  { id: "p1", title: "중간고사 대비", start_week: 1, end_week: 7, published: true, revision: 1 },
  { id: "p2", title: "기말고사 대비", start_week: 9, end_week: 15, published: false, revision: 1 },
];

/* AI 질문 · 질문하기 샘플 대화 */
const TEST_CHAT = [
  { question: "충돌이 나면 어떻게 해요?", answer: { answer_kind: "grounded", answer: "서로 다른 키가 같은 칸으로 가는 걸 충돌이라고 해요. 같은 칸에 연결 리스트로 이어 붙이는 체이닝이나, 비어 있는 다음 칸을 찾아가는 개방 주소법으로 해결해요.", citations: [{ material_id: "m6", version_id: "v6", title: "6주차 · 해시 테이블", locator: { page: 7 }, excerpt: "" }] } },
  { question: "해시 테이블은 왜 찾는 속도가 빨라요?", answer: { answer_kind: "grounded", answer: "해시 함수가 키를 바로 저장 위치(버킷 번호)로 바꿔 주기 때문이에요. 처음부터 하나씩 비교하지 않고 그 칸으로 곧장 가니까 평균 O(1)에 찾을 수 있어요.", citations: [{ material_id: "m6", version_id: "v6", title: "6주차 · 해시 테이블", locator: { page: 4 }, excerpt: "" }] } },
];

/* 오늘의 이론 퀴즈 샘플: 매번 객관식 2문항 + 서술형 1문항 */
const testDaily = (sectionId: string) => ({
  id: `test-daily-${sectionId}`, section_id: sectionId, day: kst(0), shortage: 0,
  items: [
    { id: "tq1", kind: "mcq", revision: 1, status: "active", attempt: null,
      prompt: "스택에 1, 2, 3을 차례로 push 한 뒤 pop 을 한 번 하면 나오는 값은?",
      options: ["1이 나온다", "2가 나온다", "3이 나온다", "아무것도 나오지 않는다"],
      hints: ["4주차 자료 '스택의 push와 pop' 부분을 다시 보세요.", "스택은 접시를 쌓듯 맨 위에서만 넣고 빼요.", "가장 나중에 넣은 값이 맨 위에 있어요."] },
    { id: "tq2", kind: "mcq", revision: 1, status: "active", attempt: null,
      prompt: "해시 테이블을 쓰기에 가장 알맞은 상황은?",
      options: ["값을 크기 순으로 정렬해 둘 때", "학번으로 학생 정보를 바로 찾을 때", "가장 최근에 넣은 값을 먼저 꺼낼 때", "도착한 순서대로 차례를 처리할 때"],
      hints: ["6주차 자료 '해시 테이블을 쓰는 곳' 부분을 다시 보세요.", "해시 테이블은 키로 위치를 계산해 값을 바로 찾는 구조예요.", "'키 → 값'처럼 짝지어 바로 찾는 상황이 어떤 보기인지 골라 보세요."] },
    { id: "tq3", kind: "essay", revision: 1, status: "active", attempt: null, options: [],
      prompt: "해시 테이블에서 충돌이 무엇인지 설명하고, 충돌을 해결하는 방법을 하나 들어 설명하세요.",
      hints: ["6주차 자료 '해시 함수와 버킷' 부분을 다시 보세요.", "서로 다른 두 키의 해시 결과가 같으면 어떤 일이 생길지 떠올려 보세요.", "같은 칸에 여러 값을 이어 붙이는 방법(체이닝)이나 빈 칸을 찾아가는 방법을 떠올려 보세요."] },
  ],
});

/* GET 경로별 샘플 응답. 모르는 경로는 빈 목록을 돌려줘요. */
export function testResponse(path: string, role: string): unknown {
  const p = path.split("?")[0];
  let m: RegExpMatchArray | null;
  if (p === "/classrooms") return { items: classrooms };
  if ((m = p.match(/^\/jobs\/(test-job-\d+)$/))) return testJob(m[1]);
  // 이전 질문 목록에도 쓰여서 개수(total)와 날짜(created_at)를 함께 돌려줘요
  if (p.match(/^\/sections\/[^/]+\/chat\/history$/)) return { thread_id: null, job_id: null, total: TEST_CHAT.length, items: TEST_CHAT.map((x, i) => ({ id: `test-chat-${i}`, created_at: new Date(Date.now() - (TEST_CHAT.length - i) * 864e5).toISOString(), ...x })) };
  if ((m = p.match(/^\/sections\/([^/]+)\/daily$/))) return testDaily(m[1]);
  if ((m = p.match(/^\/learning-sessions\/test-daily-([^/]+)$/))) return testDaily(m[1]);
  if (p === "/terms") return { items: [term] };
  if (p === "/courses") return { items: [course, course2] };
  if (p === "/my/practice-submission-count") return { submitted: 0 };
  if (p === "/my/learning-streak") return { today_completed: false, current_streak: 4, total_days: records.length };
  if (p === "/my/learning-sessions") {
    const q = new URLSearchParams(path.split("?")[1]);
    const from = q.get("date_from"), to = q.get("date_to"), section = q.get("section_id");
    const items = records.filter(r => (!from || r.day >= from) && (!to || r.day <= to) && (!section || r.section_id === section))
      .sort((a, b) => (q.get("order") === "asc" ? 1 : -1) * a.day.localeCompare(b.day));
    const offset = Number(q.get("offset") || 0), limit = Number(q.get("limit") || 100);
    return { items: items.slice(offset, offset + limit), total: items.length };
  }
  if (/^\/sections\/[^/]+\/my-practice$/.test(p)) {
    return { items: [], total: 0, summary: { submitted: 0, independent: 0, correct: 0, wrong: 0, assisted: 0, pending: 0, accuracy: null } };
  }
  if ((m = p.match(/^\/courses\/([^/]+)$/))) return m[1] === "c2" ? course2 : course;
  if ((m = p.match(/^\/courses\/([^/]+)\/sections$/))) return { items: m[1] === "c2" ? sections2 : sections };
  if ((m = p.match(/^\/courses\/([^/]+)\/concepts$/))) return { items: m[1] === "c2" ? [] : concepts };
  if ((m = p.match(/^\/materials\/([^/]+)\/lecture-summary$/))) return lectureSummary(m[1]);
  if ((m = p.match(/^\/materials\/([^/]+)\/preview$/))) {
    const material = materials.find(item => item.id === m![1] && item.visibility === "public");
    if (!material) throw new Error("열람할 수 있는 테스트 강의자료가 없습니다.");
    return { material_id: material.id, course_id: "c1", title: material.title, version_id: material.version!.id,
      status: "ready", pages: [{ number: 1, text: `${material.title}\n\n이 페이지는 화면 확인용 예시 자료입니다.`, image_url: null }] };
  }
  if ((m = p.match(/^\/courses\/([^/]+)\/materials$/))) return { items: m[1] === "c2" ? [] : role === "student" ? materials.filter((x) => x.visibility === "public") : materials };
  if ((m = p.match(/^\/courses\/([^/]+)\/exam-plans$/))) return { items: m[1] === "c2" ? [] : plans };
  if ((m = p.match(/^\/sections\/([^/]+)\/enrollments$/))) return { items: roster[m[1]] || [] };
  if ((m = p.match(/^\/sections\/([^/]+)\/analytics$/))) return analytics(m[1]);
  if (p.match(/^\/sections\/[^/]+\/weekly-progress$/)) return weekly;
  return { items: [], total: 0 };
}
