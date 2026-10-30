import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { offerAnalyticsChoice } from './analytics-invitation';

const seenKey = 'openjarvis-analytics-choice-seen';
let stored: Map<string, string>;

beforeEach(() => {
  stored = new Map();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

const invitation = (ready: boolean, sharingModalSeen: boolean) => ({
  ready,
  sharingModalSeen,
  open: vi.fn(),
  markSharingModalSeen: vi.fn(),
});

describe('analytics invitation in Mark (local, no sign-up)', () => {
  it('waits for setup before recording anything', () => {
    const request = invitation(false, false);
    offerAnalyticsChoice(request);
    expect(request.markSharingModalSeen).not.toHaveBeenCalled();
    expect(stored.has(seenKey)).toBe(false);
  });

  it('never opens the sharing dialog on its own for new users', () => {
    const request = invitation(true, false);
    offerAnalyticsChoice(request);
    expect(request.open).not.toHaveBeenCalled();
    expect(request.markSharingModalSeen).toHaveBeenCalledOnce();
    expect(stored.get(seenKey)).toBe('true');
  });

  it('never opens it for existing users either', () => {
    const request = invitation(true, true);
    offerAnalyticsChoice(request);
    expect(request.open).not.toHaveBeenCalled();
    expect(request.markSharingModalSeen).not.toHaveBeenCalled();
  });
});
