import React, { useState } from 'react';
import { Send, Bot } from 'lucide-react';
import CodeViewer from './CodeView';

export default function ChatConsole({ messages, onSendMessage, loading }) {
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim() || loading) return;
    onSendMessage(input);
    setInput('');
  };

  return (
    <div className="main-console">
      <div className="console-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Bot size={24} color="#38bdf8" />
          <h2 style={{ fontSize: '1.1rem' }}>AI Coding Assistant</h2>
        </div>
        <span className="status-badge">MCP Tools Active</span>
      </div>

      <div className="chat-history">
        {messages.length === 0 ? (
          <div style={{ color: '#64748b', textAlign: 'center', marginTop: '40px' }}>
            Ask a question, request code generation, or run project tests using MCP tools.
          </div>
        ) : (
          messages.map((msg, index) => (
            <div key={index} className={`message ${msg.sender}`}>
              <div>{msg.text}</div>
              {msg.code && <CodeViewer code={msg.code} />}
            </div>
          ))
        )}
        {loading && (
          <div className="message ai" style={{ color: '#94a3b8' }}>
            Assistant is invoking MCP tools & generating response...
          </div>
        )}
      </div>

      <div className="input-area">
        <input
          type="text"
          placeholder="Ask to read code, search files, or run tests..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button onClick={handleSend} disabled={loading}>
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}