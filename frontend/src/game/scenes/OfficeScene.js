// OfficeScene.js — Phaser.js ピクセルアートオフィスシーン
// プログラム生成のピクセルアートで6エージェントを可視化

import Phaser from 'phaser';

const W = 900;
const H = 420;
const ZONE_W = W / 2;  // 450px
const ZONE_H = H / 3;  // 140px

// 6ゾーン定義（3行 x 2列）
const ZONES = [
  { id: 'detective',  name: '探偵',       label: '調査エリア',     col: 0, row: 0 },
  { id: 'researcher', name: '研究者',     label: '分析エリア',     col: 1, row: 0 },
  { id: 'leader',     name: 'リーダー',   label: 'リーダー室',     col: 0, row: 1 },
  { id: 'engineer',   name: 'エンジニア', label: '作業エリア',     col: 1, row: 1 },
  { id: 'sales',      name: '営業',       label: '物流エリア',     col: 0, row: 2 },
  { id: 'secretary',  name: '秘書',       label: 'スケジュール室', col: 1, row: 2 },
];

// エージェントごとのカラーアイデンティティ
const AGENT_COLORS = {
  detective:  0x9b59b6,
  researcher: 0x3498db,
  leader:     0xe74c3c,
  engineer:   0x2ecc71,
  sales:      0xf39c12,
  secretary:  0x1abc9c,
};

// ステータスラベル（日本語）
const STATE_LABELS = {
  idle:          'idle',
  thinking:      '思考中...',
  busy:          '作業中',
  working:       '作業中',
  communicating: '連携中',
  error:         'エラー',
};

// ステータスカラー（16進数文字列）
const STATE_COLORS_HEX = {
  idle:          '#555555',
  thinking:      '#f39c12',
  busy:          '#e74c3c',
  working:       '#e74c3c',
  communicating: '#3498db',
  error:         '#ff4444',
};

export default class OfficeScene extends Phaser.Scene {
  constructor() {
    super({ key: 'OfficeScene' });
    this.agentObjects = {};
    this.agentStates  = {};
  }

  create() {
    this._drawFloor();
    this._drawZoneBorders();
    ZONES.forEach(zone => this._createAgentObject(zone));
  }

  // チェッカーボードタイルパターンの床
  _drawFloor() {
    const g = this.add.graphics();
    for (let x = 0; x < W; x += 16) {
      for (let y = 0; y < H; y += 16) {
        const dark = ((x / 16 + y / 16) % 2 === 0);
        g.fillStyle(dark ? 0x0d0d0d : 0x111111, 1);
        g.fillRect(x, y, 16, 16);
      }
    }
  }

  // ゾーン境界線とラベルを描画
  _drawZoneBorders() {
    const g = this.add.graphics();
    g.lineStyle(1, 0x2a2a2a, 1);

    ZONES.forEach(({ col, row, label }) => {
      const x = col * ZONE_W;
      const y = row * ZONE_H;
      g.strokeRect(x, y, ZONE_W, ZONE_H);
      this.add.text(x + 10, y + 8, label, {
        fontSize: '9px',
        color: '#3a3a3a',
        fontFamily: 'monospace',
      });
    });
  }

  // 各エージェントのゲームオブジェクトを生成
  _createAgentObject(zone) {
    const bx = zone.col * ZONE_W;
    const by = zone.row * ZONE_H;
    const cx = bx + ZONE_W / 2;
    const cy = by + ZONE_H / 2;
    const color = AGENT_COLORS[zone.id] || 0x7fdbff;

    // エラーオーバーレイ（デフォルト非表示）
    const errorOverlay = this.add.graphics();
    errorOverlay.fillStyle(0xff2222, 1);
    errorOverlay.fillRect(bx + 2, by + 2, ZONE_W - 4, ZONE_H - 4);
    errorOverlay.setAlpha(0).setVisible(false);

    // デスク（静的 — 座標を絶対値で描画）
    const desk = this.add.graphics();
    _drawDesk(desk, cx, cy + 18);

    // エージェントキャラクター（(0,0) 中心で描画 → setPosition で配置）
    const character = this.add.graphics();
    character.setPosition(cx, cy - 14);
    _drawCharacter(character, color);

    // エージェント名テキスト
    const nameText = this.add.text(cx, cy + 46, zone.name, {
      fontSize: '11px',
      color: '#888888',
      fontFamily: 'monospace',
    }).setOrigin(0.5);

    // ステータステキスト
    const statusText = this.add.text(cx, cy + 59, 'idle', {
      fontSize: '9px',
      color: '#555555',
      fontFamily: 'monospace',
    }).setOrigin(0.5);

    // 思考バブルテキスト（thinking状態で使用）
    const bubbleText = this.add.text(cx, by + 28, '.', {
      fontSize: '14px',
      color: '#f39c12',
      fontFamily: 'monospace',
    }).setOrigin(0.5).setVisible(false);

    this.agentObjects[zone.id] = {
      zone, bx, by, cx, cy,
      errorOverlay, desk, character,
      nameText, statusText, bubbleText,
      currentState: 'idle',
    };
  }

  // React側からエージェント状態を受け取る
  updateAgentStates(states) {
    this.agentStates = states || {};
    Object.entries(this.agentObjects).forEach(([id, obj]) => {
      const state = this.agentStates[id] || 'idle';
      if (state !== obj.currentState) {
        this._applyState(obj, state);
        obj.currentState = state;
      }
    });
  }

  // 状態に応じてビジュアルを切り替える
  _applyState(obj, state) {
    const { character, statusText, bubbleText, errorOverlay, cx, cy } = obj;

    // 既存のtweenをリセット
    this.tweens.killTweensOf(character);
    this.tweens.killTweensOf(bubbleText);
    this.tweens.killTweensOf(errorOverlay);

    character.setAlpha(1);
    character.setPosition(cx, cy - 14);
    bubbleText.setVisible(false);
    errorOverlay.setVisible(false).setAlpha(0);

    statusText.setText(STATE_LABELS[state] || state);
    statusText.setColor(STATE_COLORS_HEX[state] || '#555555');

    switch (state) {
      case 'thinking':
        bubbleText.setVisible(true).setAlpha(1);
        this.tweens.add({
          targets: bubbleText,
          alpha: 0.15,
          duration: 650,
          yoyo: true,
          repeat: -1,
        });
        break;

      case 'busy':
      case 'working':
        // タイピング振動（X軸に小さく揺らす）
        this.tweens.add({
          targets: character,
          x: cx + 2,
          duration: 75,
          yoyo: true,
          repeat: -1,
          ease: 'Stepped',
        });
        break;

      case 'communicating':
        // 点滅でエージェント間通信を表現
        this.tweens.add({
          targets: character,
          alpha: 0.35,
          duration: 320,
          yoyo: true,
          repeat: -1,
        });
        break;

      case 'error':
        errorOverlay.setVisible(true);
        this.tweens.add({
          targets: errorOverlay,
          alpha: 0.28,
          duration: 400,
          yoyo: true,
          repeat: -1,
        });
        break;
    }
  }

  update() {
    // thinking状態のドットアニメーション（毎フレーム更新）
    const dotCount = 1 + (Math.floor(this.time.now / 380) % 3);
    const dots = '.'.repeat(dotCount);

    Object.values(this.agentObjects).forEach(obj => {
      if (obj.currentState === 'thinking') {
        obj.bubbleText.setText(dots);
      }
    });
  }
}

// ===== ピクセルアート描画ヘルパー =====

// デスクを絶対座標で描画
function _drawDesk(g, x, y) {
  // 天板
  g.fillStyle(0x5a3a28, 1);
  g.fillRect(x - 34, y - 4, 68, 8);
  // 脚
  g.fillStyle(0x3a2218, 1);
  g.fillRect(x - 30, y + 4, 6, 10);
  g.fillRect(x + 24, y + 4, 6, 10);
  // モニター本体
  g.fillStyle(0x111111, 1);
  g.fillRect(x - 15, y - 24, 30, 20);
  // 画面（青みがかったグロー）
  g.fillStyle(0x143a5a, 1);
  g.fillRect(x - 13, y - 22, 26, 16);
  // スキャンライン（1px明るいライン）
  g.fillStyle(0x1a4a6a, 1);
  g.fillRect(x - 13, y - 17, 26, 1);
  g.fillRect(x - 13, y - 12, 26, 1);
  // モニタースタンド
  g.fillStyle(0x333333, 1);
  g.fillRect(x - 3, y - 4, 6, 4);
}

// キャラクターを (0,0) 中心として描画（tween用）
function _drawCharacter(g, color) {
  // 頭
  g.fillStyle(color, 1);
  g.fillRect(-8, -20, 16, 14);
  // 目（白い2ピクセル）
  g.fillStyle(0xffffff, 1);
  g.fillRect(-5, -15, 3, 3);
  g.fillRect(2, -15, 3, 3);
  // 体
  g.fillStyle(0x2c3e50, 1);
  g.fillRect(-10, -6, 20, 14);
  // 腕
  g.fillStyle(color, 1);
  g.fillRect(-18, -4, 8, 10);
  g.fillRect(10, -4, 8, 10);
  // 手（先端を少し明るく）
  g.fillStyle(0xffffff, 0.3);
  g.fillRect(-18, 2, 8, 4);
  g.fillRect(10, 2, 8, 4);
}
