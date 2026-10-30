import { describe, expect, it } from 'vitest';
import { CONNECTOR_FOCUS, connectorFocus, isMarkOrigin } from './markShell';

describe('Mark shell helpers', () => {
  it('accepts only loopback parents', () => {
    expect(isMarkOrigin('http://127.0.0.1:51234')).toBe(true);
    expect(isMarkOrigin('http://localhost:8765')).toBe(true);
    expect(isMarkOrigin('https://127.0.0.1:1')).toBe(false);
    expect(isMarkOrigin('http://127.0.0.1.evil.com')).toBe(false);
    expect(isMarkOrigin('http://example.com')).toBe(false);
  });

  it('maps the email and calendar tabs to real connector ids', () => {
    expect(connectorFocus('?focus=email')?.ids).toEqual(CONNECTOR_FOCUS.email.ids);
    expect(connectorFocus('?focus=calendar')?.ids).toContain('gcalendar');
    expect(connectorFocus('?focus=calendar')?.ids).toContain('google_tasks');
    expect(connectorFocus('?focus=other')).toBeNull();
    expect(connectorFocus('')).toBeNull();
  });
});
