// Movie clipping for Ninja Studio Clipping: a whole movie → Part 1, Part 2, … Shorts in order (server side: movies.py).
// 1. Analyze: how long the movie is and how many parts it makes (cuts land on pauses in speech).
// 2. Pick the parts, the look and the PART tag, then make them; each finished part also lands in My clips.
(function () {
  const $ = id => document.getElementById(id);
  if (!$('movie-panel')) return;
  let analysis = null, info = null, makeJob = null, timer = null;
  const picked = new Set();
  const ready = new Map();                       // part number → clip file id

  const clock = s => {
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, '0');
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + x : m + ':' + x;
  };
  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw Error(j.detail || 'Request failed');
    return j;
  }
  function progress(show, stage, fraction) {
    $('mv-progress').hidden = !show;
    if (stage != null) $('mv-stage').textContent = stage;
    if (fraction != null) $('mv-bar').style.width = Math.round(Math.max(0, Math.min(1, fraction)) * 100) + '%';
  }
  function source() {
    const url = $('mv-url').value.trim();
    if ($('mv-use-loaded').checked || !url) {
      if (typeof id === 'undefined' || !id) throw Error('Paste the movie link, or upload / load the movie in step 01 and tick “Use the video loaded”.');
      return { id };
    }
    return { url };
  }
  function poll(job, onUpdate) {
    clearInterval(timer);
    return new Promise((resolve, reject) => {
      timer = setInterval(async () => {
        try {
          const row = await api('/movie/' + job);
          onUpdate(row);
          if (row.status !== 'running') { clearInterval(timer); row.status === 'error' ? reject(Error(row.error || 'Failed')) : resolve(row); }
        } catch (e) { clearInterval(timer); reject(e); }
      }, 1500);
    });
  }

  // ---- 1. analyze
  async function analyze() {
    const btn = $('mv-analyze');
    try {
      const body = { ...source(), part_len: Number($('mv-len').value), start: $('mv-start').value.trim(), end: $('mv-end').value.trim() };
      btn.disabled = true;
      $('mv-result').hidden = true;
      progress(true, 'Reading the movie…', 0);
      const { job } = await api('/movie/analyze', body);
      const row = await poll(job, r => progress(true, r.stage, r.progress));
      analysis = job; info = row;
      showResult();
      progress(false);
    } catch (e) {
      progress(true, '⚠ ' + e.message, 0);
    } finally { btn.disabled = false; }
  }

  function showResult() {
    $('mv-result').hidden = false;
    $('mv-count').textContent = info.count;
    const lengths = info.parts.map(p => p.end - p.start);
    $('mv-info').textContent = `${info.title ? info.title + ' · ' : ''}${clock(info.duration)} movie → ${info.count} Shorts of about ${info.part_len} s ` +
      `(${Math.round(Math.min(...lengths))}–${Math.round(Math.max(...lengths))} s). Each cut lands on a pause in speech, so no sentence is cut in half. ` +
      `Subtitles would come from: ${info.captions}.`;
    $('mv-thumb').hidden = !info.thumbnail;
    if (info.thumbnail) $('mv-thumb').src = info.thumbnail;
    if (!$('mv-title').value.trim() || $('mv-title').dataset.auto === '1') { $('mv-title').value = (info.title || '').slice(0, 80); $('mv-title').dataset.auto = '1'; }
    picked.clear(); ready.clear();
    info.parts.forEach(p => picked.add(p.n));
    $('mv-grid').replaceChildren();
    $('mv-upload-now').hidden = true;
    renderParts();
  }

  function renderParts() {
    const box = $('mv-parts');
    box.replaceChildren();
    for (const p of info.parts) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'mv-part' + (picked.has(p.n) ? ' on' : '') + (ready.has(p.n) ? ' done' : '');
      b.setAttribute('aria-pressed', String(picked.has(p.n)));
      const t = document.createElement('b'); t.textContent = ($('mv-label').value.trim() || 'Part') + ' ' + p.n;
      const s = document.createElement('small'); s.textContent = clock(p.start) + ' – ' + clock(p.end) + ' · ' + Math.round(p.end - p.start) + ' s';
      b.append(t, s);
      b.onclick = () => { picked.has(p.n) ? picked.delete(p.n) : picked.add(p.n); renderParts(); };
      box.append(b);
    }
    $('mv-picked').textContent = picked.size + ' of ' + info.parts.length + ' selected';
    $('mv-make').textContent = '🎬 Make ' + picked.size + (picked.size === 1 ? ' part' : ' parts');
    $('mv-make').disabled = !picked.size || !!makeJob;
  }

  // ---- 2. make the parts
  function card(c) {
    const el = document.createElement('div');
    el.className = 'clip-card mv-card';
    if (c.file && !c.error) el.dataset.file = c.file;
    const badge = document.createElement('span'); badge.className = 'mv-badge'; badge.textContent = ($('mv-label').value.trim() || 'PART').toUpperCase() + ' ' + c.n;
    badge.style.background = $('mv-color').value;
    const title = document.createElement('b'); title.textContent = c.title;
    if (c.error) {
      const err = document.createElement('p'); err.className = 'mv-err'; err.textContent = '⚠ ' + c.error;
      el.append(badge, title, err);
      return el;
    }
    const video = document.createElement('video');
    video.controls = true; video.preload = 'none'; video.playsInline = true; video.src = '/media/' + c.file;
    const links = document.createElement('div'); links.className = 'card-links';
    const a = document.createElement('a'); a.href = '/media/' + c.file; a.download = 'ninjastudio-' + (c.title || 'part').replace(/[^\w-]+/g, '-').toLowerCase() + '.mp4'; a.textContent = '↓ Download';
    links.append(a);
    el.append(video, badge, title, links);
    return el;
  }

  async function make() {
    if (!analysis || !picked.size) return;
    if ($('mv-upload').checked && !(window.NeonYouTube && window.NeonYouTube.status().connected)) {
      window.NeonYouTube && window.NeonYouTube.openSettings();
      return alert('Pehle YouTube channel connect kijiye, ya “Upload to YouTube” ka tick hata dijiye.');
    }
    const body = {
      analysis, parts: [...picked].sort((x, y) => x - y), title: $('mv-title').value.trim(), layout: $('mv-layout').value,
      color: $('mv-color').value, label: $('mv-label').value.trim() || 'PART', show_title: $('mv-show-title').checked,
      show_part: $('mv-show-part').checked, show_total: $('mv-show-total').checked, next_hint: $('mv-next').checked,
      captions: $('mv-captions').checked, caption_style: (typeof style !== 'undefined' && style) || 'gta',
      language: $('language') ? $('language').value : '', source_height: Number($('mv-quality').value),
      upload: $('mv-upload').checked, channel: $('mv-channel').value || '', privacy: $('mv-privacy').value,
    };
    try {
      const { job } = await api('/movie/make', body);
      makeJob = job;
      $('mv-grid').dataset.job = job;                          // “Upload all parts” uses it after the run
      $('mv-stop').hidden = false; $('mv-upload-now').hidden = true; $('mv-make').disabled = true; $('mv-analyze').disabled = true;
      $('mv-grid').replaceChildren();
      progress(true, 'Starting…', 0);
      const row = await poll(job, r => {
        progress(true, r.stage, r.progress);
        const shown = $('mv-grid').children.length;
        (r.clips || []).slice(shown).forEach(c => { $('mv-grid').append(card(c)); if (c.file && !c.error) ready.set(c.n, c.file); });
        renderParts();
      });
      progress(true, (row.status === 'stopped' ? '■ ' : '✓ ') + row.stage + (row.uploads ? ' · uploading to YouTube in order, see My clips' : '') +
        (row.upload_error ? ' · YouTube: ' + row.upload_error : ''), 1);
      $('mv-upload-now').hidden = !ready.size || !!row.uploads;
      if (typeof window.updateYtTags === 'function') window.updateYtTags();
    } catch (e) {
      progress(true, '⚠ ' + e.message, 0);
    } finally {
      makeJob = null;
      $('mv-stop').hidden = true; $('mv-analyze').disabled = false;
      if (info) renderParts();
    }
  }

  $('mv-analyze').onclick = analyze;
  $('mv-url').addEventListener('keydown', e => { if (e.key === 'Enter') analyze(); });
  $('mv-make').onclick = make;
  $('mv-title').addEventListener('input', () => { $('mv-title').dataset.auto = '0'; });
  $('mv-label').addEventListener('input', () => info && renderParts());
  document.querySelectorAll('[data-mv-pick]').forEach(b => b.onclick = () => {
    if (!info) return;
    const how = b.dataset.mvPick;
    picked.clear();
    info.parts.forEach(p => { if (how === 'all' || (how !== 'none' && p.n <= Number(how))) picked.add(p.n); });
    renderParts();
  });
  $('mv-stop').onclick = async () => {
    const job = makeJob;
    if (!job) return;
    $('mv-stop').disabled = true;
    try { await api('/movie/' + job + '/stop', {}); progress(true, 'Stopping after the part being made…'); }
    catch (e) { alert(e.message); }
    finally { $('mv-stop').disabled = false; }
  };
  $('mv-upload-now').onclick = async () => {
    const job = $('mv-grid').dataset.job;
    if (!(window.NeonYouTube && window.NeonYouTube.status().connected)) { window.NeonYouTube && window.NeonYouTube.openSettings(); return; }
    try {
      const r = await api('/movie/' + job + '/upload', { channel: $('mv-channel').value || '', privacy: $('mv-privacy').value });
      $('mv-upload-now').hidden = true;
      progress(true, '▶ ' + r.jobs.length + ' parts queued for YouTube, Part 1 first. Progress shows in My clips.', 1);
      if (typeof window.updateYtTags === 'function') window.updateYtTags();
    } catch (e) { alert(e.message); }
  };
  $('nav-movie').onclick = () => {
    const editor = document.querySelector('.sidebar [data-view=editor]');
    if (editor && !editor.classList.contains('active')) editor.click();
    $('movie-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    setTimeout(() => $('mv-url').focus({ preventScroll: true }), 450);
  };
})();
