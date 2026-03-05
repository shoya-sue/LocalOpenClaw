// LocalOpenClaw フロントエンド Phase 3
// Phaser.js ピクセルアートオフィス + React 操作パネル

import { useEffect, useRef, useState } from 'react';
import PhaserGame  from './game/PhaserGame.jsx';
import ControlPanel from './components/ControlPanel.jsx';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8080';
const WS_URL      = import.meta.env.VITE_WS_URL      || 'ws://localhost:8080/ws';

export default function App() {
  const [agents,        setAgents]        = useState([]);
  const [ollamaStatus,  setOllamaStatus]  = useState('確認中...');
  const [messages,      setMessages]      = useState([]);
  const [tasks,         setTasks]         = useState([]);
  const [agentStatuses, setAgentStatuses] = useState({});
  const [wsState,       setWsState]       = useState('接続中...');
  const [mode,          setMode]          = useState('orchestrate');
  const [selectedAgent, setSelectedAgent] = useState('leader');

  const wsRef = useRef(null);

  // バックエンドのヘルスチェックとエージェント一覧取得
  useEffect(() => {
    fetch(`${BACKEND_URL}/agents`)
      .then(r => r.json())
      .then(data => {
        const list = data.agents || [];
        setAgents(list);
        // 初期ステータスを idle で設定
        const init = {};
        list.forEach(a => { init[a.codename] = 'idle'; });
        setAgentStatuses(init);
      })
      .catch(() => setAgents([]));

    fetch(`${BACKEND_URL}/health/ollama`)
      .then(r => r.json())
      .then(data => setOllamaStatus(
        data.status === 'ok'
          ? `OK (${data.models?.join(', ') || 'なし'})`
          : `エラー: ${data.message}`
      ))
      .catch(() => setOllamaStatus('バックエンド未起動'));
  }, []);

  // WebSocket 接続（自動再接続あり）
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen  = () => setWsState('接続済み');
      ws.onclose = () => {
        setWsState('切断 — 5秒後に再接続...');
        setTimeout(connect, 5000);
      };
      ws.onerror = () => setWsState('エラー');

      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        handleWsEvent(event);
      };
    };

    connect();
    return () => wsRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleWsEvent = (event) => {
    switch (event.type) {
      case 'token':
        // ストリーミングトークンを最後のメッセージに追記
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant' && last.agent === event.agent) {
            return [...prev.slice(0, -1), { ...last, content: last.content + event.content }];
          }
          return [...prev, { role: 'assistant', agent: event.agent, content: event.content }];
        });
        break;

      case 'done':
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, done: true }];
          }
          return prev;
        });
        break;

      case 'agent_status':
        setAgentStatuses(prev => ({ ...prev, [event.agent]: event.status }));
        break;

      case 'task_created':
        setTasks(prev => [...prev, {
          id:     event.task_id,
          agent:  event.agent,
          title:  event.title,
          status: 'pending',
        }]);
        break;

      case 'agent_thinking':
        setTasks(prev => prev.map(t =>
          t.id === event.task_id ? { ...t, status: 'thinking' } : t
        ));
        break;

      case 'task_done':
        setTasks(prev => prev.map(t =>
          t.id === event.task_id ? { ...t, status: 'done', preview: event.preview } : t
        ));
        break;

      case 'orchestration_result':
        setMessages(prev => [
          ...prev,
          {
            role:         'assistant',
            agent:        'leader',
            content:      event.response || event.error || '応答なし',
            orchestration: event.orchestration,
            reasoning:    event.reasoning,
            done:         true,
          },
        ]);
        break;
    }
  };

  const handleSend = (text) => {
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    setMessages(prev => [...prev, { role: 'user', content: text }]);

    if (mode === 'orchestrate') {
      wsRef.current.send(JSON.stringify({ type: 'orchestrate', message: text }));
      setTasks([]);  // 新しい会話ではタスクをリセット
    } else {
      wsRef.current.send(JSON.stringify({ type: 'chat', agent: selectedAgent, message: text }));
    }
  };

  return (
    <div style={{ width: 900, margin: '20px auto' }}>
      {/* Phaser.js キャンバス — ピクセルアートオフィス */}
      <PhaserGame agentStates={agentStatuses} />

      {/* React 操作パネル */}
      <ControlPanel
        agents={agents}
        messages={messages}
        tasks={tasks}
        wsState={wsState}
        ollamaStatus={ollamaStatus}
        mode={mode}
        selectedAgent={selectedAgent}
        onModeChange={setMode}
        onAgentSelect={setSelectedAgent}
        onSend={handleSend}
      />
    </div>
  );
}
