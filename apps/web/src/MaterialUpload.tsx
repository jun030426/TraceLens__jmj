import { useEffect, useId, useRef, useState } from "react";
import {
  api,
  uploadMaterial,
  type UploadCheckpoint,
  type UploadConfig,
} from "./api";
import { CourseCombo } from "./CourseCombo";
import { ErrorNotice } from "./components";
import "./material-upload.css";

export const MATERIAL_ACCEPT = ".pdf,.pptx,.docx,.txt,.md,.c,.java,.py,.mp4";
const kinds = [
  ["lecture", "일반 강의 자료"],
  ["example", "예제 코드"],
  ["assignment", "과제 안내"],
  ["transcript", "강의자료"],
  ["past_exam", "기출"],
  ["answer", "정답·해설"],
];
const extension = (file: File) =>
  "." + file.name.split(".").pop()!.toLowerCase();
const size = (bytes: number) =>
  bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(0)}GB` : bytes < 1048576
    ? `${Math.max(1, Math.round(bytes / 1024))}KB`
    : `${(bytes / 1048576).toFixed(1)}MB`;
type Item = {
  id: string;
  file: File;
  kind: string;
  week: string;
  visibility: string;
  state: "pending" | "uploading" | "done" | "failed";
  message: string;
};

export function MaterialUpload({
  courseId,
  totalWeeks,
  blocked,
  onChange,
  onBusy,
}: {
  courseId: string;
  totalWeeks: number;
  blocked: string;
  onChange: () => void;
  onBusy: (value: boolean) => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const [config, setConfig] = useState<UploadConfig>();
  const checkpoints = useRef(new Map<string, UploadCheckpoint>());
  const input = useRef<HTMLInputElement>(null);
  const weekInputPrefix = useId();
  const weekOptions = Array.from({ length: totalWeeks }, (_, index) => ({
    value: String(index + 1),
    label: `${index + 1}주차`,
  }));
  useEffect(() => {
    let active = true;
    api<UploadConfig>("/uploads/config")
      .then((value) => {
        if (active) setConfig(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const protect = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [busy]);
  const add = (files: FileList | File[]) => {
    if (busy || blocked) return;
    const incoming = Array.from(files);
    if (items.length + incoming.length > 20) {
      setError(
        "한 번에 최대 20개까지 선택할 수 있어요. 현재 목록을 먼저 올려 주세요.",
      );
      return;
    }
    const next: Item[] = [];
    const problems: string[] = [];
    for (const file of incoming) {
      if (!MATERIAL_ACCEPT.split(",").includes(extension(file))) {
        problems.push(`${file.name}: 지원하지 않는 형식`);
        continue;
      }
      if (!file.size) {
        problems.push(`${file.name}: 빈 파일`);
        continue;
      }
      if (
        [...items, ...next].some(
          (x) =>
            x.file.name === file.name &&
            x.file.size === file.size &&
            x.file.lastModified === file.lastModified,
        )
      )
        continue;
      const limit = config?.limits?.[extension(file)] ?? config?.max_file_bytes;
      if (limit && file.size > limit) {
        problems.push(`${file.name}: 파일당 ${size(limit)} 제한 초과`);
        continue;
      }
      next.push({
        id: crypto.randomUUID(),
        file,
        kind: "",
        week: "1",
        visibility: "private",
        state: "pending",
        message: "자료 종류 선택 필요",
      });
    }
    setItems((old) => [...old, ...next]);
    setError(problems.join(" / "));
  };
  const update = (id: string, values: Partial<Item>) =>
    setItems((old) => old.map((x) => (x.id === id ? { ...x, ...values } : x)));
  const pending = items.filter((x) => x.state !== "done");
  const unclassified = pending.filter((x) => !x.kind).length;
  const done = items.filter((x) => x.state === "done").length;
  return (
    <section id="material-upload" className="panel materials-upload">
      <h2>강의 자료 올리기</h2>
      <p className="materials-upload-intro">
        강의자료·MP4 영상·예제 코드를 함께 선택하세요. 파일마다 자료 종류를
        직접 선택하고 공개 범위를 확인한 뒤 같은 주차에 올릴 수 있어요.
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy || blocked || !pending.length) return;
          if (unclassified) {
            setError("모든 파일의 자료 종류를 선택해 주세요.");
            return;
          }
          if (pending.some(item => !weekOptions.some(option => option.value === item.week))) {
            setError(`등록할 주차를 1~${totalWeeks}주차 사이로 지정해 주세요.`);
            return;
          }
          setBusy(true);
          onBusy(true);
          setError("");
          try {
            for (const item of pending) {
              update(item.id, {
                state: "uploading",
                message: "업로드 준비 중",
              });
              const form = new FormData();
              form.set("file", item.file);
              form.set("kind", item.kind);
              form.set("visibility", item.visibility);
              form.set("week", item.week);
              try {
                await uploadMaterial(courseId, form, undefined, {
                  checkpoint: checkpoints.current.get(item.id),
                  onCheckpoint: (value) =>
                    checkpoints.current.set(item.id, value),
                  onProgress: (value) =>
                    update(item.id, {
                      message:
                        value === 100 ? "저장 확인 중" : `파일 전송 ${value}%`,
                    }),
                });
                checkpoints.current.delete(item.id);
                update(item.id, {
                  state: "done",
                  message: "저장 완료 · 원문 분석 대기",
                });
                onChange();
              } catch (cause) {
                update(item.id, {
                  state: "failed",
                  message:
                    cause instanceof Error
                      ? cause.message
                      : "업로드를 완료하지 못했어요.",
                });
              }
            }
          } finally {
            setBusy(false);
            onBusy(false);
            onChange();
          }
        }}
      >
        <fieldset disabled={busy || !!blocked}>
          <label
            className={`file-drop${over ? " is-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              add(e.dataTransfer.files);
            }}
          >
            <span className="file-drop-title">파일 여러 개 선택</span>
            <span className="file-drop-box">
              <span className="file-drop-icon" aria-hidden="true">
                ⇪
              </span>
              <strong>파일을 함께 끌어다 놓거나 눌러서 선택하세요</strong>
              <small>
                PDF, PPTX, DOCX, TXT, MD, C, JAVA, PY, MP4 · 최대 20개
              </small>
            </span>
            <input
              ref={input}
              className="file-drop-input"
              aria-label="업로드할 파일"
              type="file"
              multiple
              accept={MATERIAL_ACCEPT}
              onChange={(e) => {
                if (e.target.files) add(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
          {config && (
            <p className="batch-help">
              MP4 최대 {size(config.limits?.[".mp4"] ?? config.max_file_bytes)} · 문서 {size(config.max_file_bytes)} · 텍스트 10MB · 예제
              코드 1MB
            </p>
          )}
          <p className="batch-help">
            MP4는 로컬 음성 인식·OCR과 기초 검사로 처리해요. 문제 구간만 보류하고 나머지는 검색을 준비해요. 처리 중에도 원본은
            받을 수 있어요. 정답·해설은 비공개로 저장해요.
          </p>
          <ErrorNotice text={error} />
          {!!items.length && (
            <>
              <p className="batch-count" role="status" id="upload-selection-status">
                선택 {items.length}개 · 저장 완료 {done}개 · 남은 파일{" "}
                {pending.length}개
                {unclassified > 0 && ` · 자료 종류 미선택 ${unclassified}개`}
              </p>
              <div
                className="batch-files"
                role="region"
                aria-label="선택한 업로드 파일"
                tabIndex={0}
              >
                {items.map((item) => (
                  <article
                    key={item.id}
                    className={`batch-file is-${item.state}`}
                    aria-label={item.file.name}
                  >
                    <div className="batch-file-heading">
                      <strong>{item.file.name}</strong>
                      <span>{size(item.file.size)}</span>
                    </div>
                    <div className="batch-file-options">
                      <div className="batch-week">
                        <label htmlFor={weekInputPrefix + item.id}>등록할 주차</label>
                        <CourseCombo label="등록할 주차" options={weekOptions} value={item.week}
                          numericInput={{ id: weekInputPrefix + item.id, max: totalWeeks, disabled: item.state !== "pending" }}
                          onChange={week => update(item.id, { week })}
                        />
                      </div>
                      <label>
                        자료 종류 (필수)
                        <select
                          required
                          disabled={item.state !== "pending"}
                          value={item.kind}
                          onChange={(e) =>
                            update(item.id, {
                              kind: e.target.value,
                              visibility: [
                                "answer",
                                "transcript",
                                "past_exam",
                              ].includes(e.target.value)
                                ? "private"
                                : "public",
                              message: "업로드 대기",
                            })
                          }
                        >
                          <option value="" disabled>자료 종류를 선택하세요</option>
                          {kinds.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        학생 공개
                        <select
                          disabled={
                            item.state !== "pending" || !item.kind || item.kind === "answer"
                          }
                          value={item.visibility}
                          onChange={(e) =>
                            update(item.id, { visibility: e.target.value })
                          }
                        >
                          <option value="public">수강생에게 공개</option>
                          <option value="private">비공개</option>
                        </select>
                      </label>
                      {item.state !== "done" && (
                        <button
                          type="button"
                          onClick={() => {
                            checkpoints.current.delete(item.id);
                            setItems((old) =>
                              old.filter((x) => x.id !== item.id),
                            );
                          }}
                        >
                          목록에서 빼기
                        </button>
                      )}
                    </div>
                    <p className="batch-file-status" role="status">
                      {item.message}
                    </p>
                  </article>
                ))}
              </div>
            </>
          )}
        </fieldset>
        <div className="batch-actions">
          <button
            className="primary"
            type="submit"
            aria-describedby={items.length ? "upload-selection-status" : undefined}
            disabled={busy || !!blocked || !pending.length || unclassified > 0}
          >
            {busy
              ? "파일 업로드 중…"
              : items.some((x) => x.state === "failed")
                ? "미완료 파일 다시 올리기"
                : `선택한 파일 ${pending.length}개 올리기`}
          </button>
          {!busy && items.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setItems([]);
                checkpoints.current.clear();
                setError("");
              }}
            >
              선택 목록 비우기
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
