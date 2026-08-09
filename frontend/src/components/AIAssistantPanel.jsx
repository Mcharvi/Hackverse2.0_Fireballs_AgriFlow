// AIAssistantPanel — the chat popup. White + AgriFlow-green, in the style
// of the reference: "New chat" action in the header, a centered "How can I
// help you?" greeting with suggestion chips when the chat is empty, and a
// bottom input row with a mic (voice questions, Gujarati by default) and a
// paper-plane send button.
import { useEffect, useRef, useState } from "react";
import { useLanguage } from "../LanguageContext.jsx";
import { LANGUAGES } from "../translations.js";

// Suggested questions shown on a fresh chat. Farmers can tap one instead of
// typing; the mic handles the "ask in your own language" case.
const SUGGESTIONS = [
  "What is the nearest plant from Morbi?",
  "Which district produces the most residue?",
  "Is it worth collecting from Bhavnagar?",
  "Which plants still have spare capacity?",
];

export default function AIAssistantPanel({
  chat,
  question,
  setQuestion,
  busy,
  onAsk,
  onNewChat,
  onClose,
  suggestions = SUGGESTIONS,
}) {
  const { t, lang } = useLanguage();
  const logRef = useRef(null);
  const recRef = useRef(null);
  const [listening, setListening] = useState(false);
  const [micError, setMicError] = useState(null);

  // Keep the log scrolled to the latest message/typing indicator.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [chat, busy]);  // Voice input via the Web Speech API. The mic first listens in the
  // language the user picked in the dropdown (gu-IN / hi-IN / en-IN), so a
  // farmer speaking their own language gets recognized directly. If that
  // pass yields nothing or the language isn't supported, it falls back to
  // auto-detect so *any* language the user speaks still lands in the input
  // box — the assistant then answers in the selected language regardless.
  const VOICE_LOCALES = { gu: "gu-IN", hi: "hi-IN", en: "en-IN" };

  function toggleMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setMicError(t.micNotSupported);
      return;
    }
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new SR();
    rec.lang = VOICE_LOCALES[lang] || "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (e) => {
      let transcript = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        transcript += e.results[i][0].transcript;
      }
      setQuestion(transcript);
    };
    rec.onend = () => setListening(false);
    rec.onerror = (e) => {
      setListening(false);
      if (e.error === "not-allowed") {
        setMicError(t.micBlocked);
        return;
      }
      // Recognition in the selected language failed (e.g. "language-not-
      // supported" or "no-speech") — retry once with auto-detect so the
      // user can speak any language they like.
      if (!rec._retried && VOICE_LOCALES[lang]) {
        rec._retried = true;
        const retry = new SR();
        retry.interimResults = true;
        retry.continuous = false;
        retry.onresult = rec.onresult;
        retry.onend = () => setListening(false);
        retry.onerror = () => {
          setMicError(`Mic error: ${e.error}`);
        };
        recRef.current = retry;
        setMicError(null);
        retry.start();
        setListening(true);
      } else {
        setMicError(`Mic error: ${e.error}`);
      }
    };
    recRef.current = rec;
    setMicError(null);
    rec.start();
    setListening(true);
  }

  function askSuggestion(q) {
    setQuestion(q); // show it in the input box too
    onAsk(q);
  }

  return (
    <div className="ai-panel" role="dialog" aria-label={t.assistantHeading}>
      <div className="ai-panel-header">
        <div className="ai-panel-title">
          <span className="ai-panel-dot" />
          {t.assistantHeading}
        </div>
        <div className="ai-panel-actions">
          <button className="ai-newchat" onClick={onNewChat}>
            <PlusIcon /> {t.newChat}
          </button>
          <button className="ai-panel-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
      </div>

      {chat.length === 0 && !busy ? (
        <div className="ai-empty">
          <h3>{t.howCanIHelp}</h3>
          <p>{t.askInLanguages}</p>
          <div className="ai-suggestions">
            {suggestions.map((s) => (
              <button key={s} className="ai-chip" onClick={() => askSuggestion(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="ai-panel-log" ref={logRef}>
          {chat.map((m, i) => (
            <div key={i} className={`ai-msg ${m.role}`}>
              {m.text}
            </div>
          ))}
          {busy && (
            <div className="typing-dots" aria-label="Assistant is thinking">
              <span />
              <span />
              <span />
            </div>
          )}
        </div>
      )}

      <div className="ai-panel-input">
        {micError && <span className="ai-mic-error">⚠ {micError}</span>}
        <div className="ai-input-row">
          <button
            className={`ai-mic${listening ? " is-listening" : ""}`}
            onClick={toggleMic}
            aria-label={listening ? t.micStopTitle : `${t.micAskTitle} (${LANGUAGES[lang]})`}
            title={listening ? t.micStopTitle : `${t.micAskTitle} (${LANGUAGES[lang]})`}
          >
            <MicIcon />
          </button>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAsk()}
            placeholder={t.askAnythingPlaceholder}
            autoFocus
          />
          <button
            className="ai-send"
            onClick={() => onAsk()}
            disabled={busy || !question.trim()}
            aria-label="Send"
          >
            <SendIcon />
          </button>
        </div>
      </div>
    </div>
  );
}

function SendIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22l-4-9-9-4 20-7z" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="13"
      height="13"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
