import { useEffect } from 'react';

const EVENTS = ['mousemove', 'keydown', 'click', 'touchstart', 'scroll'];

// 閒置登出：minutes 分鐘內沒有任何鍵盤滑鼠操作就呼叫 onIdle。
// 前端只負責「體驗」；真正的保護在後端（每個請求與 refresh 都會檢查 last_active_at）。
export function useIdleLogout(minutes, onIdle, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    let timer;
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(onIdle, minutes * 60 * 1000);
    };
    EVENTS.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    reset();
    return () => {
      clearTimeout(timer);
      EVENTS.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [minutes, onIdle, enabled]);
}
