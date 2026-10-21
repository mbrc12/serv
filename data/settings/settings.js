// All mutations are serialized: a slower response can never overwrite a newer save.
// Dirty fields are retained across responses, including rejected edits.
const CDN = 'https://cdn.jsdelivr.net/npm/@shoelace-style/shoelace@2.20.1/cdn';
const $ = id => document.getElementById(id);
const bindings = new Map();
const refreshers = [];
const timers = new Map();
const token = new URLSearchParams(location.hash.slice(1)).get('token');
let state;
let queue = Promise.resolve();
let pending = 0;
let lastMessage = 'All changes saved';
let sequence = 0;

const theme = matchMedia('(prefers-color-scheme: dark)');
const setTheme = () => document.documentElement.classList.toggle('sl-theme-dark', theme.matches);
setTheme();
theme.addEventListener('change', setTheme);

function preserveSectionLinks() {
  if (!token) return;
  document.querySelectorAll('[data-section]').forEach(link => {
    const fragment = new URLSearchParams({ token, section: link.dataset.section });
    link.href = `#${fragment}`;
    link.addEventListener('click', event => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = document.getElementById(link.dataset.section);
      if (!target) return;
      event.preventDefault();
      if (location.hash !== link.hash) history.pushState(null, '', link.hash);
      target.scrollIntoView();
      target.focus({ preventScroll: true });
    });
  });
}

function scrollToSection() {
  const section = new URLSearchParams(location.hash.slice(1)).get('section');
  const target = section && document.getElementById(section);
  if (target) {
    target.scrollIntoView();
    target.focus({ preventScroll: true });
  }
}

preserveSectionLinks();
window.addEventListener('hashchange', scrollToSection);
window.addEventListener('popstate', scrollToSection);
// Fragments are not sent in HTTP requests. Keep this one so reload/retry works;
// never copy the token into navigation links, persistent storage, or logs.
$('reload').addEventListener('click', () => window.location.reload());
$('settings-form').addEventListener('submit', event => event.preventDefault());

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function configValue(key) {
  return key.split('.').reduce((value, part) => value?.[part], state.config);
}

async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'omit',
      signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw new Error('Authorization expired. Reopen Settings from serv.');
      }
      const detail = typeof data?.error === 'string' ? data.error :
        typeof data?.detail === 'string' ? data.detail : `Request failed (${response.status}).`;
      throw new Error(detail);
    }
    if (!data || typeof data !== 'object') throw new Error('The server returned an invalid response.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('The request timed out; the change may have reached the server. Edit again to retry.');
    }
    if (error instanceof TypeError) throw new Error('Cannot reach serv. Check that it is running, then edit again to retry.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function checkSettings(data) {
  if (!data.config || !data.config.server || !data.config.type || !data.config.layout ||
      !data.config.cache || !Array.isArray(data.schemes) || !data.labels || !data.fonts ||
      !Array.isArray(data.fonts.reading) || !Array.isArray(data.fonts.mono)) {
    throw new Error('The server returned incomplete settings. Reopen Settings or try again.');
  }
  return data;
}

function globalStatus() {
  const errors = [...bindings.values()].filter(binding => binding.error);
  const dirty = [...bindings.values()].some(binding => binding.dirty);
  const status = $('save-status');
  if (errors.length) {
    status.dataset.state = 'error';
    status.textContent = `${errors.length} ${errors.length === 1 ? 'setting needs' : 'settings need'} attention. See the messages below.`;
  } else if (pending || timers.size) {
    status.dataset.state = 'saving';
    status.textContent = 'Saving changes…';
  } else if (dirty) {
    status.dataset.state = 'editing';
    status.textContent = 'Changes not saved yet';
  } else {
    status.dataset.state = 'saved';
    status.textContent = lastMessage;
  }
}

function feedback(binding, message = '', error = false) {
  binding.error = error;
  binding.status.textContent = message;
  binding.status.dataset.state = error ? 'error' : '';
  binding.control?.setAttribute('aria-invalid', String(error));
  // Shoelace forwards custom validity to its native form control.
  binding.control?.setCustomValidity?.(error ? message : '');
  globalStatus();
}

function reconcile(data) {
  state = checkSettings(data);
  for (const binding of bindings.values()) {
    if (!binding.dirty) binding.write(binding.get());
  }
  for (const refresh of refreshers) refresh();
  const port = state.config.server.port;
  $('connection-note').textContent = `File server is running on port ${state.active_port}. Configured port: ${port}. Changing the configured port requires a restart. This settings UI uses a separate, temporary (ephemeral) port, ${location.port || (location.protocol === 'https:' ? '443' : '80')}; it does not change your file-server port.`;
  $('config-path').textContent = state.config_path || 'Configuration path is not available.';
}

function schedule(binding) {
  clearTimeout(timers.get(binding.key));
  timers.set(binding.key, setTimeout(() => {
    timers.delete(binding.key);
    persist(binding);
  }, 650));
  globalStatus();
}

function edited(binding, immediate = false) {
  binding.revision += 1;
  binding.dirty = true;
  feedback(binding, 'Not saved yet');
  if (immediate) persist(binding);
  else schedule(binding);
}

function persist(binding) {
  clearTimeout(timers.get(binding.key));
  timers.delete(binding.key);
  if (!binding.dirty || binding.queuedRevision === binding.revision) {
    globalStatus();
    return;
  }
  let value;
  try {
    value = binding.read();
  } catch (error) {
    feedback(binding, `${error.message} Your edit has not been saved.`, true);
    return;
  }
  const revision = binding.revision;
  binding.queuedRevision = revision;
  pending += 1;
  feedback(binding, 'Saving…');
  queue = queue.then(async () => {
    // Coalesce edits that were superseded before their request began.
    if (revision !== binding.revision) return;
    try {
      const response = await api(binding.endpoint || '/api/settings', binding.body ? binding.body(value) : { key: binding.key, value });
      if (!binding.endpoint) checkSettings(response);
      if (revision === binding.revision) {
        binding.dirty = false;
        feedback(binding, 'Saved');
      }
      if (binding.endpoint) {
        if (typeof response.autostart !== 'boolean') throw new Error('Invalid startup response. Edit again to retry.');
        state.autostart = response.autostart;
        if (!binding.dirty) binding.write(response.autostart);
      } else {
        reconcile(response);
      }
      lastMessage = 'All changes saved';
    } catch (error) {
      if (revision === binding.revision) {
        binding.dirty = true;
        // Permit retrying the same value on blur, Enter, or another edit.
        binding.queuedRevision = -1;
        feedback(binding, error.message, true);
      }
    }
  }).catch(() => {
    // Keep the queue usable even if an unexpected UI error occurs.
    binding.dirty = true;
    binding.queuedRevision = -1;
    feedback(binding, 'Could not update this setting. Edit again to retry.', true);
  }).finally(() => {
    pending -= 1;
    globalStatus();
  });
}

function bind({ key, control, status, read, write, get, endpoint, body }) {
  const binding = {
    key, control, status, read, write, endpoint, body,
    get: get || (() => configValue(key)),
    revision: 0, queuedRevision: -1, dirty: false, error: false,
  };
  bindings.set(key, binding);
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');
  control?.setAttribute('aria-describedby', status.id);
  write(binding.get());
  return binding;
}

function field(parent, label, key, { help, type = 'text', read, get, write, ...attributes } = {}) {
  const wrapper = node('div', undefined, 'field');
  const control = node('sl-input');
  control.label = label;
  control.type = type;
  control.id = `field-${key.replaceAll('.', '-')}`;
  if (help) control.helpText = help;
  for (const [name, value] of Object.entries(attributes)) control.setAttribute(name, value);
  const status = node('p', '', 'field-status');
  status.id = `${control.id}-status`;
  wrapper.append(control, status);
  parent.append(wrapper);
  const binding = bind({
    key, control, status, get,
    read: read || (() => control.value.trim()),
    write: write ? value => write(control, value) : value => { control.value = String(value ?? ''); },
  });
  control.addEventListener('sl-input', () => edited(binding));
  control.addEventListener('sl-change', () => persist(binding));
  control.addEventListener('sl-blur', () => persist(binding));
  control.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      persist(binding);
    }
  });
  return { control, binding, wrapper, status };
}

function integer(control, minimum, maximum, label) {
  const text = control.value.trim();
  if (!/^\d+$/.test(text)) throw new Error(`${label} must be a whole number.`);
  const value = Number(text);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function switchField(parent, label, key, options = {}) {
  const control = node('sl-switch', label);
  const status = node('p', '', 'field-status');
  status.id = `status-${key.replaceAll('.', '-')}`;
  parent.append(control, status);
  const binding = bind({ key, control, status, ...options,
    read: () => control.checked,
    write: value => { control.checked = Boolean(value); },
  });
  control.addEventListener('sl-change', () => edited(binding, true));
}

function serverFields() {
  const parent = $('server-fields');
  const port = field(parent, 'File-server port', 'server.port', {
    type: 'number', min: 1, max: 65535, step: 1,
    help: '1–65535. Restart serv to use a changed port.',
    read: () => integer(port.control, 1, 65535, 'Port'),
  });
  const size = field(parent, 'Largest rendered file (MB)', 'server.max_render_bytes', {
    type: 'number', min: 1024 / 1048576, max: 4096, step: 'any',
    help: '1 MB = 1,048,576 bytes. Larger files are served as plain text. Up to 4096 MB.',
    write: (control, value) => { control.value = String(value / 1048576); },
    read: () => {
      const text = size.control.value.trim();
      const number = Number(text);
      const bytes = Math.round(number * 1048576);
      if (!text || !Number.isFinite(number) || number < 1024 / 1048576 || number > 4096) {
        throw new Error('Enter a size between 0.0009765625 and 4096 MB.');
      }
      return bytes;
    },
  });
  const cache = field(parent, 'Cached pages', 'cache.entries', {
    type: 'number', min: 1, max: 4096, step: 1,
    help: 'Rendered Markdown pages kept in memory (1–4096).',
    read: () => integer(cache.control, 1, 4096, 'Cached pages'),
  });
  switchField($('autostart-field'), 'Start serv at login', 'autostart', {
    get: () => state.autostart,
    endpoint: '/api/autostart', body: enabled => ({ enabled }),
  });
  patterns();
}

function patterns() {
  let values = [...state.config.server.no_process];
  let initialized = false;
  const input = $('new-pattern');
  const list = $('pattern-list');
  const status = $('patterns-status');
  const draw = () => {
    list.replaceChildren();
    if (!values.length) list.append(node('li', 'No exceptions. All supported files will be rendered.', 'empty'));
    values.forEach((value, index) => {
      const item = node('li');
      const remove = node('sl-button', 'Remove');
      remove.size = 'small';
      remove.type = 'button';
      remove.append(node('span', ` pattern ${value}`, 'visually-hidden'));
      remove.addEventListener('click', async () => {
        values.splice(index, 1);
        draw();
        edited(binding, true);
        // Restore keyboard focus after the removed button leaves the DOM.
        const buttons = list.querySelectorAll('sl-button');
        const target = buttons[Math.min(index, buttons.length - 1)] || input;
        // Newly created web components render asynchronously.
        await target.updateComplete;
        (target.isConnected ? target : input).focus();
      });
      item.append(node('code', value), remove);
      list.append(item);
    });
  };
  const binding = bind({
    key: 'server.no_process', control: input, status,
    read: () => [...values],
    write: value => {
      if (!initialized || value.length !== values.length || value.some((pattern, index) => pattern !== values[index])) {
        values = [...value];
        draw();
        initialized = true;
      }
    },
  });
  const add = () => {
    const value = input.value.trim();
    if (!value) {
      feedback(binding, 'Enter a non-empty glob pattern.', true);
      input.focus();
      return;
    }
    if (values.includes(value)) {
      feedback(binding, 'That pattern is already in the list.', true);
      input.focus();
      return;
    }
    values.push(value);
    input.value = '';
    draw();
    edited(binding, true);
    input.focus();
  };
  input.addEventListener('sl-input', () => {
    if (binding.error && !binding.dirty) feedback(binding);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); add(); }
  });
  $('add-pattern').addEventListener('click', add);
}

function colors() {
  const wrapper = node('div', undefined, 'field');
  const select = node('sl-select');
  select.label = 'Color scheme';
  select.helpText = 'Choosing a preset replaces the page colors with that scheme.';
  const custom = node('sl-option', 'Custom colors');
  custom.value = '__custom__';
  custom.disabled = true;
  select.append(custom);
  for (const scheme of state.schemes) {
    const option = node('sl-option', scheme.label);
    option.value = scheme.key;
    select.append(option);
  }
  const status = node('p', '', 'field-status');
  status.id = 'scheme-status';
  wrapper.append(select, status);
  $('scheme-field').append(wrapper);
  const binding = bind({ key: 'scheme', control: select, status,
    get: () => state.scheme,
    read: () => select.value,
    write: value => { select.value = state.schemes.some(scheme => scheme.key === value) ? value : '__custom__'; },
  });
  select.addEventListener('sl-change', () => edited(binding, true));
  const titles = { palette: 'Page surfaces & base colors', accents: 'Surface accents', code: 'Code & syntax colors' };
  for (const section of ['palette', 'accents', 'code']) {
    const details = node('sl-details');
    details.summary = titles[section];
    const grid = node('div', undefined, 'color-grid');
    for (const [key] of Object.entries(state.config[section])) {
      const label = state.labels[section]?.[key] || key.replaceAll('_', ' ');
      const row = node('div', undefined, 'color-entry');
      const color = field(row, label, `${section}.${key}`, {
        spellcheck: 'false', autocapitalize: 'off',
        read: () => {
          const value = color.control.value.trim();
          // Match Config's accepted syntax, then ask the browser to validate it.
          if (!/^(?:#[\da-f]{3,8}|(?:rgb|rgba|hsl|hsla)\([^()]*\)|transparent|currentColor)$/i.test(value) ||
              !CSS.supports('color', value)) {
            throw new Error('Enter a valid hex, rgb(), hsl(), transparent, or currentColor value.');
          }
          return value;
        },
      });
      const picker = node('sl-color-picker');
      picker.label = `Choose ${label.toLowerCase()}`;
      picker.opacity = true;
      picker.format = 'hex';
      const syncPicker = () => {
        const value = color.control.value;
        if (CSS.supports('color', value) && value.toLowerCase() !== 'currentcolor') {
          picker.value = value === 'transparent' ? '#00000000' : value;
        }
      };
      syncPicker();
      refreshers.push(syncPicker);
      color.control.addEventListener('sl-input', syncPicker);
      picker.addEventListener('sl-change', () => {
        color.control.value = picker.value;
        edited(color.binding, true);
      });
      row.append(picker);
      grid.append(row);
    }
    details.append(grid);
    $('color-groups').append(details);
  }
}

function fonts() {
  for (const kind of ['reading', 'mono']) {
    const title = kind === 'reading' ? 'Reading' : 'Monospace';
    const group = node('div', undefined, 'font-group');
    const select = node('sl-select');
    select.label = `${title} font`;
    for (const font of state.fonts[kind]) {
      const option = node('sl-option', font.name);
      // sl-option values cannot contain spaces.
      option.value = encodeURIComponent(font.name);
      select.append(option);
    }
    const custom = node('sl-option', 'Custom font…');
    custom.value = '__custom__';
    select.append(custom);
    group.append(select);
    const customFields = node('div', undefined, 'custom-font');
    group.append(customFields);
    const name = field(customFields, `${title} font family`, `type.${kind}`, {
      help: 'Choose above or enter a custom family. Letters, digits, spaces, and hyphens; start with a letter.',
      spellcheck: 'false',
      read: () => {
        const value = name.control.value.trim();
        if (!/^[A-Za-z][A-Za-z0-9 -]*$/.test(value)) throw new Error('Enter a font family starting with a letter; use letters, digits, spaces, or hyphens.');
        return value;
      },
    });
    const weights = field(customFields, 'Google Fonts axis query (optional)', `type.${kind}_weights`, {
      help: 'Leave empty for an installed font. Example: wght@400;600 or ital,wght@0,400;1,400.',
      spellcheck: 'false', autocapitalize: 'off',
      read: () => {
        const value = weights.control.value.trim();
        if (!/^(?:[a-z]+(?:,[a-z]+)*@[0-9;,]+)?$/.test(value)) throw new Error('Use a Google Fonts axis query such as wght@400;600, or leave this empty.');
        return value;
      },
    });
    select.setAttribute('aria-describedby', name.status.id);
    const sync = () => {
      const known = state.fonts[kind].find(font => font.name === name.control.value.trim());
      select.value = known ? encodeURIComponent(known.name) : '__custom__';
    };
    sync();
    refreshers.push(sync);
    name.control.addEventListener('sl-input', sync);
    select.addEventListener('sl-change', () => {
      if (select.value === '__custom__') {
        name.control.focus();
        name.control.select();
        return;
      }
      const font = state.fonts[kind].find(item => encodeURIComponent(item.name) === select.value);
      if (!font) return;
      name.control.value = font.name;
      weights.control.value = font.weights;
      // The API changes one dotted key at a time. Keep the pair ordered.
      edited(name.binding, true);
      edited(weights.binding, true);
    });
    $('font-fields').append(group);
  }
}

// Keep these limits and steps aligned with src/serv/units.py:SLIDERS.
const SLIDERS = [
  ['type.md_size', 'Reading size', .9, 1.6, .05, 'rem'],
  ['type.md_table', 'Table text size', .8, 1.4, .05, 'rem'],
  ['type.code_size', 'Code size', 10, 18, .5, 'px'],
  ['type.line_height', 'Line height', 1.2, 2, .05, ''],
  ['layout.md_width', 'Markdown width', 32, 72, 2, 'rem'],
  ['layout.md_gutter', 'Markdown side padding', 1, 6, .5, 'rem'],
  ['layout.listing_width', 'Directory listing width', 32, 72, 2, 'rem'],
];

function ranges() {
  for (const [key, label, min, max, step, unit] of SLIDERS) {
    const group = node('div', undefined, 'field');
    const output = node('output', '', 'range-value');
    output.id = `value-${++sequence}`;
    output.setAttribute('aria-live', 'off');
    const range = node('sl-range');
    range.id = `range-${sequence}`;
    range.label = label;
    range.min = min;
    range.max = max;
    range.step = step;
    range.tooltip = 'none';
    range.setAttribute('aria-describedby', output.id);
    output.htmlFor = range.id;
    const fallback = node('div', undefined, 'range-fallback');
    group.append(output, range, fallback);
    $('range-fields').append(group);
    const input = field(fallback, `${label} (exact value)`, key, {
      help: unit ? 'CSS length: px, rem, em, ch, or %. Moving the slider uses ' + unit + '.' : 'Enter a non-negative line-height multiplier.',
      read: () => {
        const value = input.control.value.trim();
        if (!(unit ? /^\d+(?:\.\d+)?(?:px|rem|em|ch|%)$/ : /^\d+(?:\.\d+)?$/).test(value)) {
          throw new Error(unit ? 'Enter a CSS length such as 1.2rem or 18px.' : 'Enter a non-negative number such as 1.65.');
        }
        if (!Number.isFinite(parseFloat(value))) throw new Error('Enter a finite value.');
        return value;
      },
    });
    // Exact values remain editable, especially existing values in other units or
    // outside slider limits. Never silently convert or clamp saved settings.
    const sync = () => {
      const value = input.control.value.trim();
      output.textContent = value || 'Enter a value';
      const match = value.match(/^(\d+(?:\.\d+)?)(px|rem|em|ch|%)?$/);
      const numeric = match ? Number(match[1]) : NaN;
      const compatible = match && (match[2] || '') === unit && numeric >= min && numeric <= max;
      range.disabled = !compatible;
      if (compatible) range.value = numeric;
      range.helpText = compatible ? `${min}–${max}${unit ? ' ' + unit : ''}` : `Current value is outside this slider's units or range. Edit the exact value below.`;
      range.setAttribute('aria-valuetext', value);
    };
    sync();
    refreshers.push(sync);
    input.control.addEventListener('sl-input', sync);
    // Prevent announcing every animation frame; the output updates visually,
    // while sl-change saves on release or a keyboard step.
    range.addEventListener('sl-input', () => {
      input.control.value = `${Number(Number(range.value).toFixed(2))}${unit}`;
      output.textContent = input.control.value;
      range.setAttribute('aria-valuetext', input.control.value);
      edited(input.binding);
    });
    range.addEventListener('sl-change', () => {
      if (!input.binding.dirty) edited(input.binding, true);
      else persist(input.binding);
    });
  }
  switchField($('underline-field'), 'Underline links in Markdown', 'type.underline_links');
}

async function reveal() {
  const button = $('reveal');
  const status = $('reveal-status');
  button.loading = true;
  button.disabled = true;
  status.dataset.state = '';
  status.textContent = 'Opening configuration location…';
  try {
    const response = await api('/api/reveal', {});
    if (response.ok !== true) throw new Error('Could not reveal the configuration file.');
    status.textContent = 'Configuration file shown in your file manager.';
  } catch (error) {
    status.textContent = error.message;
    status.dataset.state = 'error';
  } finally {
    button.loading = false;
    button.disabled = false;
  }
}

window.addEventListener('beforeunload', event => {
  if (pending || timers.size || [...bindings.values()].some(binding => binding.dirty)) {
    event.preventDefault();
    event.returnValue = '';
  }
});

async function loadComponents() {
  let timer;
  try {
    await Promise.race([
      Promise.all(['input', 'select', 'option', 'button', 'switch', 'range', 'details', 'color-picker'].map(
        component => import(`${CDN}/components/${component}/${component}.js`),
      )),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('The settings components could not load. Check your internet connection and try again.')), 20000);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
  const { setBasePath } = await import(`${CDN}/utilities/base-path.js`);
  setBasePath(`${CDN}/`);
}

async function start() {
  try {
    if (!token) throw new Error('Missing authorization token. Open Settings from the serv menu to get a secure settings link.');
    // A failed CDN request is reported instead of leaving inert custom elements.
    await loadComponents();
    state = checkSettings(await api('/api/settings'));
    serverFields();
    colors();
    fonts();
    ranges();
    $('reveal').addEventListener('click', reveal);
    reconcile(state);
    $('settings').hidden = false;
    scrollToSection();
    lastMessage = 'Settings up to date';
    globalStatus();
  } catch (error) {
    $('load-error-text').textContent = error.message || 'Unable to load settings. Check your connection and reopen Settings.';
    $('load-error').hidden = false;
    $('save-status').textContent = 'Settings unavailable';
    $('save-status').dataset.state = 'error';
  }
}
start();
