import React from 'react';

export default function CodeViewer({ code }) {
  return (
    <div className="code-block">
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}