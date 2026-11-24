(() => {
  const library = document.querySelector("[data-demo-library]");
  if (!library) return;
  const find = (selector) => library.querySelector(selector);
  const audio = find("[data-demo-audio]");
  const title = find("[data-current-title]");
  const download = find("[data-current-download]");
  const list = find("[data-track-list]");
  const status = find("[data-demo-status]");
  const shareFallback = find("[data-share-fallback]");
  const shareInput = find("[data-share-url]");
  const previous = find("[data-previous]");
  const next = find("[data-next]");
  const rewind = find("[data-rewind]");
  const forward = find("[data-forward]");
  const toggle = find("[data-toggle-play]");
  const playCount = find("[data-play-count]");
  let tracks = [];
  let current = null;
  let loading = false;
  let needsReload = false;
  let playAttempt = 0;
  let songAnchors = new Map();
  let shareTrigger = null;
  const pendingPlays = new Map();
  let activePlay = null;
  let listening = null;
  let lastPosition = 0;
  let countRequest = 0;
  let countController = null;
  let displayedCount = null;

  function renderCount(id, count) {
    if (current?.id !== id || !Number.isSafeInteger(count) || count < 0) return;
    displayedCount = Math.max(displayedCount ?? 0, count);
    playCount.textContent = `${displayedCount.toLocaleString()} ${displayedCount === 1 ? "play" : "plays"}`;
    playCount.hidden = false;
  }

  async function loadCount(track) {
    const request = ++countRequest;
    countController?.abort();
    const controller = new AbortController();
    countController = controller;
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(`/api/demo-plays?demo_id=${encodeURIComponent(track.id)}`, {
        signal: controller.signal, credentials: "omit", cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      if (request === countRequest) renderCount(track.id, data.plays);
    } catch { /* Counting must never interfere with listening. */ }
    finally {
      clearTimeout(timeout);
      if (countController === controller) countController = null;
    }
  }

  function newPlay(payload = null) {
    return { seconds: 0, payload, sent: false, attempts: 0, inFlight: false };
  }

  function savePendingPlays() {
    try {
      sessionStorage.setItem("hc:demo-plays:pending:v2", JSON.stringify(
        Array.from(pendingPlays.values(), state => state.payload),
      ));
    } catch { /* Private browsing or disabled storage: use this page's memory. */ }
  }

  function restorePendingPlays() {
    try {
      const saved = JSON.parse(sessionStorage.getItem("hc:demo-plays:pending:v2"));
      if (!Array.isArray(saved)) return;
      for (const payload of saved) {
        if (typeof payload?.event_id !== "string" || typeof payload.demo_id !== "string") continue;
        pendingPlays.set(payload.event_id, newPlay(payload));
      }
      pendingPlays.forEach(sendPlay);
    } catch { /* Analytics storage is optional. */ }
  }

  function forgetPendingPlay(state) {
    pendingPlays.delete(state.payload.event_id);
    savePendingPlays();
  }

  async function sendPlay(state) {
    if (!state.payload || state.sent || state.inFlight || state.attempts >= 3) return;
    state.inFlight = true;
    state.attempts++;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    let retry = false;
    try {
      const body = JSON.stringify(state.payload);
      // Lambda function URL origins require a payload hash for CloudFront OAC
      // to sign POSTs. Hash these exact UTF-8 bytes; no AWS keys reach browsers.
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
      const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      const response = await fetch("/api/demo-plays", {
        method: "POST", headers: { "Content-Type": "application/json", "x-amz-content-sha256": hash },
        body, signal: controller.signal, keepalive: true, credentials: "omit",
      });
      if (!response.ok) {
        retry = response.status === 429 || response.status >= 500;
        if (!retry) forgetPendingPlay(state);
      } else {
        const data = await response.json();
        state.sent = true;
        forgetPendingPlay(state);
        if (current?.id === state.payload.demo_id) {
          ++countRequest; // An earlier count request must not overwrite this total.
          renderCount(state.payload.demo_id, data.plays);
        }
      }
    } catch { retry = true; }
    finally {
      clearTimeout(timeout);
      state.inFlight = false;
      if (retry && state.attempts < 3) setTimeout(() => sendPlay(state), 1000 * state.attempts);
    }
  }

  function qualifyPlay(track, state) {
    if (!state.payload && state.seconds >= 10 && globalThis.crypto?.randomUUID && crypto.subtle) {
      state.payload = {
        event_id: crypto.randomUUID(), demo_id: track.id,
        listened_seconds: Math.round(state.seconds * 100) / 100, page: window.location.pathname,
      };
      const version = new URL(track.url, window.location.origin).searchParams.get("versionId");
      if (version) state.payload.recording_version = version;
      if (Number.isFinite(audio.duration) && audio.duration > 0) state.payload.duration_seconds = Math.round(audio.duration * 100) / 100;
      try {
        const referrer = new URL(document.referrer);
        if (referrer.hostname !== new URL(window.location.origin).hostname) state.payload.referrer_host = referrer.hostname;
      } catch { /* No external referrer. */ }
      pendingPlays.set(state.payload.event_id, state);
      savePendingPlays(); // Preserve retry IDs without suppressing a later listen.
      sendPlay(state);
    }
  }

  function sampleListening() {
    if (!listening || !current) return;
    const now = performance.now();
    const advanced = audio.currentTime - listening.position;
    const elapsed = Math.max(0, (now - listening.time) / 1000);
    // Count time while audio advances, capped by elapsed wall time. Seeking,
    // stalls, pauses, and faster playback cannot manufacture listening time.
    if (advanced > 0) {
      const state = activePlay ??= newPlay();
      state.seconds += Math.min(advanced / (audio.playbackRate || 1), elapsed);
      qualifyPlay(current, state);
    }
    listening = { position: audio.currentTime, time: now };
    lastPosition = audio.currentTime;
  }

  function stopListening() {
    sampleListening();
    listening = null;
  }

  function buildSongAnchors() {
    // Derive links from filenames, so changing a recording's S3 version does
    // not change its public song link. Include folders to avoid common clashes.
    const bases = tracks.map(track => track.id.replace(/^tracks\//, "").replace(/\.[^.]+$/, "")
      .normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "song")
      .map(base => ["main", "page-title"].includes(base) ? `song-${base}` : base);
    const counts = new Map();
    bases.forEach(base => counts.set(base, (counts.get(base) || 0) + 1));
    songAnchors = new Map(tracks.map((track, index) => [track.id,
      counts.get(bases[index]) === 1 ? bases[index] : `${bases[index]}--${encodeURIComponent(track.id)}`,
    ]));
  }

  function songUrl(track) {
    const url = new URL("/demos", window.location.origin);
    url.hash = songAnchors.get(track.id);
    return url.href;
  }

  function updateSongHash(track) {
    if (songAnchors.has(track.id)) window.history.replaceState(null, "", songUrl(track));
  }

  function linkedSong() {
    let hash;
    try { hash = decodeURIComponent(window.location.hash.slice(1)); }
    catch { return { requested: true }; }
    if (!hash || hash === "main" || hash === "page-title") return { requested: false };
    return {
      requested: true,
      track: tracks.find(track => decodeURIComponent(songAnchors.get(track.id)) === hash),
    };
  }

  function cueLinkedSong() {
    const linked = linkedSong();
    if (linked.track) {
      select(linked.track, false, false);
      status.textContent = "";
      library.scrollIntoView({ block: "start" });
    } else if (linked.requested) {
      status.textContent = "That recording isn’t available. Choose another song below.";
      if (!current) title.textContent = "Recording not found.";
    }
    return linked.requested;
  }

  async function shareSong(track, trigger) {
    shareFallback.hidden = true;
    const url = songUrl(track);
    if (navigator.share) {
      try {
        await navigator.share({ title: track.title, url });
        return;
      } catch (error) {
        if (error.name === "AbortError") return; // Dismissing the sheet is normal.
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      status.textContent = `Link copied for “${track.title}”.`;
    } catch {
      // Clipboard permissions can be denied; keep a normal selectable URL.
      shareTrigger = trigger;
      shareInput.value = url;
      shareFallback.hidden = false;
      shareInput.focus();
      shareInput.select();
    }
  }

  function renderPlayButton() {
    toggle.disabled = !current;
    toggle.textContent = needsReload ? "Retry playback" : audio.paused ? "Play" : "Pause";
  }

  function renderSelection() {
    list.querySelectorAll("[data-track-id]").forEach((button) => {
      const selected = button.dataset.trackId === current?.id;
      if (selected) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    previous.disabled = next.disabled = tracks.length < 2;
    rewind.disabled = forward.disabled = !current;
    renderPlayButton();
  }

  async function play() {
    if (!current) return;
    const attempt = ++playAttempt;
    // Keep load() and play() together in the tap handler. The first track must
    // have the same recovery path as selecting another song on an iPhone.
    if (needsReload || audio.error || audio.readyState === 0) {
      needsReload = false;
      audio.load();
    }
    try {
      await audio.play();
      if (attempt === playAttempt) status.textContent = "";
    } catch (error) {
      if (attempt !== playAttempt || error.name === "AbortError") return;
      needsReload = true;
      status.textContent = "The recording couldn’t start. Tap Retry playback to try this song again, or download it to listen.";
      renderPlayButton();
    }
  }

  function select(track, autoplay = false, updateHash = true) {
    const changed = current?.url !== track.url;
    if (changed) {
      stopListening();
      activePlay = null;
      lastPosition = 0;
    }
    current = track;
    title.textContent = track.title;
    if (changed) {
      playCount.hidden = true;
      displayedCount = null;
      loadCount(track);
      ++playAttempt;
      needsReload = false;
      audio.src = track.url;
      if (autoplay) needsReload = true;
      else audio.load();
    }
    download.href = track.url;
    download.download = track.filename;
    download.hidden = false;
    if (updateHash) updateSongHash(track);
    renderSelection();
    if (autoplay) play();
  }

  function step(direction, autoplay = true) {
    if (!tracks.length) return;
    const index = tracks.findIndex((track) => track.id === current?.id);
    select(tracks[(Math.max(index, 0) + direction + tracks.length) % tracks.length], autoplay);
  }

  function renderTracks() {
    const fragment = document.createDocumentFragment();
    tracks.forEach((track, index) => {
      const row = document.createElement("li");
      row.id = decodeURIComponent(songAnchors.get(track.id));
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.trackId = track.id;
      button.className = "demo-track";
      const number = document.createElement("span");
      number.className = "demo-track-number";
      number.textContent = String(index + 1).padStart(2, "0");
      number.setAttribute("aria-hidden", "true");
      const name = document.createElement("span");
      name.textContent = track.title;
      button.append(number, name);
      button.setAttribute("aria-label", `Play ${track.title}`);
      button.addEventListener("click", () => select(track, true));
      const link = document.createElement("a");
      link.className = "demo-track-download";
      link.href = track.url;
      link.download = track.filename;
      link.textContent = "↓";
      link.setAttribute("aria-label", `Download ${track.title}`);
      const share = document.createElement("a");
      share.className = "demo-track-share";
      share.href = songUrl(track);
      share.textContent = "Share";
      share.setAttribute("aria-label", `Share ${track.title}`);
      share.addEventListener("click", event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
        event.preventDefault();
        shareSong(track, share);
      });
      const actions = document.createElement("div");
      actions.className = "demo-track-actions";
      actions.append(share, link);
      row.append(button, actions);
      fragment.append(row);
    });
    list.replaceChildren(fragment);
    find("[data-track-count]").textContent = `(${tracks.length})`;
    renderSelection();
  }

  async function loadTracks() {
    if (loading) return;
    loading = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/demos", { signal: controller.signal });
      if (!response.ok) throw new Error("Catalog unavailable");
      const data = await response.json();
      if (!Array.isArray(data.tracks)) throw new Error("Invalid catalog");
      // Only allow the same-origin audio paths served by our recordings bucket.
      const valid = data.tracks.every((track) => {
        if (typeof track.id !== "string" || typeof track.title !== "string" || typeof track.filename !== "string" || typeof track.url !== "string") return false;
        const url = new URL(track.url, window.location.origin);
        return url.origin === window.location.origin && url.pathname.startsWith("/tracks/");
      });
      if (!valid) throw new Error("Invalid recording URL");
      tracks = data.tracks;
      buildSongAnchors();
      renderTracks();
      status.textContent = tracks.length ? "" : "No recordings here yet. Check back soon.";
      if (!current && tracks.length && !cueLinkedSong()) select(tracks[0], false, false);
      // Keep uninterrupted playback during a refresh. A paused, replaced song
      // is recued with the latest object version; removed tracks are cleared.
      if (current && audio.paused) {
        const latest = tracks.find((track) => track.id === current.id);
        if (!latest) {
          if (tracks.length) select(tracks[0], false, false);
          else {
            stopListening();
            current = null;
            activePlay = null;
            displayedCount = null;
            ++countRequest;
            playCount.hidden = true;
            audio.removeAttribute("src");
            audio.load();
            title.textContent = "More songs soon.";
            download.hidden = true;
            renderSelection();
          }
        } else if (latest.url !== current.url) select(latest, false, false);
      }
      if (!tracks.length && !current) title.textContent = "More songs soon.";
    } catch (error) {
      status.textContent = tracks.length
        ? "Couldn’t update the recordings. You can keep listening or reload the page."
        : "The recordings couldn’t load. Please reload the page in a moment.";
      if (!current) title.textContent = "A little quiet right now.";
    } finally {
      clearTimeout(timeout);
      loading = false;
    }
  }

  audio.addEventListener("playing", () => {
    activePlay ??= newPlay();
    lastPosition = audio.currentTime;
    listening = { position: audio.currentTime, time: performance.now() };
  });
  audio.addEventListener("timeupdate", () => {
    sampleListening();
    lastPosition = audio.currentTime;
  });
  ["pause", "waiting", "ended", "error"].forEach(event => audio.addEventListener(event, stopListening));
  audio.addEventListener("ended", () => { activePlay = null; });
  audio.addEventListener("emptied", () => {
    listening = activePlay = null;
    lastPosition = 0;
  });
  audio.addEventListener("seeking", () => {
    // Returning to the beginning is a replay. Ordinary scrubbing and
    // pause/resume continue the current listen, including its retry ID.
    if (audio.currentTime <= 1 && lastPosition > 1) activePlay = null;
    listening = null;
    lastPosition = audio.currentTime;
  });
  audio.addEventListener("ratechange", () => { listening = null; });
  const resumeListening = () => {
    if (!audio.paused && !audio.seeking && audio.readyState >= 3) {
      listening = { position: audio.currentTime, time: performance.now() };
    }
  };
  audio.addEventListener("seeked", resumeListening);
  audio.addEventListener("ratechange", resumeListening);

  previous.addEventListener("click", () => step(-1));
  toggle.addEventListener("click", () => {
    if (audio.paused || needsReload || audio.error) play();
    else { ++playAttempt; audio.pause(); }
  });
  next.addEventListener("click", () => step(1));
  rewind.addEventListener("click", () => { if (current && audio.readyState > 0) audio.currentTime = Math.max(0, audio.currentTime - 15); });
  forward.addEventListener("click", () => { if (current && Number.isFinite(audio.duration)) audio.currentTime = Math.min(audio.duration, audio.currentTime + 15); });
  audio.addEventListener("ended", () => {
    const index = tracks.findIndex((track) => track.id === current?.id);
    if (index >= 0 && index < tracks.length - 1) select(tracks[index + 1], true);
  });
  audio.addEventListener("error", () => {
    if (!current) return;
    needsReload = true;
    status.textContent = "This recording couldn’t load. Tap Retry playback to try it again, or download it to listen.";
    renderPlayButton();
  });
  ["play", "pause", "ended", "emptied"].forEach(event => audio.addEventListener(event, renderPlayButton));
  audio.addEventListener("play", () => { if (current) updateSongHash(current); });
  find("[data-close-share]").addEventListener("click", () => {
    shareFallback.hidden = true;
    shareTrigger?.focus();
  });
  window.addEventListener("hashchange", () => { if (tracks.length) cueLinkedSong(); });
  const refresh = () => {
    if (document.hidden) return;
    loadTracks();
    if (current) loadCount(current);
  };
  document.addEventListener("visibilitychange", refresh);
  setInterval(refresh, 30000);
  restorePendingPlays();
  loadTracks();
})();
