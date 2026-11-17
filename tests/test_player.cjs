const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../site_src/demos.js'), 'utf8');
const song = (id, version = '1') => ({ id: `tracks/${id}.m4a`, title: id, filename: `${id}.m4a`, url: `/tracks/${id}.m4a?versionId=${version}` });
const settle = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor() { this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.textContent = ''; }
  addEventListener(name, fn) { (this.events[name] ??= []).push(fn); }
  emit(name) { for (const fn of this.events[name] ?? []) fn(); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(fragment) { this.children = fragment.children; }
  querySelectorAll() { return this.children.flatMap(row => row.children).filter(e => e.dataset.trackId); }
}

async function player(initial = [song('first'), song('second')]) {
  const nodes = new Map();
  const find = selector => { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); };
  const audio = find('[data-demo-audio]');
  let gesture = false;
  Object.assign(audio, { paused: true, readyState: 0, currentTime: 0, duration: 120, loads: 0, calls: [] });
  audio.load = () => { audio.loads++; audio.error = null; audio.readyState = 0; audio.paused = true; audio.emit('emptied'); };
  audio.play = () => {
    audio.calls.push({ gesture, src: audio.src });
    assert.equal(gesture, true, 'play must be called synchronously during the tap');
    audio.paused = false; audio.readyState = 4; audio.emit('play');
    return Promise.resolve();
  };
  audio.pause = () => { audio.paused = true; audio.emit('pause'); };
  let catalog = initial;
  const library = { querySelector: find };
  const document = { hidden: false, querySelector: () => library, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener() {} };
  vm.runInNewContext(source, {
    document, window: { location: { origin: 'https://example.com' } }, URL, AbortController,
    setTimeout: () => 1, clearTimeout() {}, setInterval() {},
    fetch: async () => ({ ok: true, json: async () => ({ tracks: catalog }) }),
  });
  await settle();
  return {
    audio, find,
    click(element) { gesture = true; try { element.emit('click'); } finally { gesture = false; } },
    rows: () => find('[data-track-list]').querySelectorAll(),
    async refresh(next = catalog) { catalog = next; find('[data-refresh]').emit('click'); await settle(); },
  };
}

test('first song starts on the first tap and can pause/resume without a reload', async () => {
  const p = await player();
  assert.equal(p.audio.calls.length, 0, 'no page-load autoplay');
  assert.equal(p.find('[data-toggle-play]').textContent, 'Play');
  p.click(p.find('[data-toggle-play]')); await settle();
  assert.equal(p.audio.calls[0].src, song('first').url);
  assert.equal(p.find('[data-toggle-play]').textContent, 'Pause');
  p.audio.currentTime = 42;
  p.click(p.find('[data-toggle-play]'));
  const loads = p.audio.loads;
  p.click(p.find('[data-toggle-play]')); await settle();
  assert.equal(p.audio.loads, loads);
  assert.equal(p.audio.currentTime, 42);
});

test('failed initial audio can retry the same song without switching tracks', async () => {
  const p = await player();
  p.audio.error = { code: 2 }; p.audio.emit('error');
  assert.equal(p.find('[data-toggle-play]').textContent, 'Retry playback');
  const loads = p.audio.loads;
  p.click(p.find('[data-toggle-play]')); await settle();
  assert.equal(p.audio.loads, loads + 1);
  assert.equal(p.audio.calls[0].src, song('first').url);
  assert.equal(p.find('[data-demo-status]').textContent, '');
});

test('track selection loads once and clicking the same track does not reset playback', async () => {
  const p = await player(); const before = p.audio.loads;
  p.click(p.rows()[1]); await settle();
  assert.equal(p.audio.loads, before + 1);
  p.audio.currentTime = 28;
  p.click(p.rows()[1]); await settle();
  assert.equal(p.audio.loads, before + 1);
  assert.equal(p.audio.currentTime, 28);
});

test('catalog refresh preserves playback but picks up a replacement when paused', async () => {
  const p = await player(); p.click(p.find('[data-toggle-play]')); await settle();
  p.audio.currentTime = 32; const loads = p.audio.loads;
  await p.refresh([song('first', '2'), song('second')]);
  assert.equal(p.audio.src, song('first').url);
  assert.equal(p.audio.loads, loads);
  assert.equal(p.audio.currentTime, 32);
  p.audio.pause(); await p.refresh();
  assert.equal(p.audio.src, song('first', '2').url);
});

test('an old play failure cannot overwrite a successful new track selection', async () => {
  const p = await player(); let rejectOld;
  const play = p.audio.play;
  p.audio.play = () => new Promise((_, reject) => { rejectOld = reject; });
  p.click(p.find('[data-toggle-play]'));
  p.audio.play = play;
  p.click(p.rows()[1]); await settle();
  rejectOld(new Error('old playback failed')); await settle();
  assert.equal(p.find('[data-demo-status]').textContent, '');
  assert.equal(p.find('[data-toggle-play]').textContent, 'Pause');
});
