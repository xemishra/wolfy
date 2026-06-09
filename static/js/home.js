let ws = null;
let wsToken = null;
let currentPeer = window.WOLFY_PEER || null;
let isRandomMatch = false;
let searching = false;
let searchGeneration = 0;
let searchTimerIds = [];
let unreadByPeer = {};
let totalUnread = window.WOLFY_UNREAD || 0;
let reconnectTimer = null;
let currentSessionId = null;
let chatSessionGeneration = 0;
let savedContactPeer = null;
let pendingReply = null;
let lastOutgoingRow = null;
const messageById = new Map();
let pendingFindMatch = false;
let cancelMatchOnReconnect = false;

function isContactPage() {
  return !!document.getElementById('contactChatView');
}

function getMessagesArea() {
  if (isRandomMatch) return getRandomMessagesArea();
  return document.getElementById('messagesArea');
}

function isStaleRandomEvent(msg) {
  if (!isRandomMatch) return false;
  if (!currentPeer || !currentSessionId) return true;
  if (msg.session_id && msg.session_id !== currentSessionId) return true;
  const fromUid = msg.from_uid || msg.peer?.uid;
  if (fromUid && fromUid !== currentPeer.uid) return true;
  return false;
}

function isStaleRandomMessage(msg) {
  if (!isRandomMatch) return false;
  return isStaleRandomEvent(msg);
}

function clearUnreadLocal(peerUid) {
  if (!peerUid) return;
  delete unreadByPeer[peerUid];
  totalUnread = sumUnread();
  syncUnreadUI();
}

function applyUnreadSync(msg) {
  if (msg.unread && typeof msg.unread === 'object') {
    unreadByPeer = { ...msg.unread };
  } else if (msg.from_uid) {
    if (msg.count > 0) unreadByPeer[msg.from_uid] = msg.count;
    else delete unreadByPeer[msg.from_uid];
  }
  if (typeof msg.total === 'number') {
    totalUnread = msg.total;
  } else {
    totalUnread = sumUnread();
  }
  syncUnreadUI();
}

function clearTyping() {
  if (typingEl) {
    typingEl.remove();
    typingEl = null;
  }
}

function getRandomMessagesArea() {
  return document.getElementById('randomMessagesArea');
}

function resetRandomChatUI() {
  clearTyping();
  cancelReply();
  messageById.clear();
  lastOutgoingRow = null;
  const area = getRandomMessagesArea();
  if (area) area.innerHTML = '';
  const av = document.getElementById('matchAvatar');
  if (av) {
    if (av.querySelector('img')) av.innerHTML = '';
    av.textContent = '?';
  }
  const name = document.getElementById('matchName');
  if (name) name.textContent = 'Stranger';
  _resetKeepBtn();
  document.getElementById('matchActions')?.classList.remove('hidden');
}

function deactivateRandomSession({ restoreContact = false } = {}) {
  chatSessionGeneration++;
  currentPeer = restoreContact && savedContactPeer ? savedContactPeer : (restoreContact ? window.WOLFY_PEER || null : null);
  currentSessionId = null;
  isRandomMatch = false;
  savedContactPeer = null;
  clearTyping();
  document.getElementById('randomChatView')?.classList.add('hidden');
  document.getElementById('matchActions')?.classList.add('hidden');

  if (isContactPage()) {
    document.getElementById('contactChatView')?.classList.remove('hidden');
    if (restoreContact && window.WOLFY_PEER) {
      currentPeer = window.WOLFY_PEER;
      notifyViewingChat(currentPeer.uid);
    }
  } else {
    document.getElementById('chatPlaceholder')?.classList.remove('hidden');
    notifyViewingChat(null);
  }
  syncComposerVisibility();
}

function activateRandomSession(peer) {
  chatSessionGeneration++;
  const gen = chatSessionGeneration;

  clearTyping();

  if (isContactPage()) {
    savedContactPeer = window.WOLFY_PEER
      ? { ...window.WOLFY_PEER }
      : (currentPeer ? { ...currentPeer } : null);
    document.getElementById('contactChatView')?.classList.add('hidden');
  } else {
    document.getElementById('chatPlaceholder')?.classList.add('hidden');
  }

  currentSessionId = peer.session_id || null;
  currentPeer = { ...peer };
  isRandomMatch = true;

  document.getElementById('randomChatView')?.classList.remove('hidden');
  resetRandomChatUI();

  const av = document.getElementById('matchAvatar');
  if (av) {
    if (peer.photo_url) av.innerHTML = `<img src="${escAttr(peer.photo_url)}" alt=""/>`;
    else av.textContent = (peer.display_name || '?')[0].toUpperCase();
  }
  const nameEl = document.getElementById('matchName');
  if (nameEl) nameEl.textContent = peer.display_name || 'Stranger';

  const area = getRandomMessagesArea();
  if (area) {
    area.innerHTML = '';
    const sys = document.createElement('div');
    sys.className = 'sys-msg';
    sys.textContent = 'Connected! Say hi.';
    area.appendChild(sys);
  }

  notifyViewingChat(peer.uid);
  syncComposerVisibility();
  focusComposer();

  return gen;
}

function hasServerSession() {
  return !!(window.WOLFY_USER && window.WOLFY_USER.uid);
}

function startRealtime(user) {
  if (user) {
    user.getIdToken(true).then(token => {
      wsToken = token;
      openWS(token);
    });
  } else if (hasServerSession()) {
    openWS();
  }
  requestNotificationPermission();
  if (currentPeer && !isRandomMatch) {
    clearUnreadLocal(currentPeer.uid);
    notifyViewingChat(currentPeer.uid);
    wsSend({ type: 'mark_read', peer_uid: currentPeer.uid });
    scrollBottom();
  }
}

window.addEventListener('load', () => {
  if (!window.FIREBASE_CFG) return;
  firebase.initializeApp(window.FIREBASE_CFG);
  firebase.auth().onAuthStateChanged(user => {
    if (user) {
      startRealtime(user);
      return;
    }
    if (hasServerSession()) {
      startRealtime(null);
      return;
    }
    window.location.href = '/';
  });
});

function openWS(token) {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    try { ws.close(); } catch (_) {}
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const qs = token ? `?token=${encodeURIComponent(token)}` : '';
  ws = new WebSocket(`${proto}://${location.host}/ws${qs}`);
  ws.onopen = () => {
    if (cancelMatchOnReconnect) {
      cancelMatchOnReconnect = false;
      wsSend({ type: 'cancel_match' });
    }
    if (currentPeer && !isRandomMatch) {
      clearUnreadLocal(currentPeer.uid);
      notifyViewingChat(currentPeer.uid);
      wsSend({ type: 'mark_read', peer_uid: currentPeer.uid });
    }
    if (pendingFindMatch) {
      pendingFindMatch = false;
      if (!wsSend({ type: 'find_match' })) {
        showToast('Could not start matching. Try Connect again.');
        exitSearchingState();
      }
    }
  };
  ws.onmessage = e => {
    try {
      handle(JSON.parse(e.data));
    } catch (err) {
      console.warn('[Wolfy] Bad WebSocket frame', err);
    }
  };
  ws.onclose = () => {
    if (searching) {
      cancelMatchOnReconnect = true;
      exitSearchingState();
    }
    reconnectTimer = setTimeout(async () => {
      const user = firebase.auth().currentUser;
      if (user) {
        openWS(await user.getIdToken(true));
      } else if (hasServerSession()) {
        openWS();
      }
    }, 3000);
  };
}

function wsSend(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
    return true;
  }
  return false;
}

function wsSendSession(payload) {
  if (!currentSessionId) return false;
  return wsSend({ ...payload, session_id: currentSessionId });
}

function notifyViewingChat(peerUid) {
  wsSend({ type: 'viewing_chat', peer_uid: peerUid || null });
}

function handle(msg) {
  switch (msg.type) {

    case 'unread_sync':
      applyUnreadSync(msg);
      break;

    case 'unread_update':
      applyUnreadSync(msg);
      break;

    case 'presence':
      updatePresenceUI(msg.uid, msg.online);
      break;

    case 'message': {
      if (isStaleRandomMessage(msg)) break;

      const fromUid = msg.from_uid;
      const inThread = currentPeer && fromUid === currentPeer.uid;
      if (inThread) {
        appendMessage('them', msg, msg.display_name, msg.photo_url);
        scrollBottom();
        if (!isRandomMatch) {
          wsSend({ type: 'mark_read', peer_uid: fromUid });
          clearUnreadLocal(fromUid);
        }
      } else {
        updateContactPreview(fromUid, msg.preview || msg.text, false);
        showToast(`💬 ${msg.display_name}: ${(msg.preview || msg.text).slice(0, 50)}`);
        pushNotification(msg.display_name, msg.preview || msg.text, fromUid);
      }
      break;
    }

    case 'message_ack':
      if (msg.message_id && lastOutgoingRow) {
        const prevId = lastOutgoingRow.dataset.messageId;
        registerMessageRow(lastOutgoingRow, msg.message_id);
        if (pendingReply && prevId && pendingReply.message_id === prevId) {
          pendingReply.message_id = msg.message_id;
          updateReplyPreviewUI();
        }
        if (msg.reply_to) {
          const quote = lastOutgoingRow.querySelector('.msg-reply-quote');
          if (quote && msg.reply_to.message_id) {
            quote.dataset.replyTarget = msg.reply_to.message_id;
          }
        }
        lastOutgoingRow = null;
      }
      if (!isRandomMatch) {
        updateContactPreview(msg.to_uid, msg.preview || '', true);
      }
      break;

    case 'match_found': {
      const peer = msg.peer;
      if (!peer?.uid) break;
      if (isRandomMatch && currentPeer && currentPeer.uid !== peer.uid) break;
      clearPendingSearch();
      exitSearchingState();

      const gen = activateRandomSession(peer);
      if (gen !== chatSessionGeneration) {
        deactivateRandomSession({ restoreContact: isContactPage() });
      }
      break;
    }

    case 'peer_disconnected':
      if (msg.session_id && currentSessionId && msg.session_id !== currentSessionId) break;
      if (isStaleRandomEvent(msg)) break;
      clearPendingSearch();
      exitSearchingState();
      appendSys('Stranger disconnected.');
      deactivateRandomSession({ restoreContact: isContactPage() });
      if (!isContactPage()) startSearch(1200);
      break;

    case 'skipped_ok':
      clearPendingSearch();
      exitSearchingState();
      deactivateRandomSession({ restoreContact: isContactPage() });
      startSearch(700);
      break;

    case 'skipped_find_new':
      if (msg.session_id && currentSessionId && msg.session_id !== currentSessionId) break;
      clearPendingSearch();
      exitSearchingState();
      deactivateRandomSession({ restoreContact: isContactPage() });
      startSearch(800);
      break;

    case 'typing':
      if (isStaleRandomEvent(msg)) break;
      if (currentPeer && msg.from_uid === currentPeer.uid) showTyping();
      break;

    case 'keep_pending':
      showToast('Waiting to see if they want to keep you too…');
      _setKeepBtnPending();
      break;

    case 'mutual_keep':
      _onMutualKeep(msg.peer_uid, msg.display_name);
      break;

    case 'peer_wants_keep':
      showToast('👀 They want to keep you!');
      break;

    case 'error':
      showToast(msg.message || 'Something went wrong');
      break;
  }
}

function _setKeepBtnPending() {
  const btn = document.getElementById('keepBtn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Waiting…';
}

function _resetKeepBtn() {
  const btn = document.getElementById('keepBtn');
  if (!btn) return;
  btn.disabled = false;
  btn.textContent = '💚 Keep';
}

function _onMutualKeep(peerUid, displayName) {
  showToast(`🎉 Mutual! ${displayName} is now in your contacts.`);
  deactivateRandomSession({ restoreContact: false });
  setTimeout(() => location.reload(), 1800);
}

function replyPreviewText(msg) {
  const msgType = msg.msg_type || 'text';
  const text = (msg.text || '').trim();
  if (text) return text.length > 80 ? text.slice(0, 79) + '…' : text;
  if (msgType === 'image') return 'Photo';
  if (msgType === 'file') return msg.attachment?.filename || 'File';
  return 'Message';
}

function buildReplySnapshot(msg, role) {
  const messageId = msg.message_id;
  if (!isPersistedMessageId(messageId)) {
    showToast('Wait for the message to send before replying to it');
    return null;
  }
  const isMe = role === 'me';
  return {
    message_id: messageId,
    from_uid: msg.from_uid || (isMe ? window.WOLFY_USER?.uid : currentPeer?.uid) || '',
    sender_label: isMe ? 'You' : (currentPeer?.display_name || window.WOLFY_PEER?.display_name || 'User'),
    msg_type: msg.msg_type || 'text',
    text: replyPreviewText(msg),
    unavailable: !!msg.reply_to?.unavailable,
  };
}

function startReply(msg, role) {
  const snap = buildReplySnapshot(msg, role);
  if (!snap) return;
  pendingReply = snap;
  updateReplyPreviewUI();
  focusComposer();
}

function cancelReply() {
  pendingReply = null;
  updateReplyPreviewUI();
}

function updateReplyPreviewUI() {
  const bar = document.getElementById('replyPreviewBar');
  const label = document.getElementById('replyPreviewLabel');
  const textEl = document.getElementById('replyPreviewText');
  if (!bar) return;
  if (!pendingReply) {
    bar.classList.add('hidden');
    return;
  }
  bar.classList.remove('hidden');
  if (label) label.textContent = `Replying to ${pendingReply.sender_label}`;
  if (textEl) {
    let t = pendingReply.text || '';
    if (pendingReply.msg_type === 'image') t = '📷 ' + t;
    else if (pendingReply.msg_type === 'file') t = '📎 ' + t;
    textEl.textContent = t;
  }
}

function registerMessageRow(row, messageId) {
  if (!row || !messageId) return;
  const prev = row.dataset.messageId;
  if (prev && prev !== messageId) messageById.delete(prev);
  row.dataset.messageId = messageId;
  messageById.set(messageId, row);
}

function newLocalMessageId() {
  const suffix = (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  return `local-${suffix}`;
}

function isPersistedMessageId(id) {
  return !!id && !String(id).startsWith('local-');
}

function scrollToMessage(messageId) {
  if (!messageId) return;
  const row = messageById.get(messageId)
    || document.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
  if (!row) {
    showToast('Original message is not loaded');
    return;
  }
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  row.classList.add('msg-highlight');
  setTimeout(() => row.classList.remove('msg-highlight'), 1200);
}

function buildReplyQuoteHtml(replyTo) {
  if (!replyTo) return '';
  const unavailable = replyTo.unavailable;
  const target = replyTo.message_id || '';
  const sender = esc(replyTo.sender_label || 'Message');
  let text = replyTo.text || '';
  if (replyTo.msg_type === 'image') text = '📷 ' + text;
  else if (replyTo.msg_type === 'file') text = '📎 ' + text;
  const tag = 'div';
  return `<${tag} class="msg-reply-quote${unavailable ? ' unavailable' : ''}" role="button" tabindex="0" data-reply-target="${escAttr(target)}"${unavailable ? ' data-unavailable="1"' : ''} title="Jump to message">
    <span class="msg-reply-sender">${sender}</span>
    <span class="msg-reply-text">${esc(text)}</span>
  </${tag}>`;
}

function bindReplyQuotes(root) {
  root.querySelectorAll('.msg-reply-quote').forEach(el => {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    const activate = e => {
      e.preventDefault();
      e.stopPropagation();
      if (el.dataset.unavailable === '1') return;
      scrollToMessage(el.dataset.replyTarget);
    };
    el.addEventListener('click', activate);
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') activate(e);
    });
  });
}

function bindMessageRow(row, role, msg) {
  if (!row || row.dataset.bound) return;
  row.dataset.bound = '1';
  if (msg?.message_id) registerMessageRow(row, msg.message_id);

  row.addEventListener('contextmenu', e => {
    e.preventDefault();
    startReply(msg, role);
  });

  let pressTimer = null;
  row.addEventListener('touchstart', () => {
    pressTimer = setTimeout(() => startReply(msg, role), 500);
  }, { passive: true });
  row.addEventListener('touchend', () => clearTimeout(pressTimer));
  row.addEventListener('touchmove', () => clearTimeout(pressTimer));

  bindReplyQuotes(row);
}

function loadServerMessagesById() {
  const byId = new Map();
  const el = document.getElementById('wolfyMessagesJson');
  if (!el) return byId;
  try {
    const list = JSON.parse(el.textContent || '[]');
    if (Array.isArray(list)) {
      list.forEach(m => {
        if (m?.message_id) byId.set(m.message_id, m);
      });
    }
  } catch (_) {}
  return byId;
}

function initExistingMessages() {
  const area = document.getElementById('messagesArea');
  if (!area) return;
  const byId = loadServerMessagesById();
  area.querySelectorAll('.msg-row[data-message-id]').forEach(row => {
    let msg = byId.get(row.dataset.messageId) || null;
    if (!msg) {
      msg = {
        message_id: row.dataset.messageId,
        msg_type: 'text',
        text: row.querySelector('.msg-text')?.textContent
          || row.querySelector('.msg-caption')?.textContent || '',
      };
    }
    const role = row.classList.contains('me') ? 'me' : 'them';
    bindMessageRow(row, role, msg);
  });
}

function sendMsg() {
  if (!currentPeer) return;
  const input = document.getElementById('msgInput');
  const text = input?.value.trim();
  if (!text) return;

  const payload = { type: 'message', to_uid: currentPeer.uid, text };
  const replySnap = pendingReply ? { ...pendingReply } : null;
  if (replySnap?.message_id) {
    if (!isPersistedMessageId(replySnap.message_id)) {
      showToast('Wait for the original message to finish sending');
      return;
    }
    payload.reply_to_id = replySnap.message_id;
  }

  if (isRandomMatch) {
    if (!currentSessionId) {
      showToast('Session expired. Reconnecting…');
      return;
    }
    payload.session_id = currentSessionId;
  }

  if (!wsSend(payload)) {
    showToast('Reconnecting… try again in a moment.');
    return;
  }
  input.value = '';
  const localMsg = {
    message_id: newLocalMessageId(),
    msg_type: 'text',
    text,
    timestamp: new Date().toISOString(),
  };
  if (replySnap) localMsg.reply_to = replySnap;
  const me = window.WOLFY_USER || {};
  lastOutgoingRow = appendMessage('me', localMsg, me.display_name || 'You', me.photo_url || '');
  cancelReply();
  scrollBottom();
  if (!isRandomMatch) {
    updateContactPreview(currentPeer.uid, text, true);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initComposerHandlers();
  initExistingMessages();
  document.getElementById('replyPreviewCancel')?.addEventListener('click', cancelReply);
  syncComposerVisibility();

  document.getElementById('sendBtn')?.addEventListener('click', sendMsg);
  document.getElementById('msgInput')?.addEventListener('keydown', e => {
    if (e.key === 'Escape' && pendingReply) { cancelReply(); return; }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
  });

  let tTimer;
  document.getElementById('msgInput')?.addEventListener('input', () => {
    if (!currentPeer) return;
    clearTimeout(tTimer);
    tTimer = setTimeout(() => {
      const payload = { type: 'typing', to_uid: currentPeer.uid };
      if (isRandomMatch) {
        if (!currentSessionId) return;
        payload.session_id = currentSessionId;
      }
      wsSend(payload);
    }, 200);
  });

  document.getElementById('connectBtn')?.addEventListener('click', () => {
    if (searching) { cancelSearch(); return; }
    beginRandomConnect();
  });

  document.getElementById('cancelConnectBtn')?.addEventListener('click', cancelSearch);

  document.getElementById('keepBtn')?.addEventListener('click', () => {
    if (!currentPeer || !isRandomMatch) return;
    wsSendSession({ type: 'keep', peer_uid: currentPeer.uid });
    _setKeepBtnPending();
  });

  document.getElementById('skipBtn')?.addEventListener('click', () => {
    if (!currentPeer || !isRandomMatch) return;
    const peerUid = currentPeer.uid;
    const sid = currentSessionId;

    clearPendingSearch();
    chatSessionGeneration++;
    deactivateRandomSession({ restoreContact: isContactPage() });

    const payload = { type: 'skip', peer_uid: peerUid };
    if (sid) payload.session_id = sid;
    wsSend(payload);
  });

  document.getElementById('moreBtn')?.addEventListener('click', e => {
    e.preventDefault();
    e.stopPropagation();
    document.getElementById('profileMenu')?.classList.toggle('hidden');
  });
  document.getElementById('profileMenu')?.addEventListener('click', e => {
    e.stopPropagation();
  });
  document.addEventListener('click', e => {
    const menu = document.getElementById('profileMenu');
    if (!menu || menu.classList.contains('hidden')) return;
    if (e.target.closest('#profileMenu') || e.target.closest('#moreBtn')) return;
    menu.classList.add('hidden');
  });

  document.getElementById('editProfileBtn')?.addEventListener('click', e => {
    e.stopPropagation();
    document.getElementById('profileMenu')?.classList.add('hidden');
    document.getElementById('editModal')?.classList.remove('hidden');
  });
  document.getElementById('settingsBtn')?.addEventListener('click', e => {
    e.stopPropagation();
    document.getElementById('profileMenu')?.classList.add('hidden');
    document.getElementById('settingsModal')?.classList.remove('hidden');
  });
  document.getElementById('closeEdit')?.addEventListener('click', () =>
    document.getElementById('editModal')?.classList.add('hidden'));
  document.getElementById('closeSettings')?.addEventListener('click', () =>
    document.getElementById('settingsModal')?.classList.add('hidden'));

  document.querySelectorAll('.modal-overlay').forEach(m =>
    m.addEventListener('click', e => { if (e.target === m) m.classList.add('hidden'); }));

  document.getElementById('searchInput')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('.contact-item').forEach(el => {
      el.style.display = el.dataset.name?.includes(q) ? '' : 'none';
    });
  });

  document.getElementById('newMessagesBanner')?.addEventListener('click', () => {
    const first = document.querySelector('.contact-item.has-unread');
    if (first) first.click();
  });

  window.addEventListener('beforeunload', () => {
    wsSend({ type: 'viewing_chat', peer_uid: null });
  });

  if (currentPeer && !isRandomMatch) {
    clearUnreadLocal(currentPeer.uid);
  }
  syncUnreadUI();
});

function sumUnread() {
  return Object.values(unreadByPeer).reduce((a, b) => a + b, 0);
}

function syncUnreadUI() {
  const fmt = n => (n > 99 ? '99+' : String(n));

  const banner = document.getElementById('newMessagesBanner');
  const pill = document.getElementById('totalUnreadPill');
  const dot = document.getElementById('profileUnreadDot');

  if (banner) banner.classList.toggle('hidden', totalUnread <= 0);
  if (pill) pill.textContent = fmt(totalUnread);
  if (dot) dot.classList.toggle('hidden', totalUnread <= 0);

  document.querySelectorAll('[data-unread-badge]').forEach(el => {
    const uid = el.dataset.unreadBadge;
    const n = unreadByPeer[uid] || 0;
    el.textContent = fmt(n);
    el.classList.toggle('hidden', n <= 0);
    el.closest('.contact-item')?.classList.toggle('has-unread', n > 0);
  });
}

function updateContactPreview(peerUid, text, isMe) {
  const el = document.querySelector(`[data-preview="${peerUid}"]`);
  if (!el || !text) return;
  const snippet = text.length > 60 ? text.slice(0, 59) + '…' : text;
  el.textContent = isMe ? `You: ${snippet}` : snippet;
}

function updatePresenceUI(uid, online) {
  document.querySelectorAll(`.contact-item[data-uid="${uid}"]`).forEach(item => {
    const wrap = item.querySelector('.contact-av-wrap');
    if (!wrap) return;
    let dot = wrap.querySelector('.online-dot');
    if (online) {
      if (!dot) {
        dot = document.createElement('div');
        dot.className = 'online-dot';
        wrap.appendChild(dot);
      }
    } else if (dot) {
      dot.remove();
    }
  });

  if (window.WOLFY_PEER && window.WOLFY_PEER.uid === uid) {
    const status = document.getElementById('peerStatus');
    if (status) {
      status.innerHTML = online
        ? '<span class="dot-green"></span> Online'
        : '<span class="dot-grey"></span> Offline';
    }
  }
}

function beginRandomConnect() {
  if (isRandomMatch) {
    showToast('Skip your current chat first');
    return;
  }
  chatSessionGeneration++;
  currentSessionId = null;
  isRandomMatch = false;
  clearTyping();
  document.getElementById('randomChatView')?.classList.add('hidden');
  resetRandomChatUI();
  if (!isContactPage()) {
    currentPeer = null;
  }
  notifyViewingChat(null);
  syncComposerVisibility();
  startSearch(0);
}

function cancelSearchTimers() {
  searchTimerIds.forEach(id => clearTimeout(id));
  searchTimerIds = [];
}

function clearPendingSearch() {
  cancelSearchTimers();
  searchGeneration++;
}

function exitSearchingState() {
  searching = false;
  pendingFindMatch = false;
  resetConnectBtn();
  document.getElementById('connectingModal')?.classList.add('hidden');
}

function startSearch(delayMs) {
  cancelSearchTimers();
  const gen = ++searchGeneration;
  const id = setTimeout(() => {
    if (gen !== searchGeneration) return;
    if (searching) return;
    if (isRandomMatch) return;
    searching = true;
    const btn = document.getElementById('connectBtn');
    if (btn) { btn.textContent = 'Cancel'; btn.classList.add('searching'); }
    document.getElementById('connectingModal')?.classList.remove('hidden');
    if (!wsSend({ type: 'find_match' })) {
      if (ws && ws.readyState === WebSocket.CONNECTING) {
        pendingFindMatch = true;
        return;
      }
      showToast('Connecting… wait a moment and try again.');
      exitSearchingState();
    }
  }, delayMs);
  searchTimerIds.push(id);
}

function cancelSearch() {
  pendingFindMatch = false;
  clearPendingSearch();
  exitSearchingState();
  wsSend({ type: 'cancel_match' });
}

function resetConnectBtn() {
  const btn = document.getElementById('connectBtn');
  if (!btn) return;
  btn.classList.remove('searching');
  btn.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <circle cx="5" cy="12" r="2"/><circle cx="19" cy="12" r="2"/>
      <path d="M7 12h10M5 10V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4"/>
      <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>
    </svg>
    Connect`;
}

function requestNotificationPermission() {
  if (!('Notification' in window) || Notification.permission !== 'default') return;
  Notification.requestPermission().catch(() => {});
}

function pushNotification(title, body, fromUid) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (
    document.visibilityState === 'visible' &&
    currentPeer &&
    fromUid &&
    fromUid === currentPeer.uid
  ) {
    return;
  }
  try {
    const n = new Notification(title || 'Wolfy', {
      body: (body || '').slice(0, 120),
      icon: '/assets/icon.png',
      tag: 'wolfy-msg',
    });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (_) {}
}

function getComposer() {
  return document.getElementById('chatComposer');
}

function focusComposer() {
  const input = document.getElementById('msgInput');
  if (!input || input.disabled) return;
  try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); }
}

function setComposerEnabled(enabled) {
  const input = document.getElementById('msgInput');
  const send = document.getElementById('sendBtn');
  const attach = document.getElementById('attachBtn');
  const attachInput = document.getElementById('attachInput');
  [input, send, attach, attachInput].forEach(el => {
    if (el) el.disabled = !enabled;
  });
  getComposer()?.classList.toggle('composer-disabled', !enabled);
}

function syncComposerVisibility() {
  const composer = getComposer();
  if (!composer) return;

  if (isContactPage()) {
    composer.classList.remove('hidden');
    setComposerEnabled(!!currentPeer && (!searching || isRandomMatch));
    return;
  }

  composer.classList.toggle('hidden', !isRandomMatch);
  setComposerEnabled(isRandomMatch && !!currentPeer);
}

function initComposerHandlers() {
  document.getElementById('attachBtn')?.addEventListener('click', () => {
    if (!currentPeer) {
      showToast('Open a chat or connect first');
      return;
    }
    document.getElementById('attachInput')?.click();
  });

  document.getElementById('attachInput')?.addEventListener('change', e => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    files.forEach(file => uploadAttachment(file));
  });
}

function setUploadProgress(text, visible) {
  const el = document.getElementById('uploadProgress');
  if (!el) return;
  el.textContent = text || '';
  el.classList.toggle('hidden', !visible);
}

function formatFileSize(bytes) {
  if (!bytes || bytes < 1024) return `${bytes || 0} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function buildMessageContent(msg) {
  const msgType = msg.msg_type || 'text';
  const att = msg.attachment;
  const text = msg.text || '';
  let bubbleClass = 'msg-bubble';
  if (msgType === 'image') bubbleClass += ' msg-bubble-media';
  else if (msgType === 'file') bubbleClass += ' msg-bubble-file';

  const inner = buildReplyQuoteHtml(msg.reply_to);
  let body = '';

  if (msgType === 'image' && att?.file_id) {
    const url = `/api/files/${encodeURIComponent(att.file_id)}`;
    body += `<a href="${url}" target="_blank" rel="noopener"><img class="msg-image" src="${url}" alt="${escAttr(att.filename || 'Photo')}"/></a>`;
    if (text) body += `<div class="msg-caption">${esc(text)}</div>`;
  } else if (msgType === 'file' && att?.file_id) {
    const url = `/api/files/${encodeURIComponent(att.file_id)}`;
    const size = att.size ? formatFileSize(att.size) : '';
    body += `<a class="msg-file-card" href="${url}" target="_blank" rel="noopener">`;
    body += '<span class="msg-file-icon">📎</span><span class="msg-file-meta">';
    body += `<span class="msg-file-name">${esc(att.filename || 'File')}</span>`;
    if (size) body += `<span class="msg-file-size">${esc(size)}</span>`;
    body += '</span></a>';
    if (text) body += `<div class="msg-caption">${esc(text)}</div>`;
  } else {
    body += `<span class="msg-text">${esc(text)}</span>`;
  }

  return `<div class="${bubbleClass}">${inner}${body}</div>`;
}

async function uploadAttachment(file) {
  if (!currentPeer) {
    showToast('No active chat');
    return;
  }
  if (isRandomMatch && !currentSessionId) {
    showToast('Session expired');
    return;
  }

  const uploadGen = chatSessionGeneration;
  const replySnap = pendingReply ? { ...pendingReply } : null;
  const form = new FormData();
  form.append('to_uid', currentPeer.uid);
  form.append('file', file);
  if (isRandomMatch && currentSessionId) {
    form.append('session_id', currentSessionId);
  }
  if (replySnap?.message_id) {
    if (!isPersistedMessageId(replySnap.message_id)) {
      showToast('Wait for the original message to finish sending');
      return;
    }
    form.append('reply_to_id', replySnap.message_id);
  }

  setUploadProgress(`Uploading ${file.name}…`, true);
  setComposerEnabled(false);

  try {
    const res = await fetch('/api/chat/upload', {
      method: 'POST',
      body: form,
      credentials: 'same-origin',
    });
    const json = await res.json();
    if (!res.ok || !json.ok) {
      throw new Error(json.error || 'Upload failed');
    }
    if (uploadGen !== chatSessionGeneration) return;
    if (isRandomMatch && isStaleRandomMessage({ session_id: currentSessionId })) return;

    const uploadMsg = {
      msg_type: json.msg_type,
      attachment: json.attachment,
      text: '',
      timestamp: json.timestamp || new Date().toISOString(),
      message_id: json.message_id,
    };
    if (json.reply_to) uploadMsg.reply_to = json.reply_to;
    else if (replySnap) uploadMsg.reply_to = replySnap;
    const me = window.WOLFY_USER || {};
    lastOutgoingRow = appendMessage('me', uploadMsg, me.display_name || 'You', me.photo_url || '');
    if (json.message_id && lastOutgoingRow) {
      registerMessageRow(lastOutgoingRow, json.message_id);
      lastOutgoingRow = null;
    }
    cancelReply();
    scrollBottom();

    if (!isRandomMatch) {
      const preview = json.msg_type === 'image'
        ? '📷 Photo'
        : `📎 ${json.attachment?.filename || 'File'}`;
      updateContactPreview(currentPeer.uid, preview, true);
    }
  } catch (err) {
    showToast(err.message || 'Upload failed');
  } finally {
    setUploadProgress('', false);
    syncComposerVisibility();
    focusComposer();
  }
}

function normalizeReplyForViewer(replyTo) {
  if (!replyTo) return replyTo;
  const rt = { ...replyTo };
  const me = window.WOLFY_USER?.uid;
  if (rt.from_uid && me) {
    if (rt.from_uid === me) rt.sender_label = 'You';
    else {
      rt.sender_label = currentPeer?.display_name || window.WOLFY_PEER?.display_name || rt.sender_label || 'User';
    }
  }
  return rt;
}

function appendMessage(role, msg, name, photo) {
  const area = getMessagesArea();
  if (!area) return null;
  if (msg.reply_to) {
    msg = { ...msg, reply_to: normalizeReplyForViewer(msg.reply_to) };
  }
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  const initials = (name || '?')[0].toUpperCase();
  row.innerHTML = `
    <div class="avatar xs">
      ${photo ? `<img src="${escAttr(photo)}" alt=""/>` : initials}
    </div>
    <div class="msg-body">
      ${buildMessageContent(msg)}
      <div class="msg-time">${fmtTime(msg.timestamp || new Date().toISOString())}</div>
    </div>`;
  area.appendChild(row);
  bindMessageRow(row, role, msg);
  return row;
}

function appendSys(text) {
  const area = getMessagesArea();
  if (!area) return;
  const el = document.createElement('div');
  el.className = 'sys-msg';
  el.textContent = text;
  area.appendChild(el);
  scrollBottom();
}

let typingEl = null;
function showTyping() {
  if (typingEl) return;
  const area = getMessagesArea();
  if (!area) return;
  typingEl = document.createElement('div');
  typingEl.className = 'msg-row them';
  typingEl.innerHTML = `
    <div class="avatar xs">${esc((currentPeer?.display_name || '?')[0])}</div>
    <div class="msg-body">
      <div class="typing-dots"><span></span><span></span><span></span></div>
    </div>`;
  area.appendChild(typingEl);
  scrollBottom();
  setTimeout(() => { typingEl?.remove(); typingEl = null; }, 2500);
}

function scrollBottom() {
  const a = getMessagesArea();
  if (a) a.scrollTop = a.scrollHeight;
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escAttr(s) {
  return esc(s).replace(/'/g, '&#39;');
}

function fmtTime(ts) {
  const d = new Date(ts);
  if (isNaN(d)) return '';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function showToast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

(function initAvatarUpload() {
  const fileInput = document.getElementById('avatarFileInput');
  const removeBtn = document.getElementById('removeAvatarBtn');
  const imgEl = document.getElementById('editAvatarImg');
  const initialEl = document.getElementById('editAvatarInitial');
  const statusEl = document.getElementById('avatarUploadStatus');
  const nameInput = document.getElementById('editDisplayNameInput');
  if (!fileInput) return;

  if (nameInput && initialEl) {
    nameInput.addEventListener('input', () => {
      initialEl.textContent = (nameInput.value.trim()[0] || '?').toUpperCase();
    });
  }

  function setStatus(msg, type) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = 'avatar-upload-status ' + type;
    statusEl.classList.remove('hidden');
    if (type === 'success') setTimeout(() => statusEl.classList.add('hidden'), 2500);
  }

  function showPhoto(url) {
    if (imgEl) { imgEl.src = url; imgEl.style.display = ''; }
    if (initialEl) initialEl.style.display = 'none';
    if (removeBtn) removeBtn.style.display = '';
    document.querySelectorAll('.profile-bar .avatar img').forEach(i => { i.src = url; i.style.display = ''; });
  }

  function showInitial() {
    if (imgEl) { imgEl.src = ''; imgEl.style.display = 'none'; }
    if (initialEl) initialEl.style.display = '';
    if (removeBtn) removeBtn.style.display = 'none';
    document.querySelectorAll('.profile-bar .avatar img').forEach(i => { i.style.display = 'none'; });
  }

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (file.size > 3_000_000) { setStatus('File too large. Max 3MB.', 'error'); return; }
    setStatus('Uploading…', 'loading');
    const dataUrl = await resizeImage(file, 256);
    try {
      const res = await fetch('/profile/photo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_url: dataUrl }),
      });
      const json = await res.json();
      if (json.ok) {
        showPhoto(json.photo_url);
        setStatus('Photo updated!', 'success');
        if (window.WOLFY_USER) window.WOLFY_USER.photo_url = json.photo_url;
      } else {
        setStatus(json.error || 'Upload failed', 'error');
      }
    } catch {
      setStatus('Network error', 'error');
    }
    fileInput.value = '';
  });

  removeBtn?.addEventListener('click', async () => {
    setStatus('Removing…', 'loading');
    try {
      const res = await fetch('/profile/photo/remove', { method: 'POST' });
      const json = await res.json();
      if (json.ok) {
        showInitial();
        setStatus('Photo removed', 'success');
        if (window.WOLFY_USER) window.WOLFY_USER.photo_url = '';
      } else {
        setStatus('Failed to remove', 'error');
      }
    } catch {
      setStatus('Network error', 'error');
    }
  });

  function resizeImage(file, maxPx) {
    return new Promise(resolve => {
      const reader = new FileReader();
      reader.onload = e => {
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(1, maxPx / Math.max(img.width, img.height));
          const w = Math.round(img.width * scale);
          const h = Math.round(img.height * scale);
          const canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          canvas.getContext('2d').drawImage(img, 0, 0, w, h);
          resolve(canvas.toDataURL('image/jpeg', 0.88));
        };
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    });
  }
})();
