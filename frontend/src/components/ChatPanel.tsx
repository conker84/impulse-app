import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage, WizardStep } from "../types";

interface Props {
  messages: ChatMessage[];
  onSend: (message: string) => void;
  loading: boolean;
  placeholder?: string;
  wizardStep?: WizardStep;
  settingsButton?: React.ReactNode;
}

const STEP_HINTS: Record<WizardStep, { title: string; hint: string }> = {
  source_data: {
    title: "Step 1: Choose Data Source",
    hint: "Upload raw measurement files (MF4, CSV) or point to existing Silver layer tables in Unity Catalog.",
  },
  report_name: {
    title: "Step 2: Set a Report Name",
    hint: "Tell the assistant what to call your report, e.g. \"Create a report called oil_temp_report\"",
  },
  channels: {
    title: "Step 3: Define Channels",
    hint: "Describe the signals you need. The assistant will search for aliases and register them.",
  },
  aggregations: {
    title: "Step 4: Define Aggregations",
    hint: "Describe the histograms you want, e.g. \"Duration histogram for oil temp from 0 to 160 degC\"",
  },
  vehicles: {
    title: "Step 5: Configure Vehicles",
    hint: "Add test vehicles with their IDs and time ranges.",
  },
  ready: {
    title: "Report Ready",
    hint: "Review the configuration and click Deploy & Run when ready.",
  },
};

export default function ChatPanel({ messages, onSend, loading, placeholder, wizardStep, settingsButton }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    onSend(trimmed);
    setInput("");
  };

  const hint = wizardStep ? STEP_HINTS[wizardStep] : null;

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <span className="dot" />
        Impulse
        {settingsButton && <div style={{ marginLeft: "auto" }}>{settingsButton}</div>}
      </div>

      <div className="chat-messages">
        {messages.length === 0 && hint && (
          <div className="empty-state">
            <div className="icon">&#x1F4CA;</div>
            <div style={{ fontWeight: 600 }}>{hint.title}</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {hint.hint}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            {msg.role === "assistant" ? (
              <ReactMarkdown>{msg.content}</ReactMarkdown>
            ) : (
              msg.content
            )}
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <span className="spinner" /> Thinking...
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="chat-input-area" onSubmit={handleSubmit}>
        <div className="chat-input-wrapper">
          <input
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={placeholder || "Describe your report..."}
            disabled={loading}
          />
          <button className="send-btn" type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
