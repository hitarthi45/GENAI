import React from 'react';
import { Folder, FileCode, HardDrive } from 'lucide-react';

export default function FileExplorer({ files, onSelectFile }) {
  const defaultFiles = [
    { name: 'app/main.py', type: 'file' },
    { name: 'app/mcp_client.py', type: 'file' },
    { name: 'mcp_servers/filesystem_server.py', type: 'file' },
    { name: 'mcp_servers/testing_server.py', type: 'file' },
    { name: 'requirements.txt', type: 'file' }
  ];

  const fileList = files && files.length > 0 ? files : defaultFiles;

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <HardDrive size={20} />
        <span>Project Files (MCP)</span>
      </div>
      <ul className="file-tree">
        {fileList.map((item, index) => (
          <li
            key={index}
            className="file-item"
            onClick={() => onSelectFile && onSelectFile(item.name || item)}
          >
            {item.type === 'folder' ? <Folder size={16} color="#38bdf8" /> : <FileCode size={16} color="#a855f7" />}
            <span>{item.name || item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}