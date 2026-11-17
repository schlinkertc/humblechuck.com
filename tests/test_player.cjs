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
  emit(name) { for (const fn of this.events[name] ?? []) fn({ preventDefault() {} }); }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(fragment) { this.children = fragment.children; }
  querySelectorAll() { return this.children.flatMap(row => row.children).filter(e => e.dataset.trackId); }
}

async function player(initial = [song('first'), song('second')], options = {}) {
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
  const library = { querySelector: find, scrollIntoView() { library.scrolled = true; } };
  const document = { hidden: false, querySelector: () => library, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener() {} };
  const location = { origin: 'https://example.com', hash: options.hash ?? '' };
  const windowEvents = {};
  const copied = [];
  const navigator = options.navigator ?? { clipboard: { writeText: async text => copied.push(text) } };
  let poll;
  vm.runInNewContext(source, {
    document, navigator, window: {
      location,
      history: { replaceState(_, __, url) { location.hash = new URL(url).hash; } },
      addEventListener(name, fn) { windowEvents[name] = fn; },
    }, URL, AbortController,
    setTimeout: () => 1, clearTimeout() {}, setInterval(fn) { poll = fn; },
    fetch: async () => ({ ok: true, json: async () => ({ tracks: catalog }) }),
  });
  await settle();
  return {
    audio, find, location, copied, library,
    click(element) { gesture = true; try { element.emit('click'); } finally { gesture = false; } },
    rows: () => find('[data-track-list]').querySelectorAll(),
    shares: () => find('[data-track-list]').children.map(row => row.children[1].children[0]),
    async refresh(next = catalog) { catalog = next; poll(); await settle(); },
    async navigate(hash) { location.hash = hash; windowEvents.hashchange(); await settle(); },
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

test('incoming song links cue the requested song without autoplay', async () => {
  const p = await player(undefined, { hash: '#second' });
  assert.equal(p.audio.src, song('second').url);
  assert.equal(p.audio.calls.length, 0);
  assert.equal(p.library.scrolled, true);
  await p.navigate('#first');
  assert.equal(p.audio.src, song('first').url);
  assert.equal(p.audio.calls.length, 0);
});

test('missing or malformed song links do not silently select the first song', async () => {
  for (const hash of ['#missing', '#%malformed']) {
    const p = await player(undefined, { hash });
    assert.equal(p.audio.src, undefined);
    assert.match(p.find('[data-demo-status]').textContent, /isn’t available/);
    assert.equal(p.find('[data-toggle-play]').disabled, true);
    p.click(p.rows()[1]); await settle();
    assert.equal(p.location.hash, '#second');
  }
});

test('share links copy stable song URLs, independent of S3 versions', async () => {
  const p = await player([song('all-the-flowers')]);
  p.click(p.shares()[0]); await settle();
  assert.deepEqual(p.copied, ['https://example.com/demos#all-the-flowers']);
  assert.match(p.find('[data-demo-status]').textContent, /Link copied/);
  await p.refresh([song('all-the-flowers', 'replacement')]);
  assert.equal(p.shares()[0].href, 'https://example.com/demos#all-the-flowers');
});

test('native sharing uses the selected song, and cancellation does not copy', async () => {
  const shared = []; const copied = [];
  const p = await player(undefined, { navigator: {
    share: async data => { shared.push(data); throw Object.assign(new Error(), { name: 'AbortError' }); },
    clipboard: { writeText: async text => copied.push(text) },
  } });
  p.click(p.shares()[1]); await settle();
  assert.equal(shared[0].url, 'https://example.com/demos#second');
  assert.equal(shared[0].title, 'second');
  assert.equal(copied.length, 0);
  assert.equal(p.audio.calls.length, 0, 'sharing must not start or change playback');
});

test('clipboard denial exposes a selectable song link', async () => {
  const p = await player(undefined, { navigator: {} });
  p.click(p.shares()[1]); await settle();
  assert.equal(p.find('[data-share-fallback]').hidden, false);
  assert.equal(p.find('[data-share-url]').value, 'https://example.com/demos#second');
  assert.equal(p.find('[data-share-url]').selected, true);
  p.click(p.find('[data-close-share]'));
  assert.equal(p.find('[data-share-fallback]').hidden, true);
});

test('song links distinguish colliding names and preserve reserved page anchors', async () => {
  const items = [song('Café'), song('cafe'), song('main')];
  const p = await player(items, { hash: '#main' });
  const links = p.shares().map(link => link.href);
  assert.equal(new Set(links).size, 3);
  for (let i = 0; i < items.length; i++) {
    await p.navigate(new URL(links[i]).hash);
    assert.equal(p.audio.src, items[i].url);
  }
});
