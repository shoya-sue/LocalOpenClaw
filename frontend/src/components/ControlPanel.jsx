// ControlPanel.jsx — React 操作パネル
// ログ・タスクキュー・チャット入力を管理する

import { useRef } from 'react';

// エージェントIDに対応するバッジ色（Phaser と揃える）
const AGENT_BADGE_COLORS = {
  detective:  '#9b59b6',
  researcher: '#3498db',
  leader:     '#e74c3c',
  engineer:   '#2ecc71',
  sales:      '#f39c12',
  secretary:  '#1abc9c',
};

/**
 * @param {object}   props
 * @param {Array}    props.agents          エージェント一覧
 * @param {Array}    props.messages        チャット履歴
 * @param {Array}    props.tasks           タスクキュー
 * @param {string}   props.wsState         WebSocket状態ラベル
 * @param {string}   props.ollamaStatus    Ollamaヘルス状態ラベル
 * @param {string}   props.mode            'orchestrate' | 'chat'
 * @param {string}   props.selectedAgent   直接チャット対象エージェントID
 * @param {Function} props.onModeChange    (mode: string) => void
 * @param {Function} props.onAgentSelect   (agentId: string) => void
 * @param {Function} props.onSend          (message: string) => void
 */
export default function ControlPanel({
  agents = [],
  messages = [],
  tasks = [],
  wsState,
  ollamaStatus,
  mode,
  selectedAgent,
  onModeChange,
  onAgentSelect,
  onSend,
}) {
  const inputRef   = useRef(null);
  const logAreaRef = useRef(null);

  const handleSend = () => {
    const text = inputRef.current?.value?.trim();
    if (!text) return;
    onSend(text);
    inputRef.current.value = '';
  };

  const handleKeyDown = (e) => {
    if (e.ctrlKey && e.key === 'Enter') handleSend();
  };

  const wsOk     = wsState === '接続済み';
  const ollamaOk = ollamaStatus?.startsWith('OK');

  return (
    <div style={styles.panel}>
      {/* ステータスバー */}
      <div style={styles.statusBar}>
        <span style={styles.appName}>⚡ LocalOpenClaw</span>
        <span style={styles.statusItem}>
          WS:&nbsp;<span style={{ color: wsOk ? '#2ecc71' : '#e74c3c' }}>{wsState}</span>
        </span>
        <span style={styles.statusItem}>
          Ollama:&nbsp;<span style={{ color: ollamaOk ? '#2ecc71' : '#e74c3c' }}>{ollamaStatus}</span>
        </span>
      </div>

      <div style={styles.body}>
        {/* 左: タスクキュー */}
        <div style={styles.sidebar}>
          <div style={styles.sectionLabel}>タスクキュー</div>
          {tasks.length === 0 ? (
            <div style={styles.emptyHint}>タスクなし</div>
          ) : (
            tasks.map(t => (
              <div key={t.id} style={styles.taskCard}>
                <div style={{
                  ...styles.taskAgent,
                  color: AGENT_BADGE_COLORS[t.agent] || '#888',
                }}>
                  {agents.find(a => a.codename === t.agent)?.name || t.agent}
                </div>
                <div style={styles.taskTitle}>{t.title}</div>
                <div style={{
                  ...styles.taskStatus,
                  color: t.status === 'done'     ? '#2ecc71'
                       : t.status === 'thinking' ? '#f39c12'
                       : '#666',
                }}>
                  {t.status === 'done'     ? '✓ 完了'
                  : t.status === 'thinking' ? '⟳ 実行中'
                  : '待機中'}
                </div>
                {t.preview && (
                  <div style={styles.taskPreview}>{t.preview}</div>
                )}
              </div>
            ))
          )}
        </div>

        {/* 右: チャットエリア */}
        <div style={styles.chatColumn}>
          {/* モード切替タブ */}
          <div style={styles.tabBar}>
            {[
              { id: 'orchestrate', label: '🔀 オーケストレーション' },
              { id: 'chat',        label: '💬 直接チャット' },
            ].map(m => (
              <button
                key={m.id}
                onClick={() => onModeChange(m.id)}
                style={{
                  ...styles.tab,
                  background: mode === m.id ? '#1a3a4a' : 'transparent',
                  color:      mode === m.id ? '#7fdbff' : '#555',
                  borderBottom: mode === m.id ? '1px solid #7fdbff' : '1px solid transparent',
                }}
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* 直接チャット: エージェント選択 */}
          {mode === 'chat' && (
            <div style={styles.agentPicker}>
              {agents.map(a => (
                <button
                  key={a.codename}
                  onClick={() => onAgentSelect(a.codename)}
                  style={{
                    ...styles.agentBtn,
                    borderColor: selectedAgent === a.codename
                      ? (AGENT_BADGE_COLORS[a.codename] || '#7fdbff')
                      : '#2a2a2a',
                    color: selectedAgent === a.codename
                      ? (AGENT_BADGE_COLORS[a.codename] || '#7fdbff')
                      : '#666',
                  }}
                >
                  {a.name}
                </button>
              ))}
            </div>
          )}

          {/* メッセージログ */}
          <div ref={logAreaRef} style={styles.logArea}>
            {messages.length === 0 ? (
              <div style={styles.logEmpty}>
                {mode === 'orchestrate'
                  ? 'チームへの指示を送ると Leader がタスクを割り振ります'
                  : `${agents.find(a => a.codename === selectedAgent)?.name || selectedAgent} と直接チャット`
                }
              </div>
            ) : (
              messages.map((msg, i) => (
                <MessageBubble key={i} msg={msg} agents={agents} />
              ))
            )}
          </div>

          {/* 入力エリア */}
          <div style={styles.inputRow}>
            <textarea
              ref={inputRef}
              placeholder={
                mode === 'orchestrate'
                  ? 'チームへの指示を入力... (Ctrl+Enter で送信)'
                  : `${agents.find(a => a.codename === selectedAgent)?.name || '?'} へのメッセージ...`
              }
              rows={3}
              style={styles.textarea}
              onKeyDown={handleKeyDown}
            />
            <button onClick={handleSend} style={styles.sendBtn}>
              送信
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// メッセージバブルコンポーネント
function MessageBubble({ msg, agents }) {
  const isUser = msg.role === 'user';
  const agentName = agents.find(a => a.codename === msg.agent)?.name || msg.agent;
  const agentColor = AGENT_BADGE_COLORS[msg.agent] || '#888';

  return (
    <div style={{ marginBottom: 10, textAlign: isUser ? 'right' : 'left' }}>
      {!isUser && (
        <div style={{ fontSize: 9, color: agentColor, marginBottom: 2 }}>
          {agentName}
          {msg.orchestration && <span style={{ color: '#7fdbff' }}> (チーム統合)</span>}
          {msg.reasoning && <span style={{ color: '#444' }}> — {msg.reasoning}</span>}
        </div>
      )}
      <div style={{
        display: 'inline-block',
        maxWidth: '88%',
        background: isUser ? '#0d2a3a' : '#141414',
        border: `1px solid ${isUser ? '#1a4a6a' : '#2a2a2a'}`,
        borderRadius: 3,
        padding: '6px 10px',
        fontSize: 12,
        textAlign: 'left',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {msg.content}
        {!isUser && !msg.done && (
          <span style={{ color: '#7fdbff' }}>▌</span>
        )}
      </div>
    </div>
  );
}

// ===== スタイル定数 =====

const styles = {
  panel: {
    border: '1px solid #1a1a1a',
    borderTop: '1px solid #2a2a2a',
    background: '#080808',
  },
  statusBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    padding: '6px 14px',
    borderBottom: '1px solid #1a1a1a',
    fontSize: 10,
    color: '#555',
  },
  appName: {
    color: '#7fdbff',
    fontWeight: 'bold',
    fontSize: 13,
    marginRight: 8,
  },
  statusItem: {
    fontSize: 10,
  },
  body: {
    display: 'flex',
    height: 320,
  },
  sidebar: {
    width: 180,
    flexShrink: 0,
    borderRight: '1px solid #1a1a1a',
    padding: '10px 10px',
    overflowY: 'auto',
  },
  sectionLabel: {
    fontSize: 9,
    color: '#444',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  emptyHint: {
    fontSize: 10,
    color: '#333',
    fontStyle: 'italic',
  },
  taskCard: {
    border: '1px solid #1e1e1e',
    borderRadius: 2,
    padding: '6px 7px',
    marginBottom: 5,
  },
  taskAgent: {
    fontSize: 9,
    fontWeight: 'bold',
  },
  taskTitle: {
    fontSize: 10,
    color: '#888',
    marginTop: 2,
  },
  taskStatus: {
    fontSize: 9,
    marginTop: 3,
  },
  taskPreview: {
    fontSize: 9,
    color: '#444',
    marginTop: 3,
    borderTop: '1px solid #1a1a1a',
    paddingTop: 3,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  chatColumn: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  tabBar: {
    display: 'flex',
    borderBottom: '1px solid #1a1a1a',
  },
  tab: {
    padding: '7px 14px',
    fontSize: 11,
    border: 'none',
    cursor: 'pointer',
    fontFamily: 'monospace',
    background: 'transparent',
  },
  agentPicker: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 5,
    padding: '7px 10px',
    borderBottom: '1px solid #1a1a1a',
  },
  agentBtn: {
    fontSize: 10,
    padding: '3px 8px',
    border: '1px solid #2a2a2a',
    borderRadius: 2,
    background: 'transparent',
    cursor: 'pointer',
    fontFamily: 'monospace',
  },
  logArea: {
    flex: 1,
    padding: '10px 12px',
    overflowY: 'auto',
    fontSize: 12,
    fontFamily: 'monospace',
    lineHeight: '1.5',
  },
  logEmpty: {
    color: '#333',
    fontSize: 11,
    textAlign: 'center',
    paddingTop: 30,
    fontStyle: 'italic',
  },
  inputRow: {
    display: 'flex',
    gap: 8,
    padding: '8px 10px',
    borderTop: '1px solid #1a1a1a',
  },
  textarea: {
    flex: 1,
    background: '#0d0d0d',
    border: '1px solid #2a2a2a',
    color: '#cccccc',
    borderRadius: 2,
    padding: '6px 8px',
    fontSize: 12,
    fontFamily: 'monospace',
    resize: 'none',
    outline: 'none',
  },
  sendBtn: {
    alignSelf: 'flex-end',
    padding: '7px 16px',
    background: '#1a3a4a',
    border: '1px solid #2a5a7a',
    color: '#7fdbff',
    borderRadius: 2,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'monospace',
  },
};
