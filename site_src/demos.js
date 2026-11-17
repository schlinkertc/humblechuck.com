(() => {
  const library = document.querySelector("[data-demo-library]");
  if (!library) return;
  const find = (selector) => library.querySelector(selector);
  const audio = find("[data-demo-audio]");
  const title = find("[data-current-title]");
  const download = find("[data-current-download]");
  const list = find("[data-track-list]");
  const status = find("[data-demo-status]");
  const refresh = find("[data-refresh]");
  const previous = find("[data-previous]");
  const next = find("[data-next]");
  const rewind = find("[data-rewind]");
  const forward = find("[data-forward]");
  const toggle = find("[data-toggle-play]");
  let tracks = [];
  let current = null;
  let loading = false;
  let needsReload = false;
  let playAttempt = 0;

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

  function select(track, autoplay = false) {
    const changed = current?.url !== track.url;
    current = track;
    title.textContent = track.title;
    if (changed) {
      ++playAttempt;
      needsReload = false;
      audio.src = track.url;
      if (autoplay) needsReload = true;
      else audio.load();
    }
    download.href = track.url;
    download.download = track.filename;
    download.hidden = false;
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
      row.append(button, link);
      fragment.append(row);
    });
    list.replaceChildren(fragment);
    find("[data-track-count]").textContent = `(${tracks.length})`;
    renderSelection();
  }

  async function loadTracks() {
    if (loading) return;
    loading = true;
    refresh.disabled = true;
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
      renderTracks();
      status.textContent = tracks.length ? "" : "No recordings here yet. Check back soon.";
      if (!current && tracks.length) select(tracks[0]);
      // Keep uninterrupted playback during a refresh. A paused, replaced song
      // is recued with the latest object version; removed tracks are cleared.
      if (current && audio.paused) {
        const latest = tracks.find((track) => track.id === current.id);
        if (!latest) {
          if (tracks.length) select(tracks[0]);
          else {
            current = null;
            audio.removeAttribute("src");
            audio.load();
            title.textContent = "More songs soon.";
            download.hidden = true;
            renderSelection();
          }
        } else if (latest.url !== current.url) select(latest);
      }
      if (!tracks.length && !current) title.textContent = "More songs soon.";
    } catch (error) {
      status.textContent = tracks.length
        ? "Couldn’t refresh the recordings. You can keep listening or try Refresh."
        : "The recordings couldn’t load. Please try Refresh in a moment.";
      if (!current) title.textContent = "A little quiet right now.";
    } finally {
      clearTimeout(timeout);
      loading = false;
      refresh.disabled = false;
    }
  }

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
  refresh.addEventListener("click", loadTracks);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadTracks(); });
  setInterval(() => { if (!document.hidden) loadTracks(); }, 30000);
  loadTracks();
})();
