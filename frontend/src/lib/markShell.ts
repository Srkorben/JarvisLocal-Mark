/**
 * Mark shell mode: this UI running inside Mark's desktop window.
 *
 * Mark (JarvisLocal.exe) loads OpenJarvis at `?shell=mark` inside its own
 * window and drives navigation from its tab bar, so in this mode the UI takes
 * Mark's blue theme, hides its own sidebar navigation and follows
 * `mark:navigate` messages from the parent window. Outside Mark nothing changes.
 */

const SHELL_KEY = 'mark-shell';

function detect(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get('shell') === 'mark') sessionStorage.setItem(SHELL_KEY, '1');
    return window.self !== window.top && sessionStorage.getItem(SHELL_KEY) === '1';
  } catch {
    return false;
  }
}

export const inMarkShell: boolean = detect();

/** Mark only ever runs on loopback; anything else is ignored. */
export function isMarkOrigin(origin: string): boolean {
  return /^http:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?$/.test(origin);
}

/** Connector groups behind Mark's "Correo" and "Calendario y tareas" tabs. */
export const CONNECTOR_FOCUS: Record<string, { title: string; ids: string[] }> = {
  email: {
    title: 'Correo',
    ids: ['gmail', 'gmail_imap', 'imap', 'outlook'],
  },
  calendar: {
    title: 'Calendario, tareas y contactos',
    ids: ['gcalendar', 'google_tasks', 'gcontacts', 'apple_calendar', 'apple_contacts'],
  },
};

export function connectorFocus(search: string): { title: string; ids: string[] } | null {
  const focus = new URLSearchParams(search).get('focus') ?? '';
  return CONNECTOR_FOCUS[focus] ?? null;
}
