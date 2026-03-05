// ControlPanel.jsx — 自律活動観察パネル（view-only）
// AI同士の活動ログをリアルタイムで表示する

import { useEffect, useRef } from 'react';

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
 * @param {Array}    props.agents       エージェント一覧
 * @param {Array}    props.activities   活動フィード
 * @param {Array}    props.tasks        タスクキュー
 * @param {string}   props.wsState      WebSocket状態ラベル
 * @param {string}   props.ollamaStatus Ollamaヘルス状態ラベル
 */
export default function ControlPanel({
  agents = [],
  activities = [],
  tasks = [],
  wsState,
  ollamaStatus,
}) {
  const feedRef = useRef(null);

  // 新しいアクティビティが来たら自動スクロール
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [activities]);

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
        <span style={{ ...styles.statusItem, marginLeft: 'auto', color: '#2ecc71' }}>
          🤖 自律稼働中
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
                <div style={{ ...styles.taskAgent, color: AGENT_BADGE_COLORS[t.agent] || '#888' }}>
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
                {t.preview && <div style={styles.taskPreview}>{t.preview}</div>}
              </div>
            ))
          )}
        </div>

        {/* 右: 活動フィード */}
        <div ref={feedRef} style={styles.feed}>
          {activities.length === 0 ? (
            <div style={styles.feedEmpty}>
              AI エージェントの自律活動をここで観察できます...
            </div>
          ) : (
            activities.map((act, i) => (
              <ActivityItem key={i} act={act} agents={agents} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// 活動フィードの各アイテム
function ActivityItem({ act, agents }) {
  const agentName  = (codename) => agents.find(a => a.codename === codename)?.name || codename;
  const agentColor = (codename) => AGENT_BADGE_COLORS[codename] || '#888';

  switch (act.type) {
    case 'autonomous_cycle_start':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>🔄</span>
          <div style={styles.actBody}>
            <span style={{ color: '#7fdbff' }}>サイクル {act.cycle} 開始</span>
            <div style={styles.actSub}>{act.theme}</div>
          </div>
        </div>
      );

    case 'autonomous_trigger':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>⚡</span>
          <div style={styles.actBody}>
            <span style={{ color: '#f39c12' }}>トリガー「{act.keyword}」</span>
            {' → '}
            <span style={{ color: agentColor(act.agent) }}>{agentName(act.agent)}</span>
            <span style={{ color: '#555' }}> に指示</span>
          </div>
        </div>
      );

    case 'autonomous_cycle_done':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>✓</span>
          <div style={styles.actBody}>
            <span style={{ color: '#2ecc71' }}>サイクル {act.cycle} 完了</span>
            {act.triggers?.length > 0 && (
              <span style={{ color: '#555' }}> — 発動: {act.triggers.join(', ')}</span>
            )}
          </div>
        </div>
      );

    case 'autonomous_artifact':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>💾</span>
          <div style={styles.actBody}>
            <span style={{ color: '#2ecc71' }}>成果物保存</span>
            <div style={styles.actSub}>{act.path}</div>
          </div>
        </div>
      );

    case 'task_created':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>📋</span>
          <div style={styles.actBody}>
            <span style={{ color: agentColor(act.agent) }}>{agentName(act.agent)}</span>
            <span style={{ color: '#555' }}> にタスク割当: </span>
            <span style={{ color: '#888' }}>{act.title}</span>
          </div>
        </div>
      );

    case 'task_done':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>✅</span>
          <div style={styles.actBody}>
            <span style={{ color: agentColor(act.agent) }}>{agentName(act.agent)}</span>
            <span style={{ color: '#555' }}> 完了</span>
            {act.preview && <div style={styles.actPreview}>{act.preview}</div>}
          </div>
        </div>
      );

    case 'agent_thinking':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>💭</span>
          <div style={styles.actBody}>
            <span style={{ color: agentColor(act.agent) }}>{agentName(act.agent)}</span>
            <span style={{ color: '#f39c12' }}> 思考中</span>
            {act.detail && <span style={{ color: '#555' }}>: {act.detail}</span>}
          </div>
        </div>
      );

    case 'orchestration_result':
      return (
        <div style={styles.actRow}>
          <span style={styles.actIcon}>🗣</span>
          <div style={styles.actBody}>
            <span style={{ color: agentColor('leader') }}>{agentName('leader')}</span>
            <span style={{ color: '#555' }}> (統合回答)</span>
            {act.reasoning && (
              <div style={{ ...styles.actSub, color: '#444' }}>{act.reasoning}</div>
            )}
            <div style={styles.actPreview}>{act.response}</div>
          </div>
        </div>
      );

    default:
      return null;
  }
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
    padding: '10px',
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
  feed: {
    flex: 1,
    padding: '10px 12px',
    overflowY: 'auto',
    fontSize: 12,
    fontFamily: 'monospace',
    lineHeight: '1.6',
  },
  feedEmpty: {
    color: '#333',
    fontSize: 11,
    textAlign: 'center',
    paddingTop: 30,
    fontStyle: 'italic',
  },
  actRow: {
    display: 'flex',
    gap: 8,
    marginBottom: 8,
    alignItems: 'flex-start',
  },
  actIcon: {
    fontSize: 12,
    flexShrink: 0,
    marginTop: 1,
  },
  actBody: {
    flex: 1,
    fontSize: 11,
    color: '#666',
  },
  actSub: {
    fontSize: 10,
    color: '#555',
    marginTop: 2,
  },
  actPreview: {
    fontSize: 10,
    color: '#666',
    marginTop: 4,
    padding: '4px 6px',
    background: '#0d0d0d',
    border: '1px solid #1a1a1a',
    borderRadius: 2,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    maxHeight: 80,
    overflowY: 'auto',
  },
};
