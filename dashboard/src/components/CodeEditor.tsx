import React, { useEffect, useRef } from 'react';
import { EditorState, Extension } from '@codemirror/state';
import { EditorView, lineNumbers, highlightActiveLine, highlightActiveLineGutter, Decoration, keymap } from '@codemirror/view';
import { HighlightStyle, syntaxHighlighting, foldGutter, foldKeymap, bracketMatching } from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { defaultKeymap } from '@codemirror/commands';
import { tags as t } from '@lezer/highlight';
import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { json } from '@codemirror/lang-json';
import { css } from '@codemirror/lang-css';
import { html } from '@codemirror/lang-html';
import { markdown } from '@codemirror/lang-markdown';
import { sql } from '@codemirror/lang-sql';
import { yaml } from '@codemirror/lang-yaml';
import { xml } from '@codemirror/lang-xml';
import { java } from '@codemirror/lang-java';
import { rust } from '@codemirror/lang-rust';
import { go } from '@codemirror/lang-go';
import { cpp } from '@codemirror/lang-cpp';
import { php } from '@codemirror/lang-php';

/** Salt okunur kod editörü (CodeMirror 6): satır numarası, sözdizimi renkleri, katlama, arama (Ctrl+F), parantez eşleme. Renkler panonun tema değişkenlerinden gelir. */
const languageFor = (path: string): Extension[] => {
  const name = (path.split('/').pop() || '').toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() || '' : '';
  switch (ext) {
    case 'ts': return [javascript({ typescript: true })];
    case 'tsx': return [javascript({ typescript: true, jsx: true })];
    case 'js': case 'mjs': case 'cjs': return [javascript()];
    case 'jsx': return [javascript({ jsx: true })];
    case 'py': return [python()];
    case 'json': case 'jsonc': return [json()];
    case 'css': case 'scss': return [css()];
    case 'html': case 'htm': case 'vue': return [html()];
    case 'xml': case 'svg': return [xml()];
    case 'md': case 'markdown': return [markdown()];
    case 'sql': return [sql()];
    case 'yml': case 'yaml': return [yaml()];
    case 'java': case 'kt': return [java()];
    case 'rs': return [rust()];
    case 'go': return [go()];
    case 'c': case 'h': case 'cpp': case 'cc': case 'hpp': case 'cs': return [cpp()];
    case 'php': return [php()];
    default: return [];
  }
};

const highlight = HighlightStyle.define([
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: 'var(--ink3)', fontStyle: 'italic' },
  { tag: [t.keyword, t.modifier, t.operatorKeyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword], color: 'var(--ac)', fontWeight: '600' },
  { tag: [t.string, t.special(t.string), t.regexp], color: 'var(--ok)' },
  { tag: [t.number, t.bool, t.null, t.atom], color: 'var(--warn)' },
  { tag: [t.typeName, t.className, t.namespace, t.tagName], color: 'var(--info)' },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.labelName], color: 'var(--info)' },
  { tag: [t.propertyName, t.attributeName], color: 'var(--ink)' },
  { tag: [t.heading, t.strong], fontWeight: '700', color: 'var(--ink)' },
  { tag: [t.link, t.url], color: 'var(--ac)', textDecoration: 'underline' },
  { tag: [t.invalid], color: 'var(--err)' },
  { tag: [t.punctuation, t.operator, t.bracket], color: 'var(--ink2)' },
]);

const theme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'transparent', color: 'var(--ink)', fontSize: '12.5px' },
  '.cm-scroller': { fontFamily: "ui-monospace, SFMono-Regular, 'JetBrains Mono', Menlo, Consolas, monospace", lineHeight: '19px' },
  '.cm-content': { caretColor: 'transparent', padding: '8px 0' },
  '.cm-gutters': { backgroundColor: 'var(--sunk)', color: 'var(--ink3)', border: 'none', borderRight: '1px solid var(--line)' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--ac) 7%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in srgb, var(--ac) 12%, transparent)', color: 'var(--ink)' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection': { backgroundColor: 'color-mix(in srgb, var(--ac) 28%, transparent) !important' },
  '.cm-searchMatch': { backgroundColor: 'color-mix(in srgb, var(--warn) 30%, transparent)' },
  '.cm-panels': { backgroundColor: 'var(--panel2)', color: 'var(--ink)', borderTop: '1px solid var(--line)' },
  '.cm-panels input, .cm-panels button': { fontSize: '12px' },
  '.cm-targetLine': { backgroundColor: 'color-mix(in srgb, var(--warn) 22%, transparent)' },
  '.cm-foldPlaceholder': { backgroundColor: 'var(--panel2)', border: '1px solid var(--line)', color: 'var(--ink3)' },
});

const targetLine = Decoration.line({ class: 'cm-targetLine' });

const CodeEditor: React.FC<{ text: string; path: string; line?: number }> = ({ text, path, line }) => {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return undefined;
    const exts: Extension[] = [
      lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(), foldGutter(), bracketMatching(), highlightSelectionMatches(),
      syntaxHighlighting(highlight), theme, ...languageFor(path),
      EditorState.readOnly.of(true), EditorView.editable.of(false),
      keymap.of([...searchKeymap, ...foldKeymap, ...defaultKeymap]),
    ];
    const probe = EditorState.create({ doc: text });
    const pos = line && line >= 1 && line <= probe.doc.lines ? probe.doc.line(line).from : null;
    if (pos !== null) exts.push(EditorView.decorations.of(Decoration.set([targetLine.range(pos)] as never)));
    const view = new EditorView({ state: EditorState.create({ doc: text, extensions: exts, selection: pos !== null ? { anchor: pos } : undefined }), parent: host.current });
    if (pos !== null) view.dispatch({ effects: EditorView.scrollIntoView(pos, { y: 'center' }) });
    return () => view.destroy();
  }, [text, path, line]);
  return <div ref={host} className="flex-1 min-h-0 overflow-hidden bg-sunk/50" />;
};

export default CodeEditor;
