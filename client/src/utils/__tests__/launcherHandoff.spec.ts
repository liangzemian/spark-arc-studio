import { beforeEach, describe, expect, it } from 'vitest';
import {
  attachLauncherOrigin,
  buildLauncherReturnUrl,
  consumeLauncherStartupHintsFromUrl,
  getLauncherTargetForServer,
  persistLauncherResume,
  readLauncherOriginFromUrl,
  readLauncherResume,
} from '../launcherHandoff';

const resumeKey = 'spark_launcher_pending_resume';
const serverBase = 'https://server.example';

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('启动器跳转协议', () => {
  it.each(['javascript:alert(1)', 'data:text/html,test', 'file:///tmp/test', 'blob:https://server.example/id', 'tauri://evil', 'tauri://localhost:123', 'https://user:password@server.example'])('拒绝危险或非预期地址 %s', (url) => {
    expect(readLauncherOriginFromUrl(`${serverBase}/?spark_launcher_origin=${encodeURIComponent(url)}`)).toBe('');
    expect(buildLauncherReturnUrl({ launcherOrigin: url })).toBe('');
    expect(attachLauncherOrigin(url, serverBase)).toBe('');
  });

  it.each(['https://launcher.example/', 'http://127.0.0.1:6688/', 'http://tauri.localhost/', 'tauri://localhost'])('保留合法启动器地址 %s', (origin) => {
    const result = buildLauncherReturnUrl({ launcherOrigin: origin, serverBase, resumeUrl: `${serverBase}/projects/demo` });
    expect(new URL(result).searchParams.get('spark_resume_url')).toBe(`${serverBase}/projects/demo`);
    expect(readLauncherOriginFromUrl(`${serverBase}/?spark_launcher_origin=${encodeURIComponent(origin)}`)).toBe(new URL(origin).toString());
  });
});

describe('恢复地址持久化', () => {
  it('写入前拒绝危险恢复地址且保留其他配置', () => {
    localStorage.setItem('spark_session_token', 'fake-session');
    persistLauncherResume({ serverBase, resumeUrl: 'javascript:alert(1)', reason: 'offline', capturedAt: 1 });
    expect(localStorage.getItem(resumeKey)).toBeNull();
    expect(localStorage.getItem('spark_session_token')).toBe('fake-session');
  });

  it('清理旧版本遗留的危险恢复地址', () => {
    localStorage.setItem(resumeKey, JSON.stringify({ serverBase, resumeUrl: 'javascript:alert(1)' }));
    expect(readLauncherResume()).toBeNull();
    expect(localStorage.getItem(resumeKey)).toBeNull();
    expect(new URL(getLauncherTargetForServer(serverBase, 'tauri://localhost')).origin).toBe(serverBase);
  });

  it('保留合法恢复路径、查询和语言参数', () => {
    const resumeUrl = `${serverBase}/studio?project=demo#/editor`;
    persistLauncherResume({ serverBase, resumeUrl, reason: 'offline', capturedAt: 1 });
    expect(readLauncherResume()?.resumeUrl).toBe(resumeUrl);
    const target = new URL(getLauncherTargetForServer(serverBase, 'tauri://localhost'));
    expect(target.pathname).toBe('/studio');
    expect(target.searchParams.get('project')).toBe('demo');
    expect(target.searchParams.get('spark_launcher_origin')).toBe('tauri://localhost');
    expect(target.hash).toBe('#/editor');
  });

  it('启动参数中的危险恢复地址不会落盘', () => {
    window.history.replaceState(null, '', `/?spark_server=${encodeURIComponent(serverBase)}&spark_resume_url=${encodeURIComponent('javascript:alert(1)')}`);
    const hints = consumeLauncherStartupHintsFromUrl();
    expect(hints?.resumeUrl).toBe('');
    expect(localStorage.getItem(resumeKey)).toBeNull();
    expect(window.location.search).toBe('');
  });
});
