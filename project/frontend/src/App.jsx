import React, { useState } from 'react';
import FileExplorer from './components/FileExplorer';
import ChatConsole from './components/ChatConsole';
import './App.css';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleSendMessage = async (userText) => {
    const newMessages = [...messages, { sender: 'user', text: userText }];
    setMessages(newMessages);
    setLoading(true);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText }),
      });

      const data = await response.json();

      if (response.ok) {
        setMessages([...newMessages, { sender: 'ai', text: data.response }]);
      } else {
        setMessages([...newMessages, { sender: 'ai', text: `Error: ${data.detail}` }]);
      }
    } catch (err) {
      setMessages([...newMessages, { sender: 'ai', text: 'Failed to connect to backend server.' }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectFile = (fileName) => {
    handleSendMessage(`Read and explain the contents of ${fileName}`);
  };

  return (
    <div className="app-container">
      <FileExplorer onSelectFile={handleSelectFile} />
      <ChatConsole messages={messages} onSendMessage={handleSendMessage} loading={loading} />
    </div>
  );
}