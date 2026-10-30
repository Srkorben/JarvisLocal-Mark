const ANALYTICS_SEEN_KEY = 'openjarvis-analytics-choice-seen';

interface AnalyticsInvitation {
  ready: boolean;
  sharingModalSeen: boolean;
  open: () => void;
  markSharingModalSeen: () => void;
}

/**
 * Mark is a local assistant with no sign-up: the sharing/giveaway dialog is
 * never opened on its own. It stays reachable from the system panel, and
 * analytics remain off unless the user opts in there.
 */
export function offerAnalyticsChoice({
  ready, sharingModalSeen, markSharingModalSeen,
}: AnalyticsInvitation): (() => void) | undefined {
  if (!ready) return;
  if (!sharingModalSeen) markSharingModalSeen();
  localStorage.setItem(ANALYTICS_SEEN_KEY, 'true');
  return undefined;
}
