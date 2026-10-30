import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useAppStore } from '../lib/store';
import { inMarkShell, isMarkOrigin } from '../lib/markShell';

/**
 * Lets Mark's tab bar drive this UI when it runs inside Mark's window:
 * `{type: 'mark:navigate', path, research?}` moves to a page (and can toggle
 * Deep Research); every route change is reported back as `mark:route`.
 */
export function MarkShellBridge() {
  const navigate = useNavigate();
  const location = useLocation();
  const setDeepResearch = useAppStore((s) => s.setDeepResearch);

  useEffect(() => {
    if (!inMarkShell) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window.parent || !isMarkOrigin(event.origin)) return;
      const data = event.data as { type?: string; path?: unknown; research?: unknown };
      if (data?.type !== 'mark:navigate' || typeof data.path !== 'string') return;
      if (!data.path.startsWith('/') || data.path.startsWith('//')) return;
      if (typeof data.research === 'boolean') setDeepResearch(data.research);
      navigate(data.path);
    };
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ type: 'mark:ready' }, '*');
    return () => window.removeEventListener('message', onMessage);
  }, [navigate, setDeepResearch]);

  useEffect(() => {
    if (!inMarkShell) return;
    window.parent.postMessage(
      { type: 'mark:route', path: location.pathname + location.search },
      '*',
    );
  }, [location.pathname, location.search]);

  return null;
}
