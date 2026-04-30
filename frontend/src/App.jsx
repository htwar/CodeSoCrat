import Editor from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import {
  clearTimedMode,
  deleteProblem,
  disableProblem,
  enableProblem,
  enableTimedMode,
  getAnswerKey,
  getAuthorProblem,
  getAuthorProblems,
  getGoogleConfig,
  getHints,
  getProblemProgress,
  getProblems,
  getSession,
  googleAuth,
  login,
  logout,
  pauseTimedMode,
  register,
  resetProgress,
  resumeTimedMode,
  runCode,
  startTimedMode,
  submitCode,
  submitExpiredTimedCode,
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

const DIFFICULTIES = ["Easy", "Medium", "Hard"];
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
const HINT_TYPE_SUMMARIES = {
  1: "Focus on the main idea behind the problem before changing code.",
  2: "Use this to choose your next debugging or problem-solving step.",
  3: "Use this to inspect the code shape, syntax, or exact failing area.",
};
const DEMO_ACCOUNTS = [
  {
    label: "Student demo",
    email: import.meta.env.VITE_DEMO_STUDENT_EMAIL || "",
    password: import.meta.env.VITE_DEMO_STUDENT_PASSWORD || "",
  },
  {
    label: "Author demo",
    email: import.meta.env.VITE_DEMO_AUTHOR_EMAIL || "",
    password: import.meta.env.VITE_DEMO_AUTHOR_PASSWORD || "",
  },
].filter((account) => account.email && account.password);
const WORKSPACE_STORAGE_PREFIX = "codesocrat_workspace_v1";

function formatSeconds(totalSeconds) {
  // Convert raw countdown seconds into an MM:SS string for the timer UI.
  // Convert raw countdown seconds into an MM:SS string for the timer UI.
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function getWorkspaceStorageKey(userId) {
  // Keep each signed-in user's saved editor/timer state isolated in localStorage.
  // Keep each signed-in user's saved editor/timer state isolated in localStorage.
  return `${WORKSPACE_STORAGE_PREFIX}:${userId}`;
}

function getExpectedTimeLimit(problem) {
  const timeLimits = {
    Easy: Number(import.meta.env.VITE_TIMED_MODE_EASY_SECONDS || 60),
    Medium: Number(import.meta.env.VITE_TIMED_MODE_MEDIUM_SECONDS || 180),
    Hard: Number(import.meta.env.VITE_TIMED_MODE_HARD_SECONDS || 300),
  };
  return Math.max(1, timeLimits[problem?.difficulty] || timeLimits.Easy);
}

function normalizeHintLines(content) {
  if (!content) {
    return [];
  }

  return content
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) => {
      const normalizedLine = line.replace(/^[*-]\s*/, "").trim();
      return normalizedLine
        .split(/\s+-\s+/)
        .map((segment) => segment.trim())
        .filter(Boolean);
    });
}

function formatCodeLines(code) {
  if (!code) {
    return [];
  }
  return code.split("\n");
}

function AuthPanel({ onLogin, onRegister, onGoogleCredential, googleConfig, loading, error }) {
  // Authentication screen shared by local login, registration, and optional
  // Google sign-in.
  // Authentication screen shared by local login, registration, and optional
  // Google sign-in.
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    // Submit either login or registration based on the active auth tab.
    // Submit either login or registration based on the active auth tab.
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
          id="auth-tab-login"
          className={mode === "login" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("login")}
          role="tab"
          aria-selected={mode === "login"}
          aria-controls="auth-form-panel"
          tabIndex={mode === "login" ? 0 : -1}
        >
          Sign in
        </button>
        <button
          type="button"
          id="auth-tab-register"
          className={mode === "register" ? "toggle-button active" : "toggle-button"}
          onClick={() => setMode("register")}
          role="tab"
          aria-selected={mode === "register"}
          aria-controls="auth-form-panel"
          tabIndex={mode === "register" ? 0 : -1}
        >
          Create account
        </button>
      </div>
      <form className="auth-form" id="auth-form-panel" onSubmit={handleSubmit}>
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
      <p className="status-text" role="status" aria-live="polite">
        {error || ""}
      </p>
      {DEMO_ACCOUNTS.length ? (
        <div className="account-hints" aria-label="Demo accounts">
          {DEMO_ACCOUNTS.map((account) => (
            <span key={account.label}>{account.label}: {account.email} / {account.password}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ProblemList({ problems, selectedDifficulty, selectedProblemId, onDifficultyChange, onSelect }) {
  // Left-hand catalog used to switch between available coding problems.
  return (
    <aside className="panel problem-list" aria-labelledby="problem-list-title">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Problem Set</p>
          <h2 id="problem-list-title">Choose a challenge</h2>
        </div>
      </div>
      <div className="difficulty-picker" role="tablist" aria-label="Difficulty levels">
        {DIFFICULTIES.map((difficulty) => (
          <button
            key={difficulty}
            type="button"
            id={`difficulty-tab-${difficulty}`}
            className={selectedDifficulty === difficulty ? "difficulty-chip active" : "difficulty-chip"}
            onClick={() => onDifficultyChange(difficulty)}
            role="tab"
            aria-selected={selectedDifficulty === difficulty}
            aria-controls="workspace-panel"
            tabIndex={selectedDifficulty === difficulty ? 0 : -1}
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
            aria-pressed={selectedProblemId === problem.problem_id}
            aria-label={`${problem.title}, ${problem.difficulty}, ${problem.source === "starter" ? "starter problem" : "custom problem"}`}
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
  onEditorChange,
  onRun,
  onSubmit,
  onResetProgress,
  timedChallenge,
  onEnableTimedMode,
  onDisableTimedMode,
  submissionState,
  hintState,
  answerKeyState,
  onViewAnswerKey,
  onUnlockHint,
}) {
  // Main learner workspace: prompt, timer, code editor, run/submit actions,
  // Main learner workspace: prompt, timer, code editor, run/submit actions,
  // and the latest result state.
  const editorOptions = {
    ariaLabel: problem ? `${problem.title} Python editor` : "Python editor",
    automaticLayout: true,
    stickyScroll: { enabled: false },
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
      <div className="panel workspace-panel" id="workspace-panel" tabIndex="-1" aria-labelledby="workspace-problem-title">
        <div className="panel-header">
          <div className="workspace-heading">
            <p className="eyebrow">{problem.difficulty}</p>
            <h2 id="workspace-problem-title">{problem.title}</h2>
            <div className="workspace-meta-row">
              <span className={`source-pill ${problem.source}`}>{problem.source === "starter" ? "Starter Problem" : "Custom Problem"}</span>
              <p className="meta-copy">
                Required function: <code>{problem.function_name}</code>
              </p>
            </div>
          </div>
          <div className="panel-actions">
            <button type="button" className="danger-button" onClick={onResetProgress}>
              Reset Progress
            </button>
          </div>
        </div>
        <p className="prompt-copy">{problem.prompt}</p>
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
        {!timedChallenge.enabled ? (
          <section className="timer-launcher" aria-labelledby="timed-mode-title">
            <div className="timer-launcher-copy">
              <p className="eyebrow">Timed Mode</p>
              <h3 id="timed-mode-title">Want a timed challenge?</h3>
              <p className="meta-copy">
                This {problem.difficulty.toLowerCase()} problem gets {formatSeconds(timedChallenge.limitSeconds)}. Open timed mode when you want a pressure run.
              </p>
            </div>
            <button type="button" className="secondary-button" onClick={onEnableTimedMode}>
              Start Timer
            </button>
          </section>
        ) : (
          <section className={["timer-panel", timedChallenge.status].join(" ").trim()} aria-labelledby="timed-mode-title">
            <div>
              <p className="eyebrow">Timed Mode</p>
              <h3 id="timed-mode-title">
                {timedChallenge.status === "running"
                  ? "Timed challenge in progress"
                  : timedChallenge.status === "paused"
                    ? "Timer paused for hint generation"
                  : timedChallenge.status === "expired"
                    ? "Time is up"
                  : timedChallenge.status === "completed"
                      ? "Timed challenge completed"
                      : "Ready when you start typing"}
              </h3>
              <p className="meta-copy">
                {timedChallenge.status === "completed"
                  ? "You finished the timed challenge. Open it again whenever you want another pressure run."
                  : timedChallenge.status === "paused"
                    ? "The countdown is paused while your hint is being generated. It will resume automatically when the hint is ready."
                  : timedChallenge.status === "ready"
                    ? `The ${formatSeconds(timedChallenge.limitSeconds)} countdown will begin as soon as you start editing in the code editor.`
                  : timedChallenge.status === "expired"
                    ? "The timer has expired. Further runs and submits stay locked until you clear or restart timed mode."
                    : `This ${problem.difficulty.toLowerCase()} problem gets ${formatSeconds(timedChallenge.limitSeconds)}. Keep an eye on the countdown, because timed mode locks once it reaches 00:00.`}
              </p>
            </div>
            <div className="timer-actions">
              <div
                className={`timer-clock ${timedChallenge.status}`}
                role="status"
                aria-live="polite"
                aria-atomic="true"
                aria-label={`Timer status: ${formatSeconds(timedChallenge.remainingSeconds)} remaining`}
              >
                <span>{formatSeconds(timedChallenge.remainingSeconds)}</span>
              </div>
              {timedChallenge.status === "ready" ? (
                <p className="timer-support">The timer starts on your first keystroke.</p>
              ) : null}
              {["running", "paused"].includes(timedChallenge.status) ? (
                <button type="button" className="ghost-button" onClick={onDisableTimedMode}>
                  Stop Timed Mode
                </button>
              ) : null}
              {["ready", "expired", "completed"].includes(timedChallenge.status) ? (
                <button type="button" className="secondary-button" onClick={onDisableTimedMode}>
                  {timedChallenge.status === "ready" ? "Cancel Timer" : "Close Timer"}
                </button>
              ) : null}
            </div>
          </section>
        )}
        <div className="editor-frame">
          <Editor
            defaultLanguage="python"
            language="python"
            value={code}
            onChange={(value) => onEditorChange(value || "")}
            options={editorOptions}
            theme="vs"
            height="420px"
          />
        </div>
        <p className="meta-copy editor-help">
          Keyboard tip: when focus is inside the code editor, press <code>Ctrl+M</code> to toggle whether the <code>Tab</code> key indents code or moves focus to the next control.
        </p>
        <div className="editor-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={onRun}
            disabled={Boolean(submissionState.loadingAction) || ["expired", "paused"].includes(timedChallenge.status)}
          >
            {submissionState.loadingAction === "Run" ? "Running..." : "Run"}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={Boolean(submissionState.loadingAction) || ["expired", "paused"].includes(timedChallenge.status)}
          >
            {submissionState.loadingAction === "Submit" ? "Submitting..." : "Submit"}
          </button>
        </div>
        {timedChallenge.message ? <p className="success-text" role="status" aria-live="polite">{timedChallenge.message}</p> : null}
        {timedChallenge.status === "expired" ? (
          <p className="error-text" role="alert">Time expired. Further runs and submits are locked until you clear timed mode.</p>
        ) : null}
        {timedChallenge.status === "paused" ? (
          <p className="meta-copy" role="status" aria-live="polite">Timed mode is paused while the selected hint loads.</p>
        ) : null}
        {submissionState.error ? <p className="error-text" role="alert">{submissionState.error}</p> : null}
        {submissionState.result ? (
          <div className={submissionState.result.result === "Pass" ? "result-card pass" : "result-card fail"} role="status" aria-live="polite">
            <h3>{submissionState.result.result}</h3>
            <p>{submissionState.result.feedback}</p>
            <div className="result-grid">
              <span>Last Action: {submissionState.result.execution_type}</span>
              <span>Failure Category: {submissionState.result.failure_category || "None"}</span>
              <span>Runtime: {submissionState.result.runtime_ms} ms</span>
              <span>Unlocked Hint Type: {HINT_TYPE_LABELS[submissionState.result.hint_stage_unlocked] || "None"}</span>
              <span>Valid Failed Attempts: {submissionState.result.valid_failed_attempts}</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="panel hints-panel" aria-labelledby="hints-panel-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Feedback</p>
            <h2 id="hints-panel-title">Hints</h2>
          </div>
        </div>
        {hintState.error ? <p className="error-text" role="alert">{hintState.error}</p> : null}
        <HintCard title="Conceptual" stage={1} hintState={hintState} onUnlockHint={onUnlockHint} />
        <HintCard title="Strategic" stage={2} hintState={hintState} onUnlockHint={onUnlockHint} />
        <HintCard title="Syntactic" stage={3} hintState={hintState} onUnlockHint={onUnlockHint} />
        <AnswerKeyCard answerKeyState={answerKeyState} onViewAnswerKey={onViewAnswerKey} />
      </div>
    </section>
  );
}

function HintCard({ title, stage, hintState, onUnlockHint }) {
  // Reusable card for one hint tier, including unlock/reveal behavior.
  const hints = hintState.hints || {};
  const stageKey = stage === 1 ? "conceptual" : stage === 2 ? "strategic" : "syntactic";
  const content = hints[stageKey];
  const contentLines = normalizeHintLines(content);
  const unlockedStages = hints.unlocked_stages || [];
  const revealedStages = hints.revealed_stages || [];
  const isUnlocked = unlockedStages.includes(stage);
  const isRevealed = revealedStages.includes(stage) && Boolean(content);
  const isHighlighted = (isUnlocked || isRevealed) && hints.highlight_stage === stage;
  const isLoading = hintState.loadingStage === stage;

  return (
    <article className={["hint-card", isRevealed ? "unlocked" : "locked", isHighlighted ? "highlighted" : ""].join(" ").trim()} aria-live={content ? "polite" : "off"}>
      <div className="hint-card-header">
        <div>
          <p className="hint-kicker">{title} Hint</p>
          <h3>{title}</h3>
        </div>
        <span className={isUnlocked || isRevealed ? "hint-status unlocked" : "hint-status locked"}>
          {isRevealed ? "Revealed" : isUnlocked ? "Ready" : "Locked"}
        </span>
      </div>
      <p className="hint-summary">
        {HINT_TYPE_SUMMARIES[stage]}
      </p>
      {content ? (
        <div className="hint-feedback">
          {contentLines.length > 1 ? (
            <ul className="hint-points">
              {contentLines.map((line, index) => (
                <li key={`${stageKey}-line-${index}`}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="hint-paragraph">{contentLines[0] || content}</p>
          )}
        </div>
      ) : (
        <p className="hint-placeholder">
          {isUnlocked
            ? "This hint is unlocked and ready. Reveal it when you want more guidance."
            : "Locked until you earn this hint type."}
        </p>
      )}
      {isUnlocked && !isRevealed ? (
        <button type="button" className="secondary-button" onClick={() => onUnlockHint(stage)} disabled={isLoading}>
          {isLoading ? "Unlocking..." : "Unlock Hint"}
        </button>
      ) : null}
    </article>
  );
}

function AnswerKeyCard({ answerKeyState, onViewAnswerKey }) {
  // Final help panel that reveals the stored solution only after unlock.
  const isUnlocked = answerKeyState.unlocked;
  const hasContent = Boolean(answerKeyState.content);
  const solutionLines = formatCodeLines(answerKeyState.content?.solution_code || "");

  return (
    <article className={["hint-card", hasContent ? "unlocked" : "locked", isUnlocked ? "highlighted" : ""].join(" ").trim()} aria-live={hasContent ? "polite" : "off"}>
      <h3>Answer Key</h3>
      {hasContent ? (
        <>
          <p>{answerKeyState.content.explanation}</p>
          <div className="answer-key-code-block" role="region" aria-label="Reference solution code">
            <ol className="answer-key-lines">
              {solutionLines.map((line, index) => (
                <li key={`answer-key-line-${index}`}>
                  <code>{line || " "}</code>
                </li>
              ))}
            </ol>
          </div>
        </>
      ) : (
        <p>
          {isUnlocked
            ? "You have earned the answer key for this problem. Unlock it when you are ready to compare your work."
            : "Locked until you reach three valid failed Submit attempts on this problem."}
        </p>
      )}
      {answerKeyState.error ? <p className="error-text" role="alert">{answerKeyState.error}</p> : null}
      {isUnlocked && !hasContent ? (
        <button type="button" className="secondary-button" onClick={onViewAnswerKey} disabled={answerKeyState.loading}>
          {answerKeyState.loading ? "Unlocking..." : "Unlock Answer Key"}
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
  onUploadJsonFile,
  onCreateNew,
  onSelectProblem,
  onUpload,
  onSave,
  onDisable,
  onEnable,
  onDelete,
}) {
  // Author-only dashboard for browsing starter/custom problems and editing
  // custom JSON payloads.
  const uploadFileInputRef = useRef(null);
  const authorEditorOptions = {
    ariaLabel: "Problem JSON editor",
    automaticLayout: true,
    stickyScroll: { enabled: false },
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
    <section className="author-layout" aria-label="Author dashboard">
      <section className="panel author-panel" aria-labelledby="author-library-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Author Dashboard</p>
            <h2 id="author-library-title">Manage problem library</h2>
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
              id={`author-filter-${filterItem.id}`}
              className={authorFilter === filterItem.id ? "difficulty-chip active" : "difficulty-chip"}
              onClick={() => onAuthorFilterChange(filterItem.id)}
              role="tab"
              aria-selected={authorFilter === filterItem.id}
              aria-controls="author-problem-list"
              tabIndex={authorFilter === filterItem.id ? 0 : -1}
            >
              {filterItem.label}
            </button>
          ))}
        </div>
        <div className="problem-items" id="author-problem-list">
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

      <section className="panel author-panel" aria-labelledby="author-workspace-title">
        <div className="panel-header">
          <div>
            <p className="eyebrow">JSON Workspace</p>
            <h2 id="author-workspace-title">{authorEditor.mode === "edit" ? `Editing ${authorEditor.problemId}` : "Upload one problem JSON file"}</h2>
          </div>
        </div>
        <p className="prompt-copy">
          Upload a `.json` file or edit the payload directly. Starter problems stay read-only; only your own custom problems can be edited, disabled, or deleted.
        </p>
        <div className="author-toolbar">
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
        <p className="meta-copy editor-help">
          Keyboard tip: when focus is inside the JSON editor, press <code>Ctrl+M</code> to toggle whether the <code>Tab</code> key indents or moves focus to the next control.
        </p>
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
  // Inject Google Identity Services once, then reuse the loaded script.
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
  // Top-level coordinator for auth, problem browsing, timed mode, hints,
  // author tools, and persisted workspace state.
  // Top-level coordinator for auth, problem browsing, timed mode, hints,
  // author tools, and persisted workspace state.
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
  const timedStartInFlightRef = useRef({});
  const timedAutoSubmitRef = useRef({});

  // Keep refs aligned with the latest session and code so execution always
  // uses the newest in-memory values.
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    codeByProblemRef.current = codeByProblem;
  }, [codeByProblem]);

  // Restore only draft code from localStorage. Timed mode state is server-owned
  // so refreshes cannot desync the countdown from backend enforcement.
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

    } catch (_error) {
      // Ignore invalid persisted workspace state and continue with in-memory defaults.
    }
  }, [session?.user_id]);

  // Persist draft code per signed-in user so a page reload does not wipe out
  // work in progress.
  useEffect(() => {
    if (!session?.user_id || typeof window === "undefined") {
      return;
    }

    const payload = JSON.stringify({
      codeByProblem,
    });
    window.localStorage.setItem(getWorkspaceStorageKey(session.user_id), payload);
  }, [session?.user_id, codeByProblem]);

  // Load Google auth configuration once so the login screen knows whether the
  // Google sign-in button should be rendered.
  // Load Google auth configuration once so the login screen knows whether the
  // Google sign-in button should be rendered.
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

  // Restore an existing cookie session before showing either the auth screen or
  // the workspace.
  // Restore an existing cookie session before showing either the auth screen or
  // the workspace.
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

  // Refresh the visible problem list whenever the user changes difficulty.
  // Refresh the visible problem list whenever the user changes difficulty.
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

  // Author users get a management dashboard alongside the student workspace,
  // so their problem list is loaded separately.
  // Author users get a management dashboard alongside the student workspace,
  // so their problem list is loaded separately.
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
        remainingSeconds: getExpectedTimeLimit(selectedProblem),
        limitSeconds: getExpectedTimeLimit(selectedProblem),
        message: "",
      }
    : null;

  useEffect(() => {
    if (!selectedProblem || !session) {
      return;
    }
    refreshHintState(selectedProblem.problem_id);
    refreshAnswerKeyState(selectedProblem.problem_id);
    refreshTimedChallengeState(selectedProblem);
  }, [selectedProblemId, session]);

  // Drive the visible countdown for any active server-owned timers.
  useEffect(() => {
    const hasRunningTimer = Object.values(timedChallengeByProblem).some((challenge) => challenge.status === "running");
    if (!hasRunningTimer) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
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
            status: nextRemaining === 0 ? "expired" : "running",
          };
        });
        return next;
      });
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [timedChallengeByProblem]);

  useEffect(() => {
    Object.entries(timedChallengeByProblem).forEach(([problemId, challenge]) => {
      if (!challenge?.enabled || challenge.status !== "expired" || timedAutoSubmitRef.current[problemId]) {
        return;
      }

      timedAutoSubmitRef.current[problemId] = true;
      const activeProblem = problems.find((problem) => problem.problem_id === problemId);
      const code = codeByProblemRef.current[problemId] || "";

      submitExpiredTimedCode({ problem_id: problemId, code, timed_mode: true })
        .then(async (response) => {
          if (selectedProblem?.problem_id === problemId) {
            setSubmissionState({ loadingAction: null, result: response, error: "" });
            await refreshHintState(problemId);
            await refreshAnswerKeyState(problemId);
          }

          if (activeProblem) {
            setTimedChallenge(problemId, hydrateTimedChallenge(activeProblem, response, {
              enabled: false,
              status: response.result === "Pass" ? "completed" : "expired",
              message: "Time expired and your latest code was submitted automatically.",
            }));
          }
        })
        .catch(async (error) => {
          if (selectedProblem?.problem_id === problemId) {
            setSubmissionState({ loadingAction: null, result: null, error: error.message });
          }
          if (activeProblem) {
            await refreshTimedChallengeState(activeProblem);
          }
        })
        .finally(() => {
          delete timedAutoSubmitRef.current[problemId];
        });
    });
  }, [timedChallengeByProblem, problems, selectedProblem]);

  function updateCode(nextCode) {
    // Store editor changes under the currently selected problem id and arm the
    // timer to begin on the learner's first edit when timed mode is ready.
    if (!selectedProblem) {
      return;
    }
    const problemId = selectedProblem.problem_id;
    const activeChallenge = timedChallengeByProblem[problemId];
    if (activeChallenge?.enabled && activeChallenge.status === "ready") {
      const startedAt = Date.now();
      const limitSeconds = activeChallenge.limitSeconds || getExpectedTimeLimit(selectedProblem);
      setTimedChallenge(problemId, {
        ...activeChallenge,
        status: "running",
        remainingSeconds: limitSeconds,
        limitSeconds,
        message: "",
        startedAt,
        expiresAt: startedAt + (limitSeconds * 1000),
      });
      if (!timedStartInFlightRef.current[problemId]) {
        timedStartInFlightRef.current[problemId] = true;
        startTimedMode(problemId)
          .then((response) => {
            setTimedChallenge(problemId, hydrateTimedChallenge(selectedProblem, response));
          })
          .catch((error) => {
            setTimedChallenge(problemId, buildTimedChallenge(selectedProblem, { message: error.message }));
          })
          .finally(() => {
            delete timedStartInFlightRef.current[problemId];
          });
      }
    }
    setCodeByProblem((current) => ({
      ...current,
      [problemId]: nextCode,
    }));
  }

  // Build the default timer state for a problem using its difficulty-specific
  // time limit.
  // Build the default timer state for a problem using its difficulty-specific
  // time limit.
  function buildTimedChallenge(problem, overrides = {}) {
    const limitSeconds = getExpectedTimeLimit(problem);
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

  function hydrateTimedChallenge(problem, progressPayload, overrides = {}) {
    const fallback = buildTimedChallenge(problem);
    if (!progressPayload) {
      return { ...fallback, ...overrides };
    }

    const rawLimit = progressPayload.timed_mode_limit_seconds || fallback.limitSeconds;
    const rawRemaining = progressPayload.timed_mode_remaining_seconds;
    const shouldRepairLegacyReadyState =
      ["off", "ready"].includes(progressPayload.timed_mode_status)
      && rawLimit < 60
      && fallback.limitSeconds >= 60;

    return {
      ...fallback,
      enabled: progressPayload.timed_mode_enabled,
      status: progressPayload.timed_mode_status,
      remainingSeconds: shouldRepairLegacyReadyState ? fallback.limitSeconds : rawRemaining,
      limitSeconds: shouldRepairLegacyReadyState ? fallback.limitSeconds : rawLimit,
      startedAt: progressPayload.timed_mode_started_at ? Date.parse(progressPayload.timed_mode_started_at) : null,
      expiresAt: progressPayload.timed_mode_expires_at ? Date.parse(progressPayload.timed_mode_expires_at) : null,
      ...overrides,
    };
  }

  async function clearProblemTimer(problem) {
    if (!problem) {
      return;
    }
    try {
      await clearTimedMode(problem.problem_id);
    } catch (_error) {
      // Ignore cleanup failures and still reset the local timer card.
    }
    setTimedChallenge(problem.problem_id, buildTimedChallenge(problem));
  }

  function resetAuthorEditor(nextJson = starterUploadTemplate) {
    // Reset the author JSON workspace back to "new upload" mode.
    // Reset the author JSON workspace back to "new upload" mode.
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
    // Refresh both the learner list and, for authors, the dashboard list after
    // uploads, edits, enables, disables, or deletes.
    // Refresh both the learner list and, for authors, the dashboard list after
    // uploads, edits, enables, disables, or deletes.
    const response = await getProblems(selectedDifficulty);
    setProblems(response.problems);
    if (session?.role === "Author") {
      const authorResponse = await getAuthorProblems(authorFilter, false);
      setAuthorProblems(authorResponse.problems);
    }
  }

  function setTimedChallenge(problemId, updater) {
    // Update one problem's timer state without overwriting timers for others.
    // Update one problem's timer state without overwriting timers for others.
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
    // Submit the login form and store the returned session payload.
    // Submit the login form and store the returned session payload.
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
    // Submit the registration form and sign the new user in.
    // Submit the registration form and sign the new user in.
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
    // Exchange the Google credential token for the app's own session cookie.
    // Exchange the Google credential token for the app's own session cookie.
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
    // Rebuild the full hint panel state for the selected problem.
    // Rebuild the full hint panel state for the selected problem.
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
            revealed_stages: [],
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
    // Re-check whether the answer key is unlocked without automatically
    // revealing its content.
    try {
      const response = await getAnswerKey(problemId);
      setAnswerKeyState({
        unlocked: response.unlocked,
        loading: false,
        content: null,
        error: "",
      });
    } catch (answerKeyError) {
      setAnswerKeyState({ unlocked: false, loading: false, content: null, error: answerKeyError.message });
    }
  }

  async function refreshTimedChallengeState(problem) {
    try {
      const response = await getProblemProgress(problem.problem_id);
      setTimedChallenge(problem.problem_id, hydrateTimedChallenge(problem, response));
    } catch (_error) {
      setTimedChallenge(problem.problem_id, buildTimedChallenge(problem));
    }
  }

  // Route all run, submit, and auto-submit paths through the same helper so
  // evaluation behavior stays consistent.
  // Route all run, submit, and auto-submit paths through the same helper so
  // evaluation behavior stays consistent.
  async function executeCode(action, options = {}) {
    const { forcedProblemId = null, timedMode = false } = options;
    const activeSession = sessionRef.current;
    const problemId = forcedProblemId || selectedProblem?.problem_id;
    if (!problemId || !activeSession) {
      return;
    }
    const code = codeByProblemRef.current[problemId] || "";
    const isSelectedProblem = selectedProblem?.problem_id === problemId;
    const activeProblem = isSelectedProblem ? selectedProblem : problems.find((problem) => problem.problem_id === problemId);

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
      if (timedMode && activeProblem) {
        if (response.result === "Pass") {
          setTimedChallenge(problemId, hydrateTimedChallenge(activeProblem, response, {
            enabled: false,
            status: "completed",
            message: "Timed challenge passed before the clock ran out.",
          }));
        } else {
          setTimedChallenge(problemId, hydrateTimedChallenge(activeProblem, response));
        }
      }
    } catch (submitError) {
      if (isSelectedProblem) {
        setSubmissionState({ loadingAction: null, result: null, error: submitError.message });
      }
      if (timedMode && activeProblem) {
        await refreshTimedChallengeState(activeProblem);
      }
    }
  }

  async function handleUnlockHint(stage) {
    // Reveal one unlocked hint stage on demand.
    // Reveal one unlocked hint stage on demand.
    if (!selectedProblem || !session) {
      return;
    }

    setHintState((current) => ({ loadingStage: stage, hints: current.hints, error: "" }));
    const activeChallenge = timedChallengeByProblem[selectedProblem.problem_id];
    const shouldPauseTimer = activeChallenge?.enabled && activeChallenge.status === "running";

    try {
      if (shouldPauseTimer) {
        const pausedProgress = await pauseTimedMode(selectedProblem.problem_id);
        setTimedChallenge(selectedProblem.problem_id, hydrateTimedChallenge(selectedProblem, pausedProgress));
      }
      const response = await getHints(selectedProblem.problem_id, stage);
      setHintState({ loadingStage: null, hints: response, error: "" });
    } catch (hintError) {
      setHintState((current) => ({ loadingStage: null, hints: current.hints, error: hintError.message }));
    } finally {
      if (shouldPauseTimer) {
        try {
          const resumedProgress = await resumeTimedMode(selectedProblem.problem_id);
          setTimedChallenge(selectedProblem.problem_id, hydrateTimedChallenge(selectedProblem, resumedProgress));
        } catch (resumeError) {
          setTimedChallenge(
            selectedProblem.problem_id,
            buildTimedChallenge(selectedProblem, { message: resumeError.message }),
          );
        }
      }
    }
  }

  async function handleResetProgress() {
    // Clear one problem back to its starter state for the current user.
    // Clear one problem back to its starter state for the current user.
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
          revealed_stages: [],
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

  async function handleEnableTimedMode() {
    // Arm timed mode on the backend, then wait for the first editor change to
    // actually start the countdown.
    if (!selectedProblem) {
      return;
    }
    try {
      const response = await enableTimedMode(selectedProblem.problem_id);
      setTimedChallenge(selectedProblem.problem_id, hydrateTimedChallenge(selectedProblem, response));
    } catch (error) {
      setTimedChallenge(selectedProblem.problem_id, buildTimedChallenge(selectedProblem, { message: error.message }));
    }
  }

  async function handleDisableTimedMode() {
    // Clear any active timer so the learner can go back to untimed practice.
    if (!selectedProblem) {
      return;
    }
    await clearProblemTimer(selectedProblem);
  }

  async function handleSelectProblem(nextProblemId) {
    if (selectedProblem && selectedProblem.problem_id !== nextProblemId) {
      const activeChallenge = timedChallengeByProblem[selectedProblem.problem_id];
      if (activeChallenge?.enabled) {
        await clearProblemTimer(selectedProblem);
      }
    }
    setSelectedProblemId(nextProblemId);
  }

  async function handleDifficultyChange(nextDifficulty) {
    if (selectedProblem) {
      const activeChallenge = timedChallengeByProblem[selectedProblem.problem_id];
      if (activeChallenge?.enabled) {
        await clearProblemTimer(selectedProblem);
      }
    }
    setSelectedDifficulty(nextDifficulty);
  }

  async function handleViewAnswerKey() {
    // Load the answer key body once the learner chooses to reveal it.
    // Load the answer key body once the learner chooses to reveal it.
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
    // Pull an author-owned custom problem into the JSON editor for editing.
    // Pull an author-owned custom problem into the JSON editor for editing.
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

  async function handleAuthorFileUpload(event) {
    // Upload a chosen JSON file directly to the backend author endpoint.
    // Upload a chosen JSON file directly to the backend author endpoint.
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
    // Parse the JSON editor contents and create a new custom problem.
    // Parse the JSON editor contents and create a new custom problem.
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
    // Save edits made to an existing custom problem draft.
    // Save edits made to an existing custom problem draft.
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
    // Flip a custom problem between enabled and disabled states.
    // Flip a custom problem between enabled and disabled states.
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
    // Soft-delete a custom problem from the author dashboard.
    // Soft-delete a custom problem from the author dashboard.
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
    // Clear backend cookies if possible, then reset all client-side state.
    // Clear backend cookies if possible, then reset all client-side state.
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
        <a className="skip-link" href="#auth-title">Skip to sign-in form</a>
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
      <a className="skip-link" href="#workspace-panel">Skip to main workspace</a>
      <header className="topbar">
        <div>
          <p className="eyebrow">Logged In</p>
          <h1>CodeSoCrat Workspace</h1>
          <p className="meta-copy">{session.display_name || session.email}</p>
        </div>
        <div className="topbar-actions">
          <span>{session.role}</span>
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
          onDifficultyChange={handleDifficultyChange}
          onSelect={handleSelectProblem}
        />
        <SubmissionPanel
          problem={selectedProblem}
          code={currentCode}
          onEditorChange={updateCode}
          onRun={() => executeCode("Run", { timedMode: Boolean(selectedTimedChallenge?.enabled) })}
          onSubmit={() => executeCode("Submit", { timedMode: Boolean(selectedTimedChallenge?.enabled) })}
          onResetProgress={handleResetProgress}
          timedChallenge={selectedTimedChallenge || buildTimedChallenge(selectedProblem)}
          onEnableTimedMode={handleEnableTimedMode}
          onDisableTimedMode={handleDisableTimedMode}
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
