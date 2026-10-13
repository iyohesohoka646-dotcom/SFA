// Kept independent of the module bundle so a missing/corrupt bundle is visible.
(() => {
  const failure = (message) => {
    const status = document.getElementById('boot-status');
    if (!status) return;
    status.textContent = message;
    status.setAttribute('role', 'alert');
    document.getElementById('boot-retry').hidden = false;
  };
  window.addEventListener('error', (event) => {
    if (event.target instanceof HTMLScriptElement)
      failure('界面资源未能加载');
    else if (event.target === window) failure('界面启动失败');
  }, true);
  window.addEventListener('unhandledrejection', () => failure('界面启动失败'));
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('boot-retry')?.addEventListener('click', () => location.reload());
    setTimeout(() => failure('界面启动未完成，请重试加载'), 20000);
  }, {once: true});
})();
