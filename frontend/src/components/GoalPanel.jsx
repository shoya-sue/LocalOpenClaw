// GoalPanel.jsx — ゴール管理パネル
// goals.yaml で定義されたゴールの達成状態を表示し、手動チェックを実行できる

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8080';

// ゴールステータスに対応する表示色
const STATUS_COLORS = {
  pending:     '#666',
  in_progress: '#f39c12',
  completed:   '#2ecc71',
  failed:      '#e74c3c',
};

// ゴールステータスに対応するラベル
const STATUS_LABELS = {
  pending:     '未着手',
  in_progress: '実行中',
  completed:   '✓ 達成',
  failed:      '✗ 失敗',
};

/**
 * @param {object}   props
 * @param {Array}    props.goals        ゴール一覧
 * @param {Function} props.onCheckGoal  ゴールチェック要求コールバック
 * @param {Set}      props.checkingIds  チェック中のゴールIDセット
 */
export default function GoalPanel({ goals = [], onCheckGoal, checkingIds = new Set() }) {
  if (goals.length === 0) {
    return (
      <div style={styles.panel}>
        <div style={styles.header}>
          <span style={styles.headerLabel}>🎯 ゴール管理</span>
        </div>
        <div style={styles.emptyHint}>goals.yaml にゴールが定義されていません</div>
      </div>
    );
  }

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <span style={styles.headerLabel}>🎯 ゴール管理</span>
        <span style={styles.goalCount}>{goals.length} 件</span>
      </div>

      <div style={styles.goalList}>
        {goals.map(goal => (
          <GoalCard
            key={goal.id}
            goal={goal}
            onCheck={() => onCheckGoal(goal.id)}
            isChecking={checkingIds.has(goal.id)}
          />
        ))}
      </div>
    </div>
  );
}

function GoalCard({ goal, onCheck, isChecking }) {
  const statusColor = STATUS_COLORS[goal.status] || '#666';
  const statusLabel = STATUS_LABELS[goal.status] || goal.status;

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <span style={styles.goalId}>{goal.id}</span>
        <span style={{ ...styles.statusBadge, color: statusColor }}>
          {isChecking ? '⟳ 判定中' : statusLabel}
        </span>
      </div>

      <div style={styles.description}>{goal.description}</div>

      <div style={styles.meta}>
        <span style={styles.metaItem}>
          サイクル: {goal.cycles_done}/{goal.max_cycles}
        </span>
        {goal.check_file && (
          <span style={styles.metaItem}>対象: {goal.check_file}</span>
        )}
      </div>

      {goal.status === 'completed' && (
        <div style={styles.achievedBadge}>✓ ゴール達成</div>
      )}

      {goal.report_path && (
        <a
          href={`${BACKEND_URL}/goals/${goal.id}/report`}
          target="_blank"
          rel="noopener noreferrer"
          style={styles.reportLink}
        >
          📄 レポートを表示
        </a>
      )}

      <button
        style={{
          ...styles.checkButton,
          opacity: isChecking ? 0.5 : 1,
          cursor: isChecking ? 'not-allowed' : 'pointer',
        }}
        onClick={onCheck}
        disabled={isChecking}
      >
        {isChecking ? '判定中...' : '達成判定を実行'}
      </button>
    </div>
  );
}

// ===== スタイル定数 =====

const styles = {
  panel: {
    border: '1px solid #1a1a1a',
    borderTop: 'none',
    background: '#080808',
    padding: '10px 14px 14px',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
    borderBottom: '1px solid #1a1a1a',
    paddingBottom: 8,
  },
  headerLabel: {
    fontSize: 12,
    color: '#7fdbff',
    fontWeight: 'bold',
  },
  goalCount: {
    fontSize: 10,
    color: '#444',
  },
  emptyHint: {
    fontSize: 11,
    color: '#333',
    fontStyle: 'italic',
    padding: '10px 0',
  },
  goalList: {
    display: 'flex',
    gap: 10,
    flexWrap: 'wrap',
  },
  card: {
    width: 260,
    border: '1px solid #1e1e1e',
    borderRadius: 3,
    padding: '8px 10px',
    background: '#0a0a0a',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 5,
  },
  goalId: {
    fontSize: 9,
    color: '#444',
    fontFamily: 'monospace',
  },
  statusBadge: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  description: {
    fontSize: 11,
    color: '#888',
    marginBottom: 6,
    lineHeight: '1.4',
  },
  meta: {
    display: 'flex',
    gap: 8,
    marginBottom: 8,
  },
  metaItem: {
    fontSize: 9,
    color: '#444',
    fontFamily: 'monospace',
  },
  achievedBadge: {
    fontSize: 10,
    color: '#2ecc71',
    background: '#0d2010',
    border: '1px solid #1a4020',
    borderRadius: 2,
    padding: '2px 6px',
    marginBottom: 6,
    display: 'inline-block',
  },
  checkButton: {
    width: '100%',
    padding: '5px 0',
    background: 'transparent',
    border: '1px solid #2a2a2a',
    borderRadius: 2,
    color: '#7fdbff',
    fontSize: 10,
    fontFamily: 'monospace',
  },
  reportLink: {
    display: 'block',
    fontSize: 10,
    color: '#f39c12',
    textDecoration: 'none',
    marginBottom: 6,
    fontFamily: 'monospace',
  },
};
