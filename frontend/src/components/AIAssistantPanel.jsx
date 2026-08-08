import { useEffect, useRef } from "react";

export default function AIAssistantPanel({
  chat,
  question,
  setQuestion,
  busy,
  onAsk,
  onClose,
}) {
  const logRef = useRef(null);

  // Keep the log scrolled to the latest message/typing indicator.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [chat, busy]);

  return (
    <div className="ai-panel" role="dialog" aria-label="AgriFlow AI assistant">
      <div className="ai-panel-header">
        <div className="ai-panel-title">
          <span className="ai-panel-dot" />
          AgriFlow Assistant
        </div>
        <button className="ai-panel-close" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <div className="ai-panel-log" ref={logRef}>
        {chat.length === 0 && !busy && (
          <p className="ai-panel-empty">
            Ask about biomass, plants, or routing — e.g. "Which district has
            the highest biomass?" or "How far is Amreli from its nearest
            plant?"
          </p>
        )}
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

      <div className="ai-panel-input">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAsk()}
          placeholder="Ask about biomass, plants, or routing…"
          autoFocus
        />
        <button onClick={onAsk} disabled={busy}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
    </div>
  );
}
