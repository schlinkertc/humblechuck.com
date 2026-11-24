const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const { webcrypto, createHash } = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '../site_src/demos.js'), 'utf8');
const song = (id, version = '1') => ({ id: `tracks/${id}.m4a`, title: id, filename: `${id}.m4a`, url: `/tracks/${id}.m4a?versionId=${version}` });
const settle = () => new Promise(resolve => setTimeout(resolve, 10));

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
  let now = 0;
  Object.assign(audio, { paused: true, readyState: 0, currentTime: 0, duration: 120, loads: 0, calls: [] });
  audio.load = () => { audio.loads++; audio.error = null; audio.readyState = 0; audio.paused = true; audio.currentTime = 0; audio.emit('emptied'); };
  audio.play = () => {
    audio.calls.push({ gesture, src: audio.src });
    assert.equal(gesture, true, 'play must be called synchronously during the tap');
    if (audio.ended) { audio.currentTime = 0; audio.ended = false; }
    audio.paused = false; audio.readyState = 4; audio.emit('play'); audio.emit('playing');
    return Promise.resolve();
  };
  audio.pause = () => { audio.paused = true; audio.emit('pause'); };
  let catalog = initial;
  const library = { querySelector: find, scrollIntoView() { library.scrolled = true; } };
  const document = { hidden: false, referrer: options.referrer ?? '', querySelector: () => library, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener() {} };
  const location = { origin: 'https://example.com', pathname: '/demos', hash: options.hash ?? '' };
  const windowEvents = {};
  const copied = [];
  const navigator = options.navigator ?? { clipboard: { writeText: async text => copied.push(text) } };
  const storage = options.storage ?? new Map();
  const requests = [];
  const timers = new Map();
  const countedEvents = new Set();
  let total = 0;
  let timerId = 0;
  let poll;
  vm.runInNewContext(source, {
    document, navigator, window: {
      location,
      history: { replaceState(_, __, url) { location.hash = new URL(url).hash; } },
      addEventListener(name, fn) { windowEvents[name] = fn; },
    }, URL, AbortController, crypto: webcrypto, TextEncoder, Uint8Array,
    performance: { now: () => now },
    sessionStorage: {
      getItem(key) { if (options.blockStorage) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem(key, value) { if (options.blockStorage) throw Error('blocked'); storage.set(key, value); },
    },
    setTimeout(fn, delay) { timers.set(++timerId, { fn, delay }); return timerId; },
    clearTimeout(id) { timers.delete(id); }, setInterval(fn) { poll = fn; },
    fetch: async (url, init = {}) => {
      requests.push({ url, ...init });
      if (url === '/api/demos') return { ok: true, json: async () => ({ tracks: catalog }) };
      if (init.method === 'POST' && options.onPlay) return options.onPlay(url, init);
      if (!init.method && options.onCount) return options.onCount(url, init);
      if (init.method === 'POST') {
        const id = JSON.parse(init.body).event_id;
        if (!countedEvents.has(id)) { countedEvents.add(id); total++; }
      }
      return { ok: true, status: 200, json: async () => ({ plays: total }) };
    },
  });
  await settle();
  return {
    audio, find, location, copied, library, storage, requests,
    playRequests: () => requests.filter(request => request.method === 'POST'),
    async listen(seconds, advanced = seconds * (audio.playbackRate || 1)) {
      now += seconds * 1000; audio.currentTime += advanced; audio.emit('timeupdate'); await settle();
    },
    async retry() {
      const entry = [...timers.entries()].find(([id, timer]) => timer.delay < 5000);
      assert.ok(entry, 'a bounded retry should be scheduled');
      timers.delete(entry[0]); entry[1].fn(); await settle();
    },
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

test('a play qualifies after ten seconds, with an exact payload hash and limited attributes', async () => {
  const p = await player(undefined, { referrer: 'https://instagram.com/private?token=secret' });
  assert.equal(p.playRequests().length, 0, 'loading and cueing are not plays');
  p.click(p.find('[data-toggle-play]'));
  await p.listen(9.5);
  assert.equal(p.playRequests().length, 0);
  await p.listen(.5);
  const request = p.playRequests()[0];
  const event = JSON.parse(request.body);
  assert.equal(event.demo_id, song('first').id);
  assert.equal(event.recording_version, '1');
  assert.equal(event.listened_seconds, 10);
  assert.equal(event.duration_seconds, 120);
  assert.equal(event.page, '/demos');
  assert.equal(event.referrer_host, 'instagram.com');
  assert.match(event.event_id, /^[a-f0-9-]{36}$/);
  assert.equal(request.headers['x-amz-content-sha256'], createHash('sha256').update(request.body).digest('hex'));
  assert.equal(request.credentials, 'omit');
  assert.equal(request.keepalive, true);
  assert.equal(p.find('[data-play-count]').textContent, '1 play');
  await p.listen(30);
  assert.equal(p.playRequests().length, 1);
});

test('pauses, buffering and seeks do not count as listening; resuming keeps progress', async () => {
  const p = await player(); p.click(p.find('[data-toggle-play]'));
  await p.listen(4);
  p.audio.pause(); await p.listen(60, 0);
  p.click(p.find('[data-toggle-play]')); await p.listen(2);
  p.audio.emit('waiting'); await p.listen(60, 0);
  p.audio.emit('playing');
  p.audio.emit('seeking'); p.audio.currentTime = 90; p.audio.emit('timeupdate'); p.audio.emit('seeked');
  await p.listen(3);
  assert.equal(p.playRequests().length, 0);
  await p.listen(1);
  assert.equal(p.playRequests().length, 1);
  assert.equal(JSON.parse(p.playRequests()[0].body).listened_seconds, 10);
});

test('listening is measured per track and faster playback cannot qualify early', async () => {
  const p = await player(); p.click(p.find('[data-toggle-play]'));
  await p.listen(6);
  p.click(p.rows()[1]); await p.listen(5);
  assert.equal(p.playRequests().length, 0);
  p.audio.playbackRate = 2; p.audio.emit('ratechange');
  await p.listen(5);
  assert.equal(p.playRequests().length, 1);
  assert.equal(JSON.parse(p.playRequests()[0].body).demo_id, song('second').id);
  p.click(p.rows()[0]); await p.listen(4);
  assert.equal(p.playRequests().length, 1, 'switching back starts a new listen with its own threshold');
  await p.listen(6);
  assert.equal(p.playRequests().length, 2);
});

test('reloading allows a new listen while pending retries preserve the old event ID', async () => {
  const p = await player(); p.click(p.find('[data-toggle-play]')); await p.listen(10);
  const reloaded = await player(undefined, { storage: p.storage });
  reloaded.click(reloaded.find('[data-toggle-play]')); await reloaded.listen(10);
  assert.equal(reloaded.playRequests().length, 1);
  assert.notEqual(JSON.parse(reloaded.playRequests()[0].body).event_id, JSON.parse(p.playRequests()[0].body).event_id);
  assert.deepEqual(JSON.parse(p.storage.get('hc:demo-plays:pending:v2')), [], 'acknowledged plays leave no suppression marker');

  const failed = await player(undefined, { onPlay: async () => { throw Error('offline'); } });
  failed.click(failed.find('[data-toggle-play]')); await failed.listen(10);
  const pending = await player(undefined, { storage: failed.storage });
  assert.equal(pending.playRequests()[0].body, failed.playRequests()[0].body);
  pending.click(pending.find('[data-toggle-play]')); await pending.listen(10);
  assert.equal(pending.playRequests().length, 2, 'restoring a retry must not suppress this new listen');
  assert.notEqual(JSON.parse(pending.playRequests()[0].body).event_id, JSON.parse(pending.playRequests()[1].body).event_id);
});

test('replays after completion and switching away and back count as separate plays', async () => {
  const p = await player([song('first')]);
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  p.audio.currentTime = p.audio.duration; p.audio.ended = true; p.audio.paused = true; p.audio.emit('ended');
  p.click(p.find('[data-toggle-play]')); await p.listen(9);
  assert.equal(p.playRequests().length, 1);
  await p.listen(1);
  assert.equal(p.playRequests().length, 2);
  assert.equal(p.find('[data-play-count]').textContent, '2 plays');
  assert.notEqual(JSON.parse(p.playRequests()[0].body).event_id, JSON.parse(p.playRequests()[1].body).event_id);

  const q = await player(); q.click(q.rows()[0]); await q.listen(10);
  q.click(q.rows()[1]); await q.listen(3);
  q.click(q.rows()[0]); await q.listen(10);
  assert.equal(q.playRequests().length, 2);
  assert.equal(new Set(q.playRequests().map(r => JSON.parse(r.body).event_id)).size, 2);
});

test('a deliberate restart counts again while pause/resume and ordinary scrubbing do not', async () => {
  const p = await player(); p.click(p.find('[data-toggle-play]')); await p.listen(10);
  p.audio.pause(); p.click(p.find('[data-toggle-play]')); await p.listen(10);
  p.audio.currentTime = 80; p.audio.emit('seeking'); p.audio.emit('seeked'); await p.listen(10);
  assert.equal(p.playRequests().length, 1);
  p.audio.currentTime = 0; p.audio.emit('seeking'); p.audio.emit('seeked');
  await p.listen(9);
  assert.equal(p.playRequests().length, 1);
  await p.listen(1);
  assert.equal(p.playRequests().length, 2);
});

test('multiple failed plays of the same song keep independent pending IDs', async () => {
  const p = await player(undefined, { onPlay: async () => ({ ok: false, status: 503 }) });
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  p.audio.currentTime = 0; p.audio.emit('seeking'); p.audio.emit('seeked'); await p.listen(10);
  const pending = JSON.parse(p.storage.get('hc:demo-plays:pending:v2'));
  assert.equal(pending.length, 2);
  assert.equal(new Set(pending.map(event => event.event_id)).size, 2);
  await p.retry();
  assert.equal(JSON.parse(p.playRequests()[2].body).event_id, pending[0].event_id);
  assert.equal(JSON.parse(p.storage.get('hc:demo-plays:pending:v2')).length, 2);
});

test('old session acknowledgement markers no longer suppress plays', async () => {
  const storage = new Map([['hc:demo-play:v1:tracks/first.m4a', JSON.stringify({
    payload: { demo_id: 'tracks/first.m4a', event_id: webcrypto.randomUUID() }, sent: true,
  })]]);
  const p = await player(undefined, { storage });
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  assert.equal(p.playRequests().length, 1);
});

test('periodic refresh picks up other listeners without interrupting playback or decreasing counts', async () => {
  let count = 5;
  const p = await player(undefined, { onCount: async () => ({ ok: true, json: async () => ({ plays: count }) }) });
  p.click(p.find('[data-toggle-play]'));
  const loads = p.audio.loads;
  assert.equal(p.find('[data-play-count]').textContent, '5 plays');
  count = 8; await p.refresh();
  assert.equal(p.find('[data-play-count]').textContent, '8 plays');
  assert.equal(p.audio.loads, loads);
  assert.equal(p.audio.paused, false);
  count = 7; await p.refresh();
  assert.equal(p.find('[data-play-count]').textContent, '8 plays');
});

test('failed requests retry at most three times without inflating or interrupting playback', async () => {
  const p = await player(undefined, { onPlay: async () => ({ ok: false, status: 503 }) });
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  await p.listen(1);
  assert.equal(p.playRequests().length, 1, 'timeupdate events must respect the scheduled retry');
  await p.retry(); await p.retry(); await p.listen(10);
  assert.equal(p.playRequests().length, 3);
  assert.equal(new Set(p.playRequests().map(r => r.body)).size, 1);
  assert.equal(p.audio.paused, false);
  assert.equal(p.find('[data-demo-status]').textContent, '');
});

test('unavailable browser storage and count service do not break the player', async () => {
  const p = await player(undefined, { blockStorage: true, onCount: async () => { throw Error('offline'); } });
  assert.equal(p.find('[data-play-count]').hidden, true);
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  assert.equal(p.playRequests().length, 1);
  assert.equal(p.find('[data-demo-status]').textContent, '');
});

test('late counts cannot replace a newly recorded total or a different track count', async () => {
  const replies = [];
  const p = await player(undefined, { onCount: () => new Promise(resolve => replies.push(resolve)) });
  p.click(p.find('[data-toggle-play]')); await p.listen(10);
  replies[0]({ ok: true, json: async () => ({ plays: 0 }) }); await settle();
  assert.equal(p.find('[data-play-count]').textContent, '1 play');
  p.click(p.rows()[1]);
  assert.equal(p.find('[data-play-count]').hidden, true);
  replies[1]({ ok: true, json: async () => ({ plays: 20 }) }); await settle();
  assert.equal(p.find('[data-play-count]').textContent, '20 plays');
});
