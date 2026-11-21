import { markdown } from "@codemirror/lang-markdown";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { syntaxHighlighting, HighlightStyle } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { EditorView, keymap, lineNumbers, highlightActiveLine, drawSelection } from "@codemirror/view";

const host = document.querySelector("#editor");
const source = document.querySelector("#source");
const status = document.querySelector("#save-status");
const saveButton = document.querySelector("#save");
const path = document.body.dataset.path;
let revision = document.body.dataset.revision;
let saved = source.value;
let saving = false;
let saveError = null;

const colors = HighlightStyle.define([
  { tag: tags.heading, color: "var(--accent-markdown)", fontWeight: "700" },
  { tag: [tags.strong, tags.emphasis], color: "var(--text)" },
  { tag: [tags.link, tags.url], color: "var(--blue)", textDecoration: "underline" },
  { tag: tags.monospace, color: "var(--code-number)" },
  { tag: tags.quote, color: "var(--muted)", fontStyle: "italic" },
  { tag: tags.processingInstruction, color: "var(--code-keyword)" },
  { tag: tags.content, color: "var(--text)" },
]);

const view = new EditorView({
  doc: source.value,
  parent: host,
  extensions: [
    lineNumbers(),
    highlightActiveLine(),
    drawSelection(),
    history(),
    markdown(),
    syntaxHighlighting(colors),
    EditorView.lineWrapping,
    EditorView.theme({
      "&": { height: "100%", color: "var(--text)", backgroundColor: "var(--bg)", fontSize: "15px" },
      ".cm-scroller": { overflow: "auto", fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace", lineHeight: "1.65" },
      ".cm-gutters": { backgroundColor: "var(--bg)", color: "var(--muted)", border: "none" },
      ".cm-activeLine": { backgroundColor: "var(--hover)" },
      "&.cm-focused": { outline: "none" },
      ".cm-selectionBackground": { backgroundColor: "var(--selected)" },
      ".cm-cursor": { borderLeftColor: "var(--text)" },
    }),
    keymap.of([
      { key: "Mod-s", run: () => { save(); return true; } },
      indentWithTab,
      ...defaultKeymap,
      ...historyKeymap,
    ]),
    EditorView.updateListener.of(update => {
      if (update.docChanged) {
        saveError = null;
        showDirty();
      }
    }),
  ],
});

function showDirty() {
  const dirty = view.state.doc.toString() !== saved;
  status.textContent = saveError || (dirty ? "Unsaved changes" : "All changes saved");
  status.dataset.dirty = saveError ? "error" : dirty ? "true" : "false";
  saveButton.disabled = !dirty || saving;
}

async function save() {
  const text = view.state.doc.toString();
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
    if (response.status === 409) throw new Error("This file changed on disk. Reload to avoid overwriting it.");
    if (!response.ok) throw new Error((await response.text()).trim() || `Save failed (${response.status})`);
    const result = await response.json();
    saved = text;
    revision = result.revision;
    document.body.dataset.revision = revision;
    status.textContent = "Saved";
    status.dataset.dirty = "false";
    saveButton.disabled = view.state.doc.toString() === saved;
  } catch (error) {
    saveError = error.message;
    status.textContent = saveError;
    status.dataset.dirty = "error";
    saveButton.disabled = false;
  } finally {
    saving = false;
    showDirty();
  }
}

saveButton.addEventListener("click", save);
window.addEventListener("beforeunload", event => {
  if (view.state.doc.toString() !== saved) {
    event.preventDefault();
    event.returnValue = "";
  }
});
showDirty();
