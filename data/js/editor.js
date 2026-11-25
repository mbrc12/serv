const body = document.body;
const host = document.querySelector("#editor");
const source = document.querySelector("#source");
const status = document.querySelector("#save-status");
const saveButton = document.querySelector("#save");
const path = body.dataset.path;
const cdnBase = body.dataset.monacoBase;
let revision = body.dataset.revision;
let saved = source.value;
let editor = null;
let saving = false;
let saveError = null;

window.MonacoEnvironment = {
  getWorkerUrl() {
    const asset = `${cdnBase}/assets/editor.worker-_vAIFJDs.js`;
    const bootstrap = `import(${JSON.stringify(asset)});`;
    return URL.createObjectURL(new Blob([bootstrap], { type: "text/javascript" }));
  },
};

require.config({ paths: { vs: cdnBase } });
require(["vs/editor/editor.main"], initializeEditor, error => {
  status.textContent = `Could not load Monaco from the CDN: ${error.message || error}`;
  status.dataset.dirty = "error";
});

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

function initializeEditor() {
  const text = themeColor("text");
  const muted = themeColor("muted");
  const themeColors = {
    "editor.background": themeColor("bg"),
    "editor.foreground": text,
    "editorLineNumber.foreground": muted,
    "editorLineNumber.activeForeground": text,
    "editor.selectionBackground": themeColor("selected"),
    "editor.inactiveSelectionBackground": themeColor("selected"),
    "editor.lineHighlightBackground": themeColor("hover"),
    "editorCursor.foreground": text,
    "editorGutter.background": themeColor("bg"),
    "editorIndentGuide.background": themeColor("border"),
    "editorWidget.background": themeColor("hover"),
    "editorWidget.border": themeColor("border"),
  };
  monaco.editor.defineTheme("serv-theme", {
    base: "vs",
    inherit: true,
    rules: [
      { token: "comment", foreground: muted, fontStyle: "italic" },
      { token: "string", foreground: themeColor("code-string") },
      { token: "keyword", foreground: themeColor("code-keyword") },
      { token: "markup.heading", foreground: themeColor("accent-markdown"), fontStyle: "bold" },
      { token: "markup.bold", foreground: text, fontStyle: "bold" },
      { token: "markup.italic", foreground: text, fontStyle: "italic" },
      { token: "markup.underline.link", foreground: themeColor("blue") },
    ],
    colors: themeColors,
  });
  editor = monaco.editor.create(host, {
    value: source.value,
    language: "markdown",
    theme: "serv-theme",
    automaticLayout: true,
    wordWrap: "on",
    scrollBeyondLastLine: false,
    lineNumbers: "on",
    minimap: { enabled: false },
    fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
    fontSize: 15,
    lineHeight: 25,
    tabSize: 2,
    insertSpaces: true,
    padding: { top: 16, bottom: 16 },
    renderLineHighlight: "line",
  });
  editor.onDidChangeModelContent(() => {
    saveError = null;
    showDirty();
  });
  installPlainTextClipboardHandlers();
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, save);
  saveButton.addEventListener("click", save);
  window.addEventListener("beforeunload", event => {
    if (editor.getValue() !== saved) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  showDirty();
  editor.focus();
}

function installPlainTextClipboardHandlers() {
  const node = editor.getDomNode();
  node.addEventListener("paste", event => {
    const text = event.clipboardData?.getData("text/plain");
    const selection = editor.getSelection();
    if (text && selection) insertPlainText(event, selection, text, "paste");
  }, true);
  node.addEventListener("drop", event => {
    const text = event.dataTransfer?.getData("text/plain");
    const target = editor.getTargetAtClientPoint(event.clientX, event.clientY);
    const position = target?.position;
    if (text && position) {
      const cursor = new monaco.Range(
        position.lineNumber, position.column, position.lineNumber, position.column
      );
      insertPlainText(event, cursor, text, "drop");
    }
  }, true);
}

function insertPlainText(event, range, text, source) {
  event.preventDefault();
  event.stopImmediatePropagation();
  const model = editor.getModel();
  const offset = model.getOffsetAt(range.getStartPosition());
  if (!editor.executeEdits(source, [{ range, text, forceMoveMarkers: true }])) return;
  editor.setPosition(model.getPositionAt(offset + text.length));
  editor.focus();
}

function showDirty() {
  if (!editor) return;
  const dirty = editor.getValue() !== saved;
  status.textContent = saveError || (dirty ? "Unsaved changes" : "All changes saved");
  status.dataset.dirty = saveError ? "error" : dirty ? "true" : "false";
  saveButton.disabled = !dirty || saving;
}

async function save() {
  if (!editor) return;
  const text = editor.getValue();
  if (saving || text === saved) return;
  saving = true;
  saveError = null;
  saveButton.disabled = true;
  status.textContent = "Saving…";
  try {
    const response = await fetch("/__serv__/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, text, revision }),
    });
    if (response.status === 409) {
      throw new Error("This file changed on disk. Reload to avoid overwriting it.");
    }
    if (!response.ok) {
      throw new Error((await response.text()).trim() || `Save failed (${response.status})`);
    }
    const result = await response.json();
    saved = text;
    revision = result.revision;
    body.dataset.revision = revision;
  } catch (error) {
    saveError = error.message;
  } finally {
    saving = false;
    showDirty();
  }
}
