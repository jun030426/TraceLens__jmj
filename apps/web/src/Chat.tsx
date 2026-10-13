import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, post, type Answer, type Job } from "./api";
import { AIAvailability, ErrorNotice } from "./components";
import { QuestionArchive } from "./QuestionArchive";
import { sourceLabel } from "./sourceLabels";

type Message = {
  id: string;
  question: string;
  answer?: Answer;
  error?: string;
};
type History = {
  thread_id: string | null;
  job_id: string | null;
  items: Message[];
  has_more: boolean;
};

export function Chat({
  sectionId,
  courseTitle,
  archiveInSidebar = false,
  onHistoryChange,
}: {
  sectionId: string;
  courseTitle?: string;
  archiveInSidebar?: boolean;
  onHistoryChange?: () => void;
}) {
  const messagesRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const followBottom = useRef(true);
  const previousScroll = useRef<{ height: number; top: number } | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [olderLoading, setOlderLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyRevision, setHistoryRevision] = useState(0);
  const [archiveRevision, setArchiveRevision] = useState(0);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [thread, setThread] = useState<string>();
  const [job, setJob] = useState<string>();
  const [jobStatus, setJobStatus] = useState("");
  const [items, setItems] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [showLatest, setShowLatest] = useState(false);

  useEffect(() => {
    let active = true;
    setHistoryLoading(true);
    setHistoryError("");
    api<History>(
      `/sections/${sectionId}/chat/history?limit=20&latest_thread=true`,
    )
      .then((result) => {
        if (!active) return;
        followBottom.current = true;
        setItems(result.items);
        setThread(result.thread_id || undefined);
        setJob(result.job_id || undefined);
        setHasMore(result.has_more);
      })
      .catch((error) => {
        if (active) setHistoryError(error.message);
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sectionId, historyRevision]);

  useEffect(() => {
    if (!job) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<Job>(`/jobs/${job}`);
        if (stopped) return;
        setJobStatus(result.status);
        if (["succeeded", "failed", "cancelled"].includes(result.status)) {
          setItems((old) =>
            old.map((item, index) =>
              index === old.length - 1
                ? {
                    ...item,
                    answer: result.result || undefined,
                    error: result.error
                      ? "답변 처리에 실패했어요. 다시 질문해 주세요."
                      : result.status === "cancelled"
                        ? "질문 처리가 취소됐어요."
                        : undefined,
                  }
                : item,
            ),
          );
          setJob(undefined);
          setArchiveRevision((value) => value + 1);
          onHistoryChange?.();
        } else timer = setTimeout(poll, 2000);
      } catch {
        if (!stopped) {
          // Keep the pending request locked until the server confirms a terminal state.
          setJobStatus("connection_error");
          timer = setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [job, onHistoryChange]);

  useLayoutEffect(() => {
    const container = messagesRef.current;
    if (!container || historyLoading) return;
    if (previousScroll.current) {
      container.scrollTop =
        previousScroll.current.top +
        container.scrollHeight -
        previousScroll.current.height;
      previousScroll.current = null;
    } else if (followBottom.current)
      container.scrollTop = container.scrollHeight;
  }, [items, historyLoading]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const resize = () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
      input.style.overflowY = input.scrollHeight > 144 ? "auto" : "hidden";
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [draft]);

  async function loadOlder() {
    if (!thread || olderLoading) return;
    setOlderLoading(true);
    setHistoryError("");
    try {
      const query = new URLSearchParams({
        limit: "20",
        offset: String(items.length),
        thread_id: thread,
      });
      const result = await api<History>(
        `/sections/${sectionId}/chat/history?${query}`,
      );
      const container = messagesRef.current;
      if (container)
        previousScroll.current = {
          height: container.scrollHeight,
          top: container.scrollTop,
        };
      setItems((old) => [
        ...result.items.filter(
          (item) => !old.some((existing) => existing.id === item.id),
        ),
        ...old,
      ]);
      setHasMore(result.has_more);
    } catch (error) {
      setHistoryError((error as Error).message);
    } finally {
      setOlderLoading(false);
    }
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (
      !question ||
      sending ||
      job ||
      historyLoading ||
      (historyError && !items.length)
    )
      return;
    setSending(true);
    setSendError("");
    try {
      const result = await api<{
        job_id: string;
        thread_id: string;
        resource_id: string;
      }>(`/sections/${sectionId}/chat/messages`, {
        ...post({ thread_id: thread, message: question }),
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      followBottom.current = true;
      setShowLatest(false);
      setThread(result.thread_id);
      setItems((old) => [...old, { id: result.resource_id, question }]);
      setJobStatus("queued");
      setJob(result.job_id);
      setDraft("");
      setArchiveRevision((value) => value + 1);
      onHistoryChange?.();
    } catch (error) {
      setSendError((error as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="panel chat" aria-label="수업 자료 기반 AI 대화">
      <div className="chat-heading">
        <div className="chat-heading-title">
          <span className="chat-heading-caption">
            수업 자료와 함께하는 대화
          </span>
          <h2>{courseTitle || "궁금한 내용을 물어보세요"}</h2>
        </div>
        <button
          type="button"
          disabled={!!job || sending || historyLoading || olderLoading}
          onClick={() => {
            setItems([]);
            setThread(undefined);
            setHasMore(false);
            setHistoryError("");
            setSendError("");
            setDraft("");
            setArchiveOpen(false);
            followBottom.current = true;
            setShowLatest(false);
            inputRef.current?.focus();
          }}
        >
          새 대화 <span aria-hidden="true">＋</span>
        </button>
      </div>
      <AIAvailability compact />
      {!archiveInSidebar && (
        <QuestionArchive
          sectionId={sectionId}
          revision={archiveRevision}
          open={archiveOpen}
          onOpenChange={setArchiveOpen}
        />
      )}
      <div
        className="chat-messages"
        ref={messagesRef}
        tabIndex={0}
        aria-label="현재 대화"
        onScroll={(event) => {
          const container = event.currentTarget;
          followBottom.current =
            container.scrollHeight -
              container.scrollTop -
              container.clientHeight <
            80;
          setShowLatest(!followBottom.current);
        }}
      >
        {hasMore && (
          <button
            className="chat-load-older"
            disabled={olderLoading}
            onClick={() => void loadOlder()}
          >
            {olderLoading ? "앞선 대화를 불러오는 중…" : "↑ 앞선 대화 불러오기"}
          </button>
        )}
        <ErrorNotice text={historyError} />
        {historyError && (
          <button
            onClick={() =>
              hasMore
                ? void loadOlder()
                : setHistoryRevision((value) => value + 1)
            }
          >
            다시 불러오기
          </button>
        )}
        {historyLoading && (
          <p className="chat-loading" role="status">
            이전 대화를 불러오는 중이에요…
          </p>
        )}
        {!historyLoading && !historyError && items.length === 0 && (
          <div className="chat-welcome">
            <span className="chat-welcome-icon" aria-hidden="true">
              ✦
            </span>
            <h3>어떤 부분을 함께 살펴볼까요?</h3>
            <p>
              궁금한 개념이나 이해되지 않은 부분을 물어보세요.
              <br />
              공개된 수업 자료에서 답변과 근거를 찾아드려요.
            </p>
            <div className="chat-suggestions" aria-label="질문 예시">
              {[
                "이 강의의 핵심 개념을 정리해 줘",
                "자료에 나온 개념을 예시로 설명해 줘",
              ].map((question) => (
                <button
                  key={question}
                  type="button"
                  disabled={historyLoading}
                  onClick={() => {
                    setDraft(question);
                    inputRef.current?.focus();
                  }}
                >
                  {question} <span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {items.map((item, index) => (
          <article key={item.id} className="conversation">
            <div className="chat-user-message">
              <span className="chat-speaker">나</span>
              <p>{item.question}</p>
            </div>
            <div className="chat-assistant-message">
              <span className="chat-assistant-avatar" aria-hidden="true">
                L
              </span>
              <div className="chat-assistant-body">
                <span className="chat-speaker">Lerny</span>
                {item.answer ? (
                  <>
                    <p className="answer">{item.answer.answer}</p>
                    {!!item.answer.citations?.length && (
                      <div
                        className="chat-citations"
                        aria-label="답변 근거 자료"
                      >
                        <span>수업 자료에서 확인하기</span>
                        {item.answer.citations.map((citation, number) => (
                          <a
                            key={`${citation.material_id}:${number}`}
                            href={`/api/v1/materials/${citation.material_id}/file?version_id=${citation.version_id}`}
                          >
                            <span>{citation.title}</span>
                            <small>{sourceLabel(citation.locator)} ↗</small>
                          </a>
                        ))}
                      </div>
                    )}
                  </>
                ) : item.error ? (
                  <ErrorNotice text={item.error} />
                ) : (
                  <p
                    className="chat-answer-pending"
                    role={index === items.length - 1 ? "status" : undefined}
                  >
                    {jobStatus === "waiting_ai"
                      ? "AI 연결을 기다리고 있어요. 질문은 보관되어 있습니다."
                      : jobStatus === "connection_error"
                        ? "연결 상태를 다시 확인하고 있어요. 질문은 보관되어 있습니다."
                        : "수업 자료에서 답변의 근거를 확인하고 있어요…"}
                  </p>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
      <div className="chat-composer">
        {showLatest && (
          <button
            className="chat-jump-latest"
            type="button"
            onClick={() => {
              followBottom.current = true;
              messagesRef.current?.scrollTo({
                top: messagesRef.current.scrollHeight,
                behavior: "smooth",
              });
            }}
          >
            최근 대화로 ↓
          </button>
        )}
        <ErrorNotice text={sendError} />
        <form
          className="chat-input-form"
          onSubmit={(event) => void send(event)}
        >
          <textarea
            ref={inputRef}
            aria-label="수업 자료에 질문하기"
            name="message"
            placeholder="수업에서 궁금한 내용을 물어보세요"
            rows={1}
            maxLength={4000}
            required
            value={draft}
            disabled={
              !!job ||
              sending ||
              historyLoading ||
              (!!historyError && !items.length)
            }
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing &&
                window.matchMedia("(min-width: 761px)").matches
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button
            type="submit"
            aria-label="질문 보내기"
            disabled={
              !draft.trim() ||
              !!job ||
              sending ||
              historyLoading ||
              (!!historyError && !items.length)
            }
          >
            <span aria-hidden="true">↑</span>
          </button>
        </form>
        <p className="chat-input-help">
          <span>수업 자료 기반 답변 · 출처를 함께 확인하세요.</span>
          <span className="chat-keyboard-hint">
            Enter 전송 · Shift+Enter 줄바꿈
          </span>
        </p>
      </div>
    </section>
  );
}
