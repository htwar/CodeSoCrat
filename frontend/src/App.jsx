import Editor from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import {
  deleteProblem,
  disableProblem,
  enableProblem,
  getAnswerKey,
  getAuthorProblem,
  getAuthorProblems,
  getGoogleConfig,
  getHints,
  getProblems,
  getSession,
  googleAuth,
  login,
  logout,
  register,
  resetProgress,
  runCode,
  submitCode,
  updateProblem,
  uploadProblem,
  uploadProblemFile,
} from "./api";

const starterUploadTemplate = `{
  "problem_id": "multiply_two_numbers",
  "title": "Multiply Two Numbers",
  "prompt": "Write a function named multiply_numbers(a, b) that returns the product of two numbers.",
  "difficulty": "Easy",
  "function_name": "multiply_numbers",
  "starter_code": "def multiply_numbers(a, b):\\n    pass\\n",
  "example_cases": [
    { "input": [2, 3], "expected": 6 }
  ],
  "test_cases": [
    { "input": [-1, 4], "expected": -4 }
  ],
  "hints": {
    "1": "Think about the arithmetic operation used to combine repeated groups.",
    "2": "Return the result of multiplying the two parameters.",
    "3": "Use: return a * b"
  },
  "answer_key": {
    "solution_code": "def multiply_numbers(a, b):\\n    return a * b\\n",
    "explanation": "The function returns the product of the two numbers using the * operator."
  }
}`;

const demoSolution = "def add_numbers(a, b):\n    return a + b\n";
const DIFFICULTIES = ["Easy", "Medium", "Hard"];
const TIME_LIMITS = {
  Easy: 5 * 60,
  Medium: 10 * 60,
  Hard: 15 * 60,
};
const AUTHOR_FILTERS = [
  { id: "all", label: "All visible" },
  { id: "starter", label: "Starter only" },
  { id: "author", label: "My uploads" },
];
const HINT_TYPE_LABELS = {
  0: "None",
  1: "Conceptual",
  2: "Strategic",
  3: "Syntactic",
};
const WORKSPACE_STORAGE_PREFIX = "codesocrat_workspace_v1";

function formatSeconds(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function getWorkspaceStorageKey(userId) {
  return `${WORKSPACE_STORAGE_PREFIX}:${userId}`;
}

function AuthPanel({ onLogin, onRegister, onGoogleCredential, googleConfig, loading, error }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("student@codesocrat.dev");
  const [password, setPassword] = useState("studentpass");
  const [confirmPassword, setConfirmPassword] = useState("");
  const googleButtonRef = useRef(null);

  useEffect(() => {
    if (!googleConfig.enabled || !window.google?.accounts?.id || !googleButtonRef.current) {
      return;
    }

    googleButtonRef.current.innerHTML = "";
    window.google.accounts.id.initialize({
      client_id: googleConfig.client_id,
      callback: ({ credential }) => onGoogleCredential(credential),
    });
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      theme: "outline",
      size: "large",
      shape: "pill",
      text: mode === "register" ? "signup_with" : "signin_with",
      width: 320,
    });
  }, [googleConfig, mode, onGoogleCredential]);

  function handleSubmit(event) {
    event.preventDefault();
    if (mode === "register") {
      onRegister({ email, password, confirm_password: confirmPassword });
      return;
    }
    onLogin({ email, password });
  }

  return (
    <section className="auth-card" aria-labelledby="auth-title">
      <h1 id="auth-title">CodeSoCrat</h1>
      <p className="eyebrow">Practice Python with guided feedback</p>
      <p className="lede">
        Sign in with email or Google. New accounts start as students, and author permissions stay role-based on the backend.
      </p>
      <div className="auth-toggle" role="tablist" aria-label="Authentication mode">
        <button
          type="button"
          className={mode === "login" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("login")}
          role="tab"
          aria-selected={mode === "login"}
        >
          Sign in
        </button>
        <button
          type="button"
          className={mode === "register" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("register")}
          role="tab"
          aria-selected={mode === "register"}
        >
          Create account
        </button>
      </div>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label htmlFor="auth-email">Email</label>
        <input
          id="auth-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label htmlFor="auth-password">Password</label>
        <input
          id="auth-password"
          type="password"
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        {mode === "register" ? (
          <>
            <label htmlFor="auth-confirm-password">Confirm Password</label>
            <input
              id="auth-confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
            />
          </>
        ) : null}
        <button type="submit" disabled={loading}>
          {loading ? (mode === "register" ? "Creating..." : "Signing in...") : (mode === "register" ? "Create account" : "Sign in")}
        </button>
      </form>
      {googleConfig.enabled ? (
        <div className="google-auth-block">
          <div className="divider" aria-hidden="true">
            <span>or</span>
          </div>
          <div ref={googleButtonRef} className="google-button-slot" aria-label="Continue with Google" />
        </div>
      ) : (
        <p className="meta-copy">Google sign-in becomes available after `CODESOCRAT_GOOGLE_CLIENT_ID` is configured.</p>
      )}
      <p className="status-text" aria-live="polite">
        {error || ""}
      </p>
      <div className="account-hints">
        <span>Student demo: student@codesocrat.dev / studentpass</span>
        <span>Author demo: author@codesocrat.dev / authorpass</span>
      </div>
    </section>
  );
}

function ProblemList({ problems, selectedDifficulty, selectedProblemId, onDifficultyChange, onSelect }) {
  return (
    <aside className="panel problem-list">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Problem Set</p>
          <h2>Choose a challenge</h2>
        </div>
      </div>
      <div className="difficulty-picker" role="tablist" aria-label="Difficulty levels">
        {DIFFICULTIES.map((difficulty) => (
          <button
            key={difficulty}
            type="button"
            className={selectedDifficulty === difficulty ? "difficulty-chip active" : "difficulty-chip"}
            onClick={() => onDifficultyChange(difficulty)}
            role="tab"
            aria-selected={selectedDifficulty === difficulty}
          >
            {difficulty}
          </button>
        ))}
      </div>
      <div className="problem-items">
        {problems.length === 0 ? <p className="meta-copy">No active problems are available in this difficulty yet.</p> : null}
        {problems.map((problem) => (
          <button
            key={problem.problem_id}
            className={selectedProblemId === problem.problem_id ? "problem-item active" : "problem-item"}
            onClick={() => onSelect(problem.problem_id)}
            type="button"
          >
            <strong>{problem.title}</strong>
            <span>{problem.difficulty}</span>
            <span className={`source-pill ${problem.source}`}>{problem.source === "starter" ? "Starter" : "Custom"}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function SubmissionPanel({
  problem,
  code,
  setCode,
  onRun,
  onSubmit,
  onResetProgress,
  timedChallenge,
  onEnableTimedMode,
  onDisableTimedMode,
  onStartTimedMode,
  submissionState,
  hintState,
  answerKeyState,
  onViewAnswerKey,
  onUnlockHint,
}) {
  const editorOptions = {
    automaticLayout: true,
    fontSize: 15,
    glyphMargin: false,
    lineNumbers: "on",
    minimap: { enabled: false },
    padding: { top: 16, bottom: 16 },
    renderLineHighlight: "all",
    roundedSelection: false,
    scrollBeyondLastLine: false,
    tabSize: 4,
    wordWrap: "on",
  };

  if (!problem) {
    return (
      <section className="panel workspace-panel empty-panel">
        <h2>Pick a problem to begin</h2>
        <p>Your prompt, editor, results, and hints will appear here.</p>
      </section>
    );
  }

  return (
    <section className="workspace-grid">
      <div className="panel workspace-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{problem.difficulty}</p>
            <h2>{problem.title}</h2>
          </div>
          <div className="panel-actions">
            <span className={`source-pill ${problem.source}`}>{problem.source === "starter" ? "Starter" : "Custom"}</span>
            <button type="button" className="secondary-button" onClick={() => setCode(problem.starter_code || "")}>
              Reset to Starter
            </button>
            <button type="button" className="danger-button" onClick={onResetProgress}>
              Reset Progress
            </button>
          </div>
        </div>
        <p className="prompt-copy">{problem.prompt}</p>
        <p className="meta-copy">
          Required function: <code>{problem.function_name}</code>
        </p>
        {problem.example_cases?.length ? (
          <div className="examples-panel">
            <p className="meta-copy"><strong>Sample Cases</strong></p>
            <div className="example-list">
              {problem.example_cases.map((exampleCase, index) => (
                <div key={`${problem.problem_id}-example-${index}`} className="example-card">
                  <p className="meta-copy">Example {index + 1}</p>
                  <p className="meta-copy">
                    Input: <code>{JSON.stringify(exampleCase.input)}</code>
                  </p>
                  <p className="meta-copy">
                    Expected: <code>{JSON.stringify(exampleCase.expected)}</code>
                  </p>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        <section className={["timer-panel", timedChallenge.status].join(" ").trim()}>
          <div>
            <p className="eyebrow">Timed Mode</p>
            <h3>
              {timedChallenge.status === "running"
                ? "Timed challenge in progress"
                : timedChallenge.status === "expiring"
                  ? "Submitting timed challenge"
                : timedChallenge.status === "expired"
                  ? "Time is up"
                  : timedChallenge.status === "completed"
                    ? "Timed challenge completed"
                    : timedChallenge.enabled
                      ? "Challenge timer ready"
                      : "Practice without a timer"}
            </h3>
            <p className="meta-copy">
              {timedChallenge.status === "completed"
                ? "You finished the timed challenge. Start another one whenever you want a new pressure run."
                : timedChallenge.status === "expiring"
                  ? "The timer reached zero and your latest saved code is being submitted automatically."
                : timedChallenge.enabled
                  ? `This ${problem.difficulty.toLowerCase()} problem gets ${formatSeconds(timedChallenge.limitSeconds)}. When time reaches 00:00, your current code is automatically submitted for grading.`
                  : `Optional challenge timer: ${formatSeconds(timedChallenge.limitSeconds)} for ${problem.difficulty} problems.`}
            </p>
          </div>
          <div className="timer-actions">
            <div className={`timer-clock ${timedChallenge.status}`}>
              <span>{formatSeconds(timedChallenge.remainingSeconds)}</span>
            </div>
            {!timedChallenge.enabled ? (
              <button type="button" className="secondary-button" onClick={onEnableTimedMode}>
                Use Timed Mode
              </button>
            ) : null}
            {timedChallenge.enabled && timedChallenge.status === "ready" ? (
              <>
                <button type="button" onClick={onStartTimedMode}>
                  Start Timer
                </button>
                <button type="button" className="ghost-button" onClick={onDisableTimedMode}>
                  Cancel Timer
                </button>
              </>
            ) : null}
            {timedChallenge.enabled && timedChallenge.status === "running" ? (
              <button type="button" className="ghost-button" onClick={onDisableTimedMode}>
                Stop Timed Mode
              </button>
            ) : null}
            {timedChallenge.status === "expired" ? (
              <button type="button" className="secondary-button" onClick={onDisableTimedMode}>
                Clear Expired Timer
              </button>
            ) : null}
          </div>
        </section>
        <div className="editor-frame">
          <Editor
            defaultLanguage="python"
            language="python"
            value={code}
            onChange={(value) => setCode(value || "")}
            options={editorOptions}
            theme="vs"
            height="420px"
          />
        </div>
        <div className="editor-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onRun}
            disabled={Boolean(submissionState.loadingAction) || ["expired", "expiring"].includes(timedChallenge.status)}
          >
            {submissionState.loadingAction === "Run" ? "Running..." : "Run"}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={Boolean(submissionState.loadingAction) || ["expired", "expiring"].includes(timedChallenge.status)}
          >
            {submissionState.loadingAction === "Submit" ? "Submitting..." : "Submit"}
          </button>
          <button type="button" className="ghost-button" onClick={() => setCode(demoSolution)}>
            Load Demo Pass
          </button>
        </div>
        {timedChallenge.message ? <p className="success-text">{timedChallenge.message}</p> : null}
        {timedChallenge.status === "expiring" ? (
          <p className="meta-copy">Auto-submitting your timed attempt now.</p>
        ) : null}
        {timedChallenge.status === "expired" ? (
          <p className="error-text">Time expired. Your current code was submitted automatically, and further submissions are locked until you clear timed mode.</p>
        ) : null}
        {submissionState.error ? <p className="error-text">{submissionState.error}</p> : null}
        {submissionState.result ? (
          <div className={submissionState.result.result === "Pass" ? "result-card pass" : "result-card fail"}>
            <h3>{submissionState.result.result}</h3>
            <p>{submissionState.result.feedback}</p>
            <div className="result-grid">
              <span>Last Action: {submissionState.result.execution_type}</span>
              <span>Failure Category: {submissionState.result.failure_category || "None"}</span>
              <span>Runtime: {submissionState.result.runtime_ms} ms</span>
              <span>Highest Hint Type: {HINT_TYPE_LABELS[submissionState.result.hint_stage_unlocked] || "None"}</span>
              <span>Valid Failed Attempts: {submissionState.result.valid_failed_attempts}</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="panel hints-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Feedback</p>
            <h2>Hints</h2>
          </div>
        </div>
        {hintState.error ? <p className="error-text">{hintState.error}</p> : null}
        <HintCard title="Conceptual" stage={1} hintState={hintState} onUnlockHint={onUnlockHint} />
        <HintCard title="Strategic" stage={2} hintState={hintState} onUnlockHint={onUnlockHint} />
        <HintCard title="Syntactic" stage={3} hintState={hintState} onUnlockHint={onUnlockHint} />
        <AnswerKeyCard answerKeyState={answerKeyState} onViewAnswerKey={onViewAnswerKey} />
      </div>
    </section>
  );
}

function HintCard({ title, stage, hintState, onUnlockHint }) {
  const hints = hintState.hints || {};
  const stageKey = stage === 1 ? "conceptual" : stage === 2 ? "strategic" : "syntactic";
  const content = hints[stageKey];
  const unlockedStages = hints.unlocked_stages || [];
  const isUnlocked = unlockedStages.includes(stage);
  const isHighlighted = isUnlocked && hints.highlight_stage === stage;
  const isLoading = hintState.loadingStage === stage;

  return (
    <article className={["hint-card", content ? "unlocked" : "locked", isHighlighted ? "highlighted" : ""].join(" ").trim()}>
      <h3>{title}</h3>
      <p>
        {content
          ? content
          : isUnlocked
            ? "This hint is unlocked and ready. Reveal it when you want more guidance."
            : "Locked until you earn this hint type."}
      </p>
      {isUnlocked && !content ? (
        <button type="button" className="secondary-button" onClick={() => onUnlockHint(stage)} disabled={isLoading}>
          {isLoading ? "Unlocking..." : "Unlock Hint"}
        </button>
      ) : null}
    </article>
  );
}

function AnswerKeyCard({ answerKeyState, onViewAnswerKey }) {
  const isUnlocked = answerKeyState.unlocked;
  const hasContent = Boolean(answerKeyState.content);

  return (
    <article className={["hint-card", hasContent ? "unlocked" : "locked", isUnlocked ? "highlighted" : ""].join(" ").trim()}>
      <h3>Answer Key</h3>
      {hasContent ? (
        <>
          <p>{answerKeyState.content.explanation}</p>
          <div className="editor-frame answer-key-frame">
            <Editor
              defaultLanguage="python"
              language="python"
              value={answerKeyState.content.solution_code}
              options={{
                automaticLayout: true,
                fontSize: 14,
                lineNumbers: "on",
                minimap: { enabled: false },
                readOnly: true,
                renderLineHighlight: "none",
                scrollBeyondLastLine: false,
                wordWrap: "on",
              }}
              theme="vs"
              height="200px"
            />
          </div>
        </>
      ) : (
        <p>
          {isUnlocked
            ? "You have earned the answer key for this problem. Reveal it when you are ready to compare your work."
            : "Locked until you reach three valid failed Submit attempts on this problem."}
        </p>
      )}
      {answerKeyState.error ? <p className="error-text">{answerKeyState.error}</p> : null}
      {isUnlocked && !hasContent ? (
        <button type="button" className="secondary-button" onClick={onViewAnswerKey} disabled={answerKeyState.loading}>
          {answerKeyState.loading ? "Loading..." : "View Answer Key"}
        </button>
      ) : null}
    </article>
  );
}

function AuthorPanel({
  authorProblems,
  authorFilter,
  onAuthorFilterChange,
  authorEditor,
  onAuthorEditorChange,
  onLoadJsonFile,
  onUploadJsonFile,
  onCreateNew,
  onSelectProblem,
  onUpload,
  onSave,
  onDisable,
  onEnable,
  onDelete,
}) {
  const loadFileInputRef = useRef(null);
  const uploadFileInputRef = useRef(null);
  const authorEditorOptions = {
    automaticLayout: true,
    fontSize: 14,
    formatOnPaste: true,
    lineNumbers: "on",
    minimap: { enabled: false },
    padding: { top: 16, bottom: 16 },
    renderLineHighlight: "all",
    scrollBeyondLastLine: false,
    tabSize: 2,
    wordWrap: "on",
  };

  return (
    <section className="author-layout">
      <section className="panel author-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Author Dashboard</p>
            <h2>Manage problem library</h2>
          </div>
          <button type="button" className="secondary-button" onClick={onCreateNew}>
            New Upload Draft
          </button>
        </div>
        <div className="author-filter-row" role="tablist" aria-label="Author problem filters">
          {AUTHOR_FILTERS.map((filterItem) => (
            <button
              key={filterItem.id}
              type="button"
              className={authorFilter === filterItem.id ? "difficulty-chip active" : "difficulty-chip"}
              onClick={() => onAuthorFilterChange(filterItem.id)}
              role="tab"
              aria-selected={authorFilter === filterItem.id}
            >
              {filterItem.label}
            </button>
          ))}
        </div>
        <div className="problem-items">
          {authorProblems.map((problem) => (
            <article key={problem.problem_id} className="author-problem-card">
              <div className="author-problem-copy">
                <strong>{problem.title}</strong>
                <span>{problem.problem_id}</span>
                <div className="author-problem-meta">
                  <span className={`source-pill ${problem.source}`}>{problem.source}</span>
                  <span className={problem.is_active ? "status-pill active" : "status-pill inactive"}>
                    {problem.is_active ? "Active" : "Disabled"}
                  </span>
                </div>
              </div>
              <div className="author-problem-actions">
                {problem.can_edit ? (
                  <button type="button" className="secondary-button" onClick={() => onSelectProblem(problem.problem_id)}>
                    Edit JSON
                  </button>
                ) : null}
                {problem.can_disable ? (
                  problem.is_active ? (
                    <button type="button" className="ghost-button" onClick={() => onDisable(problem.problem_id)}>
                      Disable
                    </button>
                  ) : (
                    <button type="button" className="ghost-button" onClick={() => onEnable(problem.problem_id)}>
                      Enable
                    </button>
                  )
                ) : null}
                {problem.can_delete ? (
                  <button type="button" className="danger-button" onClick={() => onDelete(problem.problem_id)}>
                    Delete
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel author-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">JSON Workspace</p>
            <h2>{authorEditor.mode === "edit" ? `Editing ${authorEditor.problemId}` : "Upload one problem JSON file"}</h2>
          </div>
        </div>
        <p className="prompt-copy">
          Upload a `.json` file or edit the payload directly. Starter problems stay read-only; only your own custom problems can be edited, disabled, or deleted.
        </p>
        <div className="author-toolbar">
          <button
            type="button"
            className="secondary-button"
            onClick={() => loadFileInputRef.current?.click()}
          >
            Load JSON Into Editor
          </button>
          <input
            ref={loadFileInputRef}
            className="sr-only-input"
            type="file"
            accept="application/json,.json"
            onChange={onLoadJsonFile}
            aria-label="Load a JSON problem file into the editor"
          />
          <button
            type="button"
            className="secondary-button"
            onClick={() => uploadFileInputRef.current?.click()}
          >
            Upload JSON File
          </button>
          <input
            ref={uploadFileInputRef}
            className="sr-only-input"
            type="file"
            accept="application/json,.json"
            onChange={onUploadJsonFile}
            aria-label="Upload a JSON problem file directly"
          />
          <button type="button" className="secondary-button" onClick={onCreateNew}>
            Reset Draft
          </button>
        </div>
        <div className="editor-frame author-editor-frame">
          <Editor
            defaultLanguage="json"
            language="json"
            value={authorEditor.jsonText}
            onChange={(value) => onAuthorEditorChange(value || "")}
            options={authorEditorOptions}
            theme="vs"
            height="360px"
          />
        </div>
        <div className="editor-actions">
          {authorEditor.mode === "edit" ? (
            <button type="button" onClick={onSave} disabled={authorEditor.loading}>
              {authorEditor.loading ? "Saving..." : "Save Changes"}
            </button>
          ) : (
            <button type="button" onClick={onUpload} disabled={authorEditor.loading}>
              {authorEditor.loading ? "Uploading..." : "Upload Problem"}
            </button>
          )}
        </div>
        {authorEditor.message ? <p className="success-text" aria-live="polite">{authorEditor.message}</p> : null}
        {authorEditor.error ? <p className="error-text" aria-live="assertive">{authorEditor.error}</p> : null}
      </section>
    </section>
  );
}

function loadGoogleScriptOnce() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve();
      return;
    }

    const existing = document.querySelector('script[data-google-identity="true"]');
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Google sign-in failed to load.")), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Google sign-in failed to load."));
    document.head.appendChild(script);
  });
}

export default function App() {
  const [session, setSession] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [googleConfig, setGoogleConfig] = useState({ enabled: false, client_id: "" });
  const [problems, setProblems] = useState([]);
  const [selectedDifficulty, setSelectedDifficulty] = useState("Easy");
  const [selectedProblemId, setSelectedProblemId] = useState("");
  const [codeByProblem, setCodeByProblem] = useState({});
  const [submissionState, setSubmissionState] = useState({ loadingAction: null, result: null, error: "" });
  const [hintState, setHintState] = useState({ loadingStage: null, hints: null, error: "" });
  const [answerKeyState, setAnswerKeyState] = useState({ unlocked: false, loading: false, content: null, error: "" });
  const [timedChallengeByProblem, setTimedChallengeByProblem] = useState({});
  const [authorFilter, setAuthorFilter] = useState("all");
  const [authorProblems, setAuthorProblems] = useState([]);
  const [authorEditor, setAuthorEditor] = useState({
    mode: "create",
    problemId: "",
    jsonText: starterUploadTemplate,
    loading: false,
    message: "",
    error: "",
  });
  const sessionRef = useRef(session);
  const codeByProblemRef = useRef(codeByProblem);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    codeByProblemRef.current = codeByProblem;
  }, [codeByProblem]);

  useEffect(() => {
    if (!session?.user_id || typeof window === "undefined") {
      return;
    }

    try {
      const raw = window.localStorage.getItem(getWorkspaceStorageKey(session.user_id));
      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw);
      if (parsed.codeByProblem && typeof parsed.codeByProblem === "object") {
        setCodeByProblem((current) => ({ ...parsed.codeByProblem, ...current }));
      }

      if (parsed.timedChallengeByProblem && typeof parsed.timedChallengeByProblem === "object") {
        const now = Date.now();
        const restoredTimers = Object.fromEntries(
          Object.entries(parsed.timedChallengeByProblem).map(([problemId, challenge]) => {
            if (!challenge || typeof challenge !== "object") {
              return [problemId, challenge];
            }

            if (challenge.status === "running" && challenge.expiresAt) {
              const remainingSeconds = Math.max(0, Math.ceil((challenge.expiresAt - now) / 1000));
              return [
                problemId,
                {
                  ...challenge,
                  remainingSeconds,
                  status: remainingSeconds === 0 ? "expiring" : "running",
                },
              ];
            }

            return [problemId, challenge];
          }),
        );
        setTimedChallengeByProblem(restoredTimers);
      }
    } catch (_error) {
      // Ignore invalid persisted workspace state and continue with in-memory defaults.
    }
  }, [session?.user_id]);

  useEffect(() => {
    if (!session?.user_id || typeof window === "undefined") {
      return;
    }

    const payload = JSON.stringify({
      codeByProblem,
      timedChallengeByProblem,
    });
    window.localStorage.setItem(getWorkspaceStorageKey(session.user_id), payload);
  }, [session?.user_id, codeByProblem, timedChallengeByProblem]);

  useEffect(() => {
    let isActive = true;

    async function bootstrap() {
      try {
        const config = await getGoogleConfig();
        if (!isActive) {
          return;
        }
        setGoogleConfig(config);
        if (config.enabled) {
          await loadGoogleScriptOnce();
        }
      } catch (_error) {
        if (isActive) {
          setGoogleConfig({ enabled: false, client_id: "" });
        }
      }
    }

    bootstrap();
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    let isActive = true;

    async function restoreSession() {
      try {
        const response = await getSession();
        if (isActive) {
          setSession(response);
        }
      } catch (_error) {
        if (isActive) {
          setSession(null);
        }
      } finally {
        if (isActive) {
          setSessionLoading(false);
        }
      }
    }

    restoreSession();
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    if (!session) {
      return;
    }

    let isActive = true;

    async function loadProblemsForDifficulty() {
      try {
        const response = await getProblems(selectedDifficulty);
        if (!isActive) {
          return;
        }
        setProblems(response.problems);
        if (response.problems.length > 0) {
          const firstProblem = response.problems[0];
          setSelectedProblemId((current) => (
            response.problems.some((problem) => problem.problem_id === current) ? current : firstProblem.problem_id
          ));
          setCodeByProblem((current) => {
            const next = { ...current };
            response.problems.forEach((problem) => {
              if (next[problem.problem_id] === undefined) {
                next[problem.problem_id] = problem.starter_code || "";
              }
            });
            return next;
          });
        } else {
          setSelectedProblemId("");
        }
      } catch (loadError) {
        if (isActive) {
          setAuthError(loadError.message);
        }
      }
    }

    loadProblemsForDifficulty();
    return () => {
      isActive = false;
    };
  }, [session, selectedDifficulty]);

  useEffect(() => {
    if (!session || session.role !== "Author") {
      return;
    }

    let isActive = true;

    async function loadAuthorProblems() {
      try {
        const response = await getAuthorProblems(authorFilter, false);
        if (isActive) {
          setAuthorProblems(response.problems);
        }
      } catch (_error) {
        if (isActive) {
          setAuthorProblems([]);
        }
      }
    }

    loadAuthorProblems();
    return () => {
      isActive = false;
    };
  }, [session, authorFilter]);

  const selectedProblem = problems.find((problem) => problem.problem_id === selectedProblemId) || null;
  const currentCode = selectedProblem ? codeByProblem[selectedProblem.problem_id] || "" : "";
  const selectedTimedChallenge = selectedProblem
    ? timedChallengeByProblem[selectedProblem.problem_id] || {
        enabled: false,
        status: "off",
        remainingSeconds: TIME_LIMITS[selectedProblem.difficulty] || TIME_LIMITS.Easy,
        limitSeconds: TIME_LIMITS[selectedProblem.difficulty] || TIME_LIMITS.Easy,
        message: "",
      }
    : null;

  useEffect(() => {
    if (!selectedProblem || !session) {
      return;
    }
    refreshHintState(selectedProblem.problem_id);
    refreshAnswerKeyState(selectedProblem.problem_id);
  }, [selectedProblemId, session]);

  useEffect(() => {
    const hasRunningTimer = Object.values(timedChallengeByProblem).some((challenge) => challenge.status === "running");
    if (!hasRunningTimer) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      const expiredProblemIds = [];
      const now = Date.now();
      setTimedChallengeByProblem((current) => {
        const next = { ...current };
        Object.entries(current).forEach(([problemId, challenge]) => {
          if (challenge.status !== "running") {
            return;
          }
          const nextRemaining = challenge.expiresAt
            ? Math.max(0, Math.ceil((challenge.expiresAt - now) / 1000))
            : Math.max(0, challenge.remainingSeconds - 1);
          next[problemId] = {
            ...challenge,
            remainingSeconds: nextRemaining,
          };
          if (nextRemaining === 0) {
            next[problemId] = {
              ...next[problemId],
              status: "expiring",
            };
            expiredProblemIds.push(problemId);
          }
        });
        return next;
      });

      expiredProblemIds.forEach((problemId) => {
        autoSubmitTimedChallenge(problemId);
      });
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [timedChallengeByProblem]);

  useEffect(() => {
    const expiringProblemIds = Object.entries(timedChallengeByProblem)
      .filter(([, challenge]) => challenge.status === "expiring")
      .map(([problemId]) => problemId);

    if (expiringProblemIds.length === 0) {
      return;
    }

    expiringProblemIds.forEach((problemId) => {
      autoSubmitTimedChallenge(problemId);
    });
  }, [timedChallengeByProblem]);

  function updateCode(nextCode) {
    if (!selectedProblem) {
      return;
    }
    setCodeByProblem((current) => ({
      ...current,
      [selectedProblem.problem_id]: nextCode,
    }));
  }

  function buildTimedChallenge(problem, overrides = {}) {
    const limitSeconds = TIME_LIMITS[problem.difficulty] || TIME_LIMITS.Easy;
    return {
      enabled: false,
      status: "off",
      remainingSeconds: limitSeconds,
      limitSeconds,
      message: "",
      startedAt: null,
      expiresAt: null,
      ...overrides,
    };
  }

  function resetAuthorEditor(nextJson = starterUploadTemplate) {
    setAuthorEditor({
      mode: "create",
      problemId: "",
      jsonText: nextJson,
      loading: false,
      message: "",
      error: "",
    });
  }

  async function refreshProblemCollections() {
    const response = await getProblems(selectedDifficulty);
    setProblems(response.problems);
    if (session?.role === "Author") {
      const authorResponse = await getAuthorProblems(authorFilter, false);
      setAuthorProblems(authorResponse.problems);
    }
  }

  function setTimedChallenge(problemId, updater) {
    setTimedChallengeByProblem((current) => {
      const currentChallenge = current[problemId];
      const nextChallenge = typeof updater === "function" ? updater(currentChallenge) : updater;
      return {
        ...current,
        [problemId]: nextChallenge,
      };
    });
  }

  async function handleLogin(credentials) {
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = await login(credentials);
      setSession(response);
    } catch (loginError) {
      setAuthError(loginError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleRegister(credentials) {
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = await register(credentials);
      setSession(response);
    } catch (registerError) {
      setAuthError(registerError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleGoogleCredential(credential) {
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = await googleAuth(credential);
      setSession(response);
    } catch (googleError) {
      setAuthError(googleError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function refreshHintState(problemId) {
    try {
      const response = await getHints(problemId);
      setHintState({ loadingStage: null, hints: response, error: "" });
    } catch (hintError) {
      if (String(hintError.message).includes("No hints unlocked yet")) {
        setHintState({
          loadingStage: null,
          hints: {
            problem_id: problemId,
            unlocked_stage: 0,
            unlocked_stages: [],
            highlight_stage: null,
            conceptual: null,
            strategic: null,
            syntactic: null,
          },
          error: "",
        });
        return;
      }
      setHintState({ loadingStage: null, hints: null, error: hintError.message });
    }
  }

  async function refreshAnswerKeyState(problemId) {
    try {
      const response = await getAnswerKey(problemId);
      setAnswerKeyState({
        unlocked: response.unlocked,
        loading: false,
        content: response.unlocked ? response : null,
        error: "",
      });
    } catch (answerKeyError) {
      setAnswerKeyState({ unlocked: false, loading: false, content: null, error: answerKeyError.message });
    }
  }

  async function executeCode(action, options = {}) {
    const { forcedProblemId = null, timedMode = false, autoTriggered = false } = options;
    const activeSession = sessionRef.current;
    const problemId = forcedProblemId || selectedProblem?.problem_id;
    if (!problemId || !activeSession) {
      return;
    }
    const code = codeByProblemRef.current[problemId] || "";
    const isSelectedProblem = selectedProblem?.problem_id === problemId;

    if (isSelectedProblem) {
      setSubmissionState({ loadingAction: action, result: null, error: "" });
      if (action === "Submit") {
        setHintState({ loadingStage: null, hints: null, error: "" });
        setAnswerKeyState((current) => ({ ...current, error: "" }));
      }
    }

    try {
      const response = await (action === "Run"
        ? runCode({ problem_id: problemId, code, timed_mode: timedMode })
        : submitCode({ problem_id: problemId, code, timed_mode: timedMode }));
      if (isSelectedProblem) {
        setSubmissionState({ loadingAction: null, result: response, error: "" });
      }
      if (action === "Submit" && isSelectedProblem) {
        await refreshHintState(problemId);
        await refreshAnswerKeyState(problemId);
      }
      if (timedMode && response.result === "Pass") {
        setTimedChallenge(problemId, (current) => ({
          ...(current || buildTimedChallenge(selectedProblem || { difficulty: "Easy" })),
          enabled: false,
          status: "completed",
          message: autoTriggered ? "Timed submission finished successfully." : "Timed challenge passed before the clock ran out.",
          expiresAt: null,
          startedAt: null,
        }));
      } else if (timedMode) {
        setTimedChallenge(problemId, (current) => ({
          ...(current || buildTimedChallenge(selectedProblem || { difficulty: "Easy" })),
          enabled: false,
          status: autoTriggered ? "expired" : "ready",
          message: autoTriggered ? "Time expired and your latest code was submitted automatically." : "",
          expiresAt: null,
          startedAt: null,
        }));
      }
    } catch (submitError) {
      if (isSelectedProblem) {
        setSubmissionState({ loadingAction: null, result: null, error: submitError.message });
      }
      if (timedMode) {
        setTimedChallenge(problemId, (current) => ({
          ...(current || buildTimedChallenge(selectedProblem || { difficulty: "Easy" })),
          enabled: false,
          status: "expired",
          message: "",
          expiresAt: null,
          startedAt: null,
        }));
      }
    }
  }

  async function autoSubmitTimedChallenge(problemId) {
    await executeCode("Submit", {
      forcedProblemId: problemId,
      timedMode: true,
      autoTriggered: true,
    });
  }

  async function handleUnlockHint(stage) {
    if (!selectedProblem || !session) {
      return;
    }

    setHintState((current) => ({ loadingStage: stage, hints: current.hints, error: "" }));
    try {
      const response = await getHints(selectedProblem.problem_id, stage);
      setHintState({ loadingStage: null, hints: response, error: "" });
    } catch (hintError) {
      setHintState((current) => ({ loadingStage: null, hints: current.hints, error: hintError.message }));
    }
  }

  async function handleResetProgress() {
    if (!selectedProblem || !session) {
      return;
    }
    try {
      await resetProgress(selectedProblem.problem_id);
      setCodeByProblem((current) => ({ ...current, [selectedProblem.problem_id]: selectedProblem.starter_code || "" }));
      setSubmissionState({ loadingAction: null, result: null, error: "" });
      setHintState({
        loadingStage: null,
        hints: {
          problem_id: selectedProblem.problem_id,
          unlocked_stage: 0,
          unlocked_stages: [],
          highlight_stage: null,
          conceptual: null,
          strategic: null,
          syntactic: null,
        },
        error: "",
      });
      setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
      setTimedChallenge(selectedProblem.problem_id, buildTimedChallenge(selectedProblem));
    } catch (resetError) {
      setHintState((current) => ({ loadingStage: null, hints: current.hints, error: resetError.message }));
    }
  }

  function handleEnableTimedMode() {
    if (!selectedProblem) {
      return;
    }
    setTimedChallenge(selectedProblem.problem_id, buildTimedChallenge(selectedProblem, {
      enabled: true,
      status: "ready",
      message: "",
    }));
  }

  function handleDisableTimedMode() {
    if (!selectedProblem) {
      return;
    }
    setTimedChallenge(selectedProblem.problem_id, buildTimedChallenge(selectedProblem));
  }

  function handleStartTimedMode() {
    if (!selectedProblem) {
      return;
    }
    const startedAt = Date.now();
    const limitSeconds = TIME_LIMITS[selectedProblem.difficulty] || TIME_LIMITS.Easy;
    setTimedChallenge(selectedProblem.problem_id, buildTimedChallenge(selectedProblem, {
      enabled: true,
      status: "running",
      remainingSeconds: limitSeconds,
      limitSeconds,
      message: "",
      startedAt,
      expiresAt: startedAt + (limitSeconds * 1000),
    }));
  }

  async function handleViewAnswerKey() {
    if (!selectedProblem || !session) {
      return;
    }
    setAnswerKeyState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const response = await getAnswerKey(selectedProblem.problem_id);
      setAnswerKeyState({ unlocked: response.unlocked, loading: false, content: response.unlocked ? response : null, error: "" });
    } catch (answerKeyError) {
      setAnswerKeyState((current) => ({ ...current, loading: false, error: answerKeyError.message }));
    }
  }

  async function handleLoadAuthorProblem(problemId) {
    setAuthorEditor((current) => ({ ...current, loading: true, message: "", error: "" }));
    try {
      const payload = await getAuthorProblem(problemId);
      setAuthorEditor({
        mode: "edit",
        problemId,
        jsonText: JSON.stringify(payload, null, 2),
        loading: false,
        message: `Loaded ${problemId} for editing.`,
        error: "",
      });
    } catch (loadError) {
      setAuthorEditor((current) => ({ ...current, loading: false, error: loadError.message }));
    }
  }

  function handleAuthorFileLoad(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const fileText = typeof reader.result === "string" ? reader.result : "";
      resetAuthorEditor(fileText || starterUploadTemplate);
    };
    reader.onerror = () => {
      setAuthorEditor((current) => ({ ...current, error: "The selected JSON file could not be read." }));
    };
    reader.readAsText(file);
    event.target.value = "";
  }

  async function handleAuthorFileUpload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    setAuthorEditor((current) => ({ ...current, loading: true, message: "", error: "" }));
    try {
      const response = await uploadProblemFile(file);
      await refreshProblemCollections();
      setAuthorEditor((current) => ({
        ...current,
        mode: "edit",
        problemId: response.problem_id,
        loading: false,
        message: `Uploaded ${response.problem_id} from file successfully.`,
        error: "",
      }));
    } catch (uploadError) {
      setAuthorEditor((current) => ({ ...current, loading: false, error: uploadError.message }));
    }
  }

  async function handleAuthorUpload() {
    setAuthorEditor((current) => ({ ...current, loading: true, message: "", error: "" }));
    try {
      const payload = JSON.parse(authorEditor.jsonText);
      const response = await uploadProblem(payload);
      await refreshProblemCollections();
      setAuthorEditor({
        mode: "edit",
        problemId: response.problem_id,
        jsonText: JSON.stringify(payload, null, 2),
        loading: false,
        message: `Uploaded ${response.problem_id} successfully.`,
        error: "",
      });
    } catch (uploadError) {
      setAuthorEditor((current) => ({ ...current, loading: false, error: uploadError.message }));
    }
  }

  async function handleAuthorSave() {
    setAuthorEditor((current) => ({ ...current, loading: true, message: "", error: "" }));
    try {
      const payload = JSON.parse(authorEditor.jsonText);
      await updateProblem(authorEditor.problemId, payload);
      await refreshProblemCollections();
      setAuthorEditor((current) => ({ ...current, loading: false, message: `Saved ${authorEditor.problemId}.`, error: "" }));
    } catch (saveError) {
      setAuthorEditor((current) => ({ ...current, loading: false, error: saveError.message }));
    }
  }

  async function handleAuthorToggle(problemId, action) {
    try {
      if (action === "disable") {
        await disableProblem(problemId);
      } else {
        await enableProblem(problemId);
      }
      await refreshProblemCollections();
    } catch (toggleError) {
      setAuthorEditor((current) => ({ ...current, error: toggleError.message }));
    }
  }

  async function handleAuthorDelete(problemId) {
    try {
      await deleteProblem(problemId);
      await refreshProblemCollections();
      if (authorEditor.problemId === problemId) {
        resetAuthorEditor();
      }
    } catch (deleteError) {
      setAuthorEditor((current) => ({ ...current, error: deleteError.message }));
    }
  }

  async function handleLogout() {
    try {
      await logout();
    } catch (_error) {
      // Client state should still be cleared if the cookie is already gone.
    }
    setSession(null);
    setProblems([]);
    setSelectedProblemId("");
    setCodeByProblem({});
    setTimedChallengeByProblem({});
    setSubmissionState({ loadingAction: null, result: null, error: "" });
    setHintState({ loadingStage: null, hints: null, error: "" });
    setAnswerKeyState({ unlocked: false, loading: false, content: null, error: "" });
    setAuthorProblems([]);
    resetAuthorEditor();
    setAuthError("");
  }

  if (sessionLoading) {
    return (
      <main className="app-shell auth-shell">
        <section className="auth-card">
          <p className="eyebrow">CodeSoCrat</p>
          <h1>Restoring session</h1>
          <p className="lede">Checking your secure session cookie.</p>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="app-shell auth-shell">
        <AuthPanel
          onLogin={handleLogin}
          onRegister={handleRegister}
          onGoogleCredential={handleGoogleCredential}
          googleConfig={googleConfig}
          loading={authLoading}
          error={authError}
        />
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Logged In</p>
          <h1>CodeSoCrat Workspace</h1>
          <p className="meta-copy">{session.display_name || session.email}</p>
        </div>
        <div className="topbar-actions">
          <span>{session.role}</span>
          <span className="auth-provider-pill">{session.auth_provider}</span>
          <button type="button" className="secondary-button" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      <section className="dashboard">
        <ProblemList
          problems={problems}
          selectedDifficulty={selectedDifficulty}
          selectedProblemId={selectedProblemId}
          onDifficultyChange={setSelectedDifficulty}
          onSelect={setSelectedProblemId}
        />
        <SubmissionPanel
          problem={selectedProblem}
          code={currentCode}
          setCode={updateCode}
          onRun={() => executeCode("Run", { timedMode: selectedTimedChallenge?.status === "running" })}
          onSubmit={() => executeCode("Submit", { timedMode: selectedTimedChallenge?.status === "running" })}
          onResetProgress={handleResetProgress}
          timedChallenge={selectedTimedChallenge}
          onEnableTimedMode={handleEnableTimedMode}
          onDisableTimedMode={handleDisableTimedMode}
          onStartTimedMode={handleStartTimedMode}
          submissionState={submissionState}
          hintState={hintState}
          answerKeyState={answerKeyState}
          onViewAnswerKey={handleViewAnswerKey}
          onUnlockHint={handleUnlockHint}
        />
      </section>

      {session.role === "Author" ? (
        <AuthorPanel
          authorProblems={authorProblems}
          authorFilter={authorFilter}
          onAuthorFilterChange={setAuthorFilter}
          authorEditor={authorEditor}
          onAuthorEditorChange={(jsonText) => setAuthorEditor((current) => ({ ...current, jsonText, message: "", error: "" }))}
          onLoadJsonFile={handleAuthorFileLoad}
          onUploadJsonFile={handleAuthorFileUpload}
          onCreateNew={() => resetAuthorEditor()}
          onSelectProblem={handleLoadAuthorProblem}
          onUpload={handleAuthorUpload}
          onSave={handleAuthorSave}
          onDisable={(problemId) => handleAuthorToggle(problemId, "disable")}
          onEnable={(problemId) => handleAuthorToggle(problemId, "enable")}
          onDelete={handleAuthorDelete}
        />
      ) : null}
    </main>
  );
}
