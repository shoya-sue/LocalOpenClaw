// LocalOpenClaw フロントエンド — 自律観察モード
// AI同士の自律活動をリアルタイムで観察するview-only UI

import { useEffect, useRef, useState } from 'react';
import PhaserGame  from './game/PhaserGame.jsx';
import ControlPanel from './components/ControlPanel.jsx';
import GoalPanel   from './components/GoalPanel.jsx';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8080';
const WS_URL      = import.meta.env.VITE_WS_URL      || 'ws://localhost:8080/ws';

export default function App() {
  const [agents,        setAgents]        = useState([]);
  const [ollamaStatus,  setOllamaStatus]  = useState('確認中...');
  const [activities,    setActivities]    = useState([]);
  const [tasks,         setTasks]         = useState([]);
  const [agentStatuses, setAgentStatuses] = useState({});
  const [wsState,       setWsState]       = useState('接続中...');
  const [goals,         setGoals]         = useState([]);
  const [checkingIds,   setCheckingIds]   = useState(new Set());

  const wsRef = useRef(null);

  const MAX_ACTIVITIES = 100;

  // アクティビティフィードに追記（最新100件を保持）
  const addActivity = (activity) => {
    setActivities(prev => {
      const next = [...prev, { ...activity, ts: Date.now() }];
      return next.length > MAX_ACTIVITIES ? next.slice(next.length - MAX_ACTIVITIES) : next;
    });
  };

  // バックエンドのヘルスチェックとエージェント一覧取得
  useEffect(() => {
    fetch(`${BACKEND_URL}/agents`)
      .then(r => r.json())
      .then(data => {
        const list = data.agents || [];
        setAgents(list);
        const init = {};
        list.forEach(a => { init[a.codename] = { status: 'idle', detail: '' }; });
        setAgentStatuses(init);
      })
      .catch(() => setAgents([]));

    fetch(`${BACKEND_URL}/goals`)
      .then(r => r.json())
      .then(data => setGoals(data.goals || []))
      .catch(() => setGoals([]));

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
      case 'agent_status':
        setAgentStatuses(prev => ({
          ...prev,
          [event.agent]: { status: event.status, detail: event.detail || '' },
        }));
        // 思考中になった場合のみフィードに記録（ノイズを減らす）
        if (event.status === 'thinking' && event.detail) {
          addActivity({ type: 'agent_thinking', agent: event.agent, detail: event.detail });
        }
        break;

      case 'task_created':
        setTasks(prev => [...prev, {
          id:     event.task_id,
          agent:  event.agent,
          title:  event.title,
          status: 'pending',
        }]);
        addActivity({ type: 'task_created', agent: event.agent, title: event.title });
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
        addActivity({ type: 'task_done', agent: event.agent, preview: event.preview });
        break;

      case 'orchestration_result':
        addActivity({
          type:      'orchestration_result',
          agent:     'leader',
          response:  event.response || event.error || '応答なし',
          reasoning: event.reasoning,
        });
        break;

      case 'autonomous_cycle_start':
        setTasks([]);  // 新サイクル開始でタスクをリセット
        addActivity({ type: 'autonomous_cycle_start', cycle: event.cycle, theme: event.theme });
        break;

      case 'autonomous_trigger':
        addActivity({ type: 'autonomous_trigger', keyword: event.keyword, agent: event.agent });
        break;

      case 'autonomous_cycle_done':
        addActivity({ type: 'autonomous_cycle_done', cycle: event.cycle, triggers: event.triggers_fired });
        break;

      case 'autonomous_artifact':
        addActivity({ type: 'autonomous_artifact', cycle: event.cycle, path: event.path });
        break;

      case 'goal_checked':
        // ゴールの状態をバックエンドから再取得して同期
        fetch(`${BACKEND_URL}/goals`)
          .then(r => r.json())
          .then(data => setGoals(data.goals || []))
          .catch(() => {});
        addActivity({ type: 'goal_checked', goal_id: event.goal_id, achieved: event.achieved });
        break;
    }
  };

  // ゴール達成判定を手動実行
  const handleCheckGoal = (goalId) => {
    setCheckingIds(prev => new Set([...prev, goalId]));
    fetch(`${BACKEND_URL}/goals/${goalId}/check`, { method: 'POST' })
      .then(r => r.json())
      .then(() => {
        // 判定後はサーバーからゴール状態を再取得して同期
        return fetch(`${BACKEND_URL}/goals`).then(r => r.json());
      })
      .then(data => setGoals(data.goals || []))
      .catch(() => {})
      .finally(() => {
        setCheckingIds(prev => {
          const next = new Set(prev);
          next.delete(goalId);
          return next;
        });
      });
  };

  return (
    <div style={{ width: 900, margin: '20px auto' }}>
      {/* Phaser.js キャンバス — ピクセルアートオフィス */}
      <PhaserGame agentStates={agentStatuses} />

      {/* 自律活動観察パネル */}
      <ControlPanel
        agents={agents}
        activities={activities}
        tasks={tasks}
        wsState={wsState}
        ollamaStatus={ollamaStatus}
      />

      {/* ゴール管理パネル */}
      <GoalPanel
        goals={goals}
        onCheckGoal={handleCheckGoal}
        checkingIds={checkingIds}
      />
    </div>
  );
}
