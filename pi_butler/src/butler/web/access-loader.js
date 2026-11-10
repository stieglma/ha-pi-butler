// Keep startup failures visible even when the editor module cannot load.
const editorUrl = new URL('./access.js?v=0.1.7', document.currentScript.src);
const startupTimeout = setTimeout(() => startupFailed(new Error('Loading the settings script timed out.')), 15000);
function startupFailed(error) {
  clearTimeout(startupTimeout);
  document.getElementById('loading').hidden = true;
  const message = document.getElementById('load-error');
  message.textContent = `Settings could not start: ${error.message} Reload this page to retry.`;
  message.hidden = false;
  const retry = document.getElementById('retry');
  retry.hidden = false;
  retry.onclick = () => location.reload();
}
import(editorUrl.href).then(() => clearTimeout(startupTimeout)).catch(startupFailed);
