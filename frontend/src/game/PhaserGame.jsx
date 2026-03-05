// PhaserGame.jsx — Phaser ゲームの React ラッパー
// Phaser インスタンスのライフサイクルを React に統合する

import { useEffect, useRef } from 'react';
import Phaser from 'phaser';
import OfficeScene from './scenes/OfficeScene';

const GAME_WIDTH  = 900;
const GAME_HEIGHT = 420;

/**
 * @param {object} props
 * @param {Record<string, string>} props.agentStates  エージェントID → 状態文字列
 * @param {Function} [props.onReady]                  ゲーム起動完了時のコールバック
 */
export default function PhaserGame({ agentStates, onReady }) {
  const containerRef = useRef(null);
  const gameRef      = useRef(null);

  // Phaser ゲームの初期化（マウント時のみ）
  useEffect(() => {
    if (!containerRef.current) return;

    const config = {
      type: Phaser.AUTO,
      width: GAME_WIDTH,
      height: GAME_HEIGHT,
      backgroundColor: '#0a0a0a',
      parent: containerRef.current,
      scene: [OfficeScene],
      // ピクセルアート向け設定
      pixelArt: true,
      antialias: false,
      roundPixels: true,
    };

    const game = new Phaser.Game(config);
    gameRef.current = game;

    // シーン起動完了後にコールバックを呼ぶ
    if (onReady) {
      game.events.once('ready', () => onReady(game));
    }

    return () => {
      game.destroy(true);
      gameRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // agentStates 変化時に OfficeScene へ通知
  useEffect(() => {
    const game = gameRef.current;
    if (!game) return;

    // シーンが起動済みかチェックしてから呼ぶ
    const scene = game.scene.getScene('OfficeScene');
    if (scene?.updateAgentStates) {
      scene.updateAgentStates(agentStates);
    }
  }, [agentStates]);

  return (
    <div
      ref={containerRef}
      style={{
        lineHeight: 0,          // 画像下余白を除去
        border: '1px solid #1a1a1a',
        borderBottom: 'none',
      }}
    />
  );
}
