// YouTube Integration for Ninja Studio Clipping
// Handles channel connection, auto-upload settings, and one-click Shorts uploads.

(function() {
  let ytStatus = { connected: false, has_secrets: false, channel: null, auto_upload: false, default_privacy: 'public' };
  let activeUploadTask = null;
  let uploadPollTimer = null;

  async function fetchStatus() {
    try {
      const res = await fetch('/youtube/status');
      if (res.ok) {
        ytStatus = await res.json();
        updateUI();
        renderChannels();
        window.dispatchEvent(new CustomEvent('yt-status', { detail: ytStatus }));
      }
    } catch (e) {
      console.warn('YouTube status check failed:', e);
    }
  }

  // ---- several channels: list, switch, remove, add, and the channel pickers (select.yt-channel-select)
  function channels() { return Array.isArray(ytStatus.channels) ? ytStatus.channels : []; }

  function renderChannels() {
    const list = document.getElementById('yt-channel-list');
    const all = channels();
    if (list) {
      list.replaceChildren();
      for (const ch of all) {
        const row = document.createElement('div');
        row.className = 'yt-ch' + (ch.active ? ' active' : '');
        const img = document.createElement('img');
        img.alt = ''; img.referrerPolicy = 'no-referrer';
        if (ch.thumbnail) img.src = ch.thumbnail; else img.hidden = true;
        const info = document.createElement('div');
        info.className = 'yt-ch-info';
        const name = document.createElement('b'); name.textContent = ch.title || 'Channel';
        const sub = document.createElement('small');
        sub.textContent = (ch.subscribers ? ch.subscribers + ' subscribers' : '') + (ch.custom_url ? ' · ' + ch.custom_url : '') + (ch.client ? ' · own Google app' : '') + (ch.live_allowed ? '' : ' · live needs “Allow live streaming”');
        info.append(name, sub);
        row.append(img, info);
        if (ch.active) {
          const tag = document.createElement('span'); tag.className = 'yt-ch-active'; tag.textContent = 'ACTIVE'; row.append(tag);
        } else {
          const sw = document.createElement('button'); sw.type = 'button'; sw.className = 'yt-ch-switch'; sw.textContent = 'Switch';
          sw.onclick = () => channelAction('/youtube/channels/active', ch.id);
          row.append(sw);
        }
        const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'yt-ch-remove'; rm.title = 'Remove this channel from Ninja Studio'; rm.textContent = '✕';
        rm.onclick = () => {
          if (confirm('Remove “' + (ch.title || 'this channel') + '” from Ninja Studio? Nothing changes on YouTube; you can add it again any time.')) channelAction('/youtube/channels/remove', ch.id);
        };
        row.append(rm);
        list.append(row);
      }
    }
    // every channel picker on the page: keep the user's choice, default to the active channel
    document.querySelectorAll('select.yt-channel-select').forEach(sel => {
      const keep = sel.value;
      sel.replaceChildren();
      for (const ch of all) {
        const o = document.createElement('option');
        o.value = ch.id; o.textContent = (ch.title || 'Channel') + (ch.active ? ' (active)' : '');
        sel.append(o);
      }
      sel.value = all.some(c => c.id === keep) ? keep : (ytStatus.active_channel || (all[0] && all[0].id) || '');
      sel.hidden = all.length < 2 && sel.id === 'lib-channel';      // the My clips picker only shows up with 2+ channels
    });
    const glWrap = document.getElementById('gl-channel-wrap');
    if (glWrap) glWrap.hidden = all.length < 2;
    const btn = document.getElementById('yt-header-btn');
    if (btn && ytStatus.connected && ytStatus.channel && all.length > 1) {
      btn.innerHTML = `<span style="color:#22c55e">●</span> ${escapeHtml(ytStatus.channel.title)} <small style="opacity:.75">+${all.length - 1}</small>`;
      btn.title = all.length + ' channels connected · click to switch';
    }
  }

  async function channelAction(url, id) {
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Failed');
    } catch (err) {
      alert(err.message);
    }
    fetchStatus();
  }

  /** Google sign-in for a channel: shows the account / brand-account chooser, so it also adds another channel. */
  async function startAuth() {
    try {
      const res = await fetch('/youtube/auth-url');
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Auth URL error');
      const authWindow = window.open(j.url, '_blank', 'width=600,height=700');
      if (!authWindow) window.location.href = j.url;
    } catch (err) {
      alert('Authentication start nahi ho paaya: ' + err.message);
    }
  }

  /** Add a channel through another Google app: its own client JSON (own test users and daily quota). */
  async function addWithJson(file) {
    const popup = window.open('', '_blank', 'width=600,height=700');   // opened now, while the click still counts, so it is not blocked
    try {
      let secrets;
      try { secrets = JSON.parse(await file.text()); } catch (e) { throw new Error('Yeh file JSON nahi hai. Google Cloud Console se download ki hui client JSON choose kijiye.'); }
      const res = await fetch('/youtube/auth-url-client', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secrets }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || 'Is JSON se login shuru nahi ho paaya');
      if (popup) popup.location.href = j.url; else window.location.href = j.url;
    } catch (err) {
      if (popup) popup.close();
      alert(err.message);
    }
  }

  function updateUI() {
    const btn = document.getElementById('yt-header-btn');
    const badge = document.getElementById('yt-badge');
    const autoCheck = document.getElementById('auto-yt-upload');
    const connectedView = document.getElementById('yt-connected-view');
    const setupView = document.getElementById('yt-setup-view');

    if (autoCheck) {
      autoCheck.checked = Boolean(ytStatus.auto_upload);
    }

    if (btn) btn.title = '';
    if (ytStatus.connected && ytStatus.channel) {
      if (btn) {
        btn.innerHTML = `<span style="color:#22c55e">●</span> ${escapeHtml(ytStatus.channel.title)}`;
        btn.style.background = '#1a221a';
        btn.style.borderColor = '#22c55e';
      }
      if (badge) {
        badge.textContent = 'Connected';
        badge.style.background = '#22c55e';
      }
      if (connectedView) connectedView.hidden = false;
      if (setupView) setupView.hidden = true;

      const chName = document.getElementById('yt-channel-name');
      const chSub = document.getElementById('yt-channel-subs');
      const chThumb = document.getElementById('yt-channel-thumb');
      if (chName) chName.textContent = ytStatus.channel.title || 'Connected Channel';
      if (chSub) chSub.textContent = (ytStatus.channel.subscribers || '0') + ' subscribers';
      if (chThumb) {
        chThumb.hidden = !ytStatus.channel.thumbnail;              // a switched-to channel without a picture: no old picture
        if (ytStatus.channel.thumbnail) chThumb.src = ytStatus.channel.thumbnail;
      }
    } else {
      if (btn) {
        btn.innerHTML = `<span style="color:#ef4444">▶</span> Connect YouTube`;
        btn.style.background = '#2a1215';
        btn.style.borderColor = '#ef4444';
      }
      if (badge) {
        badge.textContent = ytStatus.has_secrets ? 'Ready to Auth' : 'Not setup';
        badge.style.background = ytStatus.has_secrets ? '#f59e0b' : '#ef4444';
      }
      if (connectedView) connectedView.hidden = true;
      if (setupView) setupView.hidden = false;

      const secStatus = document.getElementById('yt-secrets-status');
      if (secStatus) {
        secStatus.textContent = ytStatus.has_secrets ? '✓ client_secrets.json loaded' : 'Missing client_secrets.json';
        secStatus.style.color = ytStatus.has_secrets ? '#22c55e' : '#f59e0b';
      }
      const authBtn = document.getElementById('yt-auth-btn');
      if (authBtn) {
        authBtn.disabled = !ytStatus.has_secrets;
      }
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, m => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  }

  // Hook into cards
  function attachUploadButtons() {
    document.querySelectorAll('.mk, .clip-card').forEach(card => {
      if (card.querySelector('.yt-upload-btn')) return;

      const clipId = card.dataset.file || card.querySelector('a[href^="/media/"]')?.getAttribute('href')?.replace('/media/', '');
      if (!clipId) return;

      const titleEl = card.querySelector('b, h3');
      const clipTitle = titleEl ? titleEl.textContent : 'Ninja Studio Highlight';

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'yt-upload-btn';
      btn.innerHTML = '▶ Upload to YouTube';
      btn.title = 'Upload this clip as a YouTube Short';
      btn.style.cssText = 'background:#cc0000;color:#fff;border:none;padding:5px 10px;border-radius:4px;cursor:pointer;font-weight:600;font-size:12px;margin:4px 0;display:inline-flex;align-items:center;gap:4px;';

      btn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        openUploadModal(clipId, clipTitle);
      };

      // Append near other action buttons (Edit clip, Download)
      const targetContainer = card.querySelector('.card-links') || card;
      targetContainer.appendChild(btn);
    });
  }

  function openUploadModal(clipId, defaultTitle) {
    if (!ytStatus.connected) {
      openSettingsModal();
      alert('Pehle apna YouTube channel connect kijiye!');
      return;
    }

    const dialog = document.getElementById('yt-upload-modal');
    if (!dialog) return;

    document.getElementById('yt-up-clip-id').value = clipId;
    let titleVal = defaultTitle || 'My Clip';
    if (!titleVal.toLowerCase().includes('#shorts')) {
      titleVal = `${titleVal} #Shorts`;
    }
    document.getElementById('yt-up-title').value = titleVal;
    document.getElementById('yt-up-desc').value = `${titleVal}\n\nClip generated automatically with Ninja Studio Clipping\n#Shorts #Viral #Trending`;
    document.getElementById('yt-up-tags').value = 'Shorts, Viral, NinjaStudio';
    document.getElementById('yt-up-privacy').value = ytStatus.default_privacy || 'public';
    
    const statusBox = document.getElementById('yt-up-status');
    statusBox.textContent = '';
    statusBox.hidden = true;
    document.getElementById('yt-up-submit').disabled = false;
    document.getElementById('yt-up-submit').textContent = 'Upload to Shorts ↗';

    dialog.showModal();
  }

  function openSettingsModal() {
    const dialog = document.getElementById('yt-settings-modal');
    if (dialog) dialog.showModal();
  }

  // Setup DOM listeners
  window.addEventListener('DOMContentLoaded', () => {
    fetchStatus();

    // Observe changes in clip containers
    const observer = new MutationObserver(() => {
      attachUploadButtons();
    });

    ['make-grid', 'library', 'live-grid'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        observer.observe(el, { childList: true, subtree: true });
      }
    });

    setInterval(attachUploadButtons, 2500);

    // Header Connect Button
    const headerBtn = document.getElementById('yt-header-btn');
    if (headerBtn) {
      headerBtn.onclick = openSettingsModal;
    }

    // Modal Close buttons
    document.getElementById('yt-settings-close')?.addEventListener('click', () => {
      document.getElementById('yt-settings-modal')?.close();
    });
    document.getElementById('yt-upload-close')?.addEventListener('click', () => {
      document.getElementById('yt-upload-modal')?.close();
    });

    // Auto-upload toggle in settings
    document.getElementById('yt-auto-upload-cfg')?.addEventListener('change', async (e) => {
      await fetch('/youtube/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_upload: e.target.checked })
      });
      fetchStatus();
    });

    // Auto-upload checkbox in Make Clips panel
    document.getElementById('auto-yt-upload')?.addEventListener('change', async (e) => {
      await fetch('/youtube/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_upload: e.target.checked })
      });
      fetchStatus();
    });

    // Disconnect button
    document.getElementById('yt-disconnect-btn')?.addEventListener('click', async () => {
      if (confirm('Kya aap sach me apna YouTube channel disconnect karna chahte hain?')) {
        await fetch('/youtube/disconnect', { method: 'POST' });
        fetchStatus();
      }
    });

    // Upload client_secrets file
    const secFile = document.getElementById('yt-secrets-file');
    secFile?.addEventListener('change', async () => {
      if (!secFile.files[0]) return;
      const form = new FormData();
      form.append('file', secFile.files[0]);
      try {
        const res = await fetch('/youtube/secrets', { method: 'POST', body: form });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || 'Upload failed');
        alert('client_secrets.json successfully save ho gaya!');
        fetchStatus();
      } catch (err) {
        alert('Error: ' + err.message);
      }
    });

    // Paste client_secrets JSON
    document.getElementById('yt-save-secrets-btn')?.addEventListener('click', async () => {
      const txt = document.getElementById('yt-secrets-json').value.trim();
      if (!txt) return alert('Pehle JSON paste kijiye');
      try {
        const parsed = JSON.parse(txt);
        const res = await fetch('/youtube/secrets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(parsed)
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || 'Save failed');
        alert('Credentials successfully save ho gaye!');
        document.getElementById('yt-secrets-json').value = '';
        fetchStatus();
      } catch (err) {
        alert('Invalid JSON ya error: ' + err.message);
      }
    });

    // Authorize button (starts Google OAuth)
    document.getElementById('yt-auth-btn')?.addEventListener('click', startAuth);
    document.getElementById('yt-add-channel')?.addEventListener('click', startAuth);
    document.getElementById('yt-add-json')?.addEventListener('change', e => {
      const file = e.target.files[0];
      e.target.value = '';                                  // the same file can be chosen again
      if (file) addWithJson(file);
    });

    // Manual code submit (if user pastes redirect code)
    document.getElementById('yt-code-submit')?.addEventListener('click', async () => {
      const code = document.getElementById('yt-code-input').value.trim();
      if (!code) return alert('Auth Code paste kijiye');
      try {
        const res = await fetch('/youtube/auth-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code })
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || 'Code exchange failed');
        alert('YouTube channel successfully connect ho gaya!');
        document.getElementById('yt-code-input').value = '';
        fetchStatus();
      } catch (err) {
        alert('Error: ' + err.message);
      }
    });

    // Submit upload to YouTube
    document.getElementById('yt-up-submit')?.addEventListener('click', async () => {
      const clipId = document.getElementById('yt-up-clip-id').value;
      const title = document.getElementById('yt-up-title').value.trim();
      const description = document.getElementById('yt-up-desc').value.trim();
      const privacy = document.getElementById('yt-up-privacy').value;
      const tags = document.getElementById('yt-up-tags').value.split(',').map(s => s.trim()).filter(Boolean);

      const submitBtn = document.getElementById('yt-up-submit');
      const statusBox = document.getElementById('yt-up-status');

      submitBtn.disabled = true;
      submitBtn.textContent = 'Uploading...';
      statusBox.hidden = false;
      statusBox.style.color = '#38bdf8';
      statusBox.textContent = 'Starting upload to YouTube...';

      try {
        const res = await fetch('/youtube/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clip_id: clipId, title, description, privacy, tags, channel: document.getElementById('yt-up-channel')?.value || '' })
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || 'Upload request failed');

        activeUploadTask = j.task_id;
        if (typeof window.updateYtTags === 'function') window.updateYtTags();
        pollUpload(j.task_id);
      } catch (err) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Retry Upload';
        statusBox.style.color = '#ef4444';
        statusBox.textContent = 'Failed: ' + err.message;
      }
    });

    // Listen for OAuth message from child popup
    window.addEventListener('message', (event) => {
      if (event.data === 'youtube_connected') {
        fetchStatus();
      }
    });

    initCustomCam();
  });

  // Custom Face Video Handler
  function initCustomCam() {
    const fileInput = document.getElementById('custom-cam-file');
    const removeBtn = document.getElementById('custom-cam-remove');
    const infoBox = document.getElementById('custom-cam-info');
    const nameEl = document.getElementById('custom-cam-name');
    const previewEl = document.getElementById('custom-cam-preview');

    function setCamUI(id, name) {
      window.customCamId = id;
      if (id) {
        if (infoBox) infoBox.style.display = 'flex';
        if (removeBtn) removeBtn.style.display = 'inline-block';
        if (nameEl) nameEl.textContent = name || 'My Facecam Video';
        if (previewEl) previewEl.src = `/asset-file/video/${id}`;
      } else {
        if (infoBox) infoBox.style.display = 'none';
        if (removeBtn) removeBtn.style.display = 'none';
        if (previewEl) previewEl.src = '';
      }
    }

    const saved = localStorage.getItem('neon_custom_cam');
    if (saved) {
      try {
        const obj = JSON.parse(saved);
        setCamUI(obj.id, obj.name);
      } catch (e) {}
    }

    fileInput?.addEventListener('change', async () => {
      const file = fileInput.files[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      try {
        const res = await fetch('/upload-asset?kind=video', { method: 'POST', body: form });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || 'Upload failed');
        localStorage.setItem('neon_custom_cam', JSON.stringify({ id: j.id, name: j.name }));
        setCamUI(j.id, j.name);
        alert('Custom facecam video successfully upload ho gaya! Ye aapki clips mein loop hokar chalega.');
      } catch (err) {
        alert('Facecam upload error: ' + err.message);
      }
    });

    removeBtn?.addEventListener('click', () => {
      window.customCamId = null;
      localStorage.removeItem('neon_custom_cam');
      setCamUI(null, null);
    });
  }

  async function pollUpload(taskId) {
    if (uploadPollTimer) clearInterval(uploadPollTimer);

    const submitBtn = document.getElementById('yt-up-submit');
    const statusBox = document.getElementById('yt-up-status');

    uploadPollTimer = setInterval(async () => {
      try {
        const res = await fetch('/youtube/upload-status/' + taskId);
        if (!res.ok) return;
        const task = await res.json();

        if (task.status === 'uploading' || task.status === 'starting') {
          const pct = Math.round((task.progress || 0) * 100);
          statusBox.textContent = task.stage || `Uploading... ${pct}%`;
        } else if (task.status === 'done') {
          clearInterval(uploadPollTimer);
          submitBtn.disabled = false;
          submitBtn.textContent = 'Uploaded ✓';
          statusBox.style.color = '#22c55e';
          statusBox.innerHTML = `✅ Successfully Uploaded!<br><a href="${task.url}" target="_blank" rel="noopener" style="color:#38bdf8;font-weight:bold;text-decoration:underline;">View on YouTube Shorts ↗</a>`;
          if (typeof window.updateYtTags === 'function') window.updateYtTags();
        } else if (task.status === 'error') {
          clearInterval(uploadPollTimer);
          submitBtn.disabled = false;
          submitBtn.textContent = 'Try Again';
          statusBox.style.color = '#ef4444';
          statusBox.textContent = 'Upload failed: ' + (task.error || 'Unknown error');
        }
      } catch (e) {
        console.warn('Poll error:', e);
      }
    }, 1500);
  }

  // Expose global helpers
  window.NeonYouTube = {
    fetchStatus,
    openSettings: openSettingsModal,
    openUpload: openUploadModal,
    status: () => ytStatus,
    channels
  };
})();
