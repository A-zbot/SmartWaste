/* SmartWaste AI - floating assistant widget (vanilla JS, no dependencies).
   Safe rendering rule: message text and structured data are inserted with
   textContent / createElement only - no innerHTML for anything user- or
   model-derived. Links are restricted to same-origin relative paths. */

(function () {
  'use strict';

  var API = '/chat/api';
  var LS_LANG = 'sw-chat-lang';
  var LS_CONV = 'sw-chat-conv';

  document.addEventListener('DOMContentLoaded', boot);

  function boot() {
    var root = document.getElementById('sw-chat');
    if (!root) return;

    var el = {
      root: root,
      fab: document.getElementById('sw-chat-fab'),
      panel: document.getElementById('sw-chat-panel'),
      close: document.getElementById('sw-chat-close'),
      messages: document.getElementById('sw-chat-messages'),
      suggestions: document.getElementById('sw-chat-suggestions'),
      input: document.getElementById('sw-chat-text'),
      send: document.getElementById('sw-chat-send'),
      lang: document.getElementById('sw-chat-lang'),
      historyBtn: document.getElementById('sw-chat-history-btn'),
      history: document.getElementById('sw-chat-history'),
      historyList: document.getElementById('sw-chat-history-list'),
      newBtn: document.getElementById('sw-chat-new'),
      status: document.getElementById('sw-chat-status'),
    };

    var state = {
      open: false,
      busy: false,
      booted: false,
      guest: false,
      disabled: false,
      aiConfigured: true,
      conversationId: null,
      language: 'en',
      suggestions: [],
      typing: null,
    };

    try {
      var storedLang = localStorage.getItem(LS_LANG);
      if (storedLang === 'en' || storedLang === 'hi' || storedLang === 'hinglish') {
        state.language = storedLang;
      }
    } catch (e) { /* storage unavailable */ }

    var role = root.dataset.role || 'guest';
    var suggestions = [];
    try {
      suggestions = JSON.parse(root.dataset.suggestions || '[]')[role] || [];
    } catch (e) { suggestions = []; }
    state.suggestions = suggestions;
    if (el.lang) el.lang.value = state.language;

    /* ---------------- API helper ---------------- */
    function api(path, options) {
      options = options || {};
      var headers = options.headers || {};
      headers['X-CSRFToken'] = root.dataset.csrf || '';
      if (options.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
      return fetch(path, {
        method: options.method || 'GET',
        headers: headers,
        body: options.body,
        credentials: 'same-origin',
      }).then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (!res.ok) {
            var err = new Error((data && data.error) || 'Request failed');
            err.status = res.status;
            err.code = data && data.code;
            throw err;
          }
          return data;
        });
      });
    }

    /* ---------------- DOM helpers ---------------- */
    function clearNode(node) {
      while (node.firstChild) node.removeChild(node.firstChild);
    }

    function safeHref(href) {
      if (typeof href !== 'string') return null;
      if (href.charAt(0) !== '/' || href.charAt(1) === '/' || href.charAt(1) === '\\') {
        return null;
      }
      if (href.indexOf('\\') !== -1) return null;
      return href;
    }

    function timeLabel(iso) {
      try {
        var d = iso && iso.indexOf('T') === -1 ? new Date(iso.replace(' ', 'T') + 'Z') : new Date(iso);
        if (isNaN(d.getTime())) d = new Date();
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      } catch (e) {
        return '';
      }
    }

    function scrollBottom() {
      el.messages.scrollTop = el.messages.scrollHeight;
    }

    /* ---------------- Structured cards ---------------- */
    function cardRow(container, label, value) {
      var row = document.createElement('div');
      row.className = 'sw-card-row';
      var b = document.createElement('b');
      b.textContent = label;
      var span = document.createElement('span');
      span.textContent = value == null || value === '' ? '-' : String(value);
      row.appendChild(b);
      row.appendChild(span);
      container.appendChild(row);
    }

    function cardItem(container, text, href) {
      var item = document.createElement('div');
      item.className = 'sw-card-item';
      if (href) {
        var a = document.createElement('a');
        a.href = href;
        a.textContent = text;
        a.addEventListener('click', function (ev) {
          ev.stopPropagation();
        });
        item.appendChild(a);
      } else {
        item.textContent = text;
      }
      container.appendChild(item);
    }

    function buildCard(meta) {
      if (!meta || !meta.type) return null;
      var type = meta.type;
      if (['complaint_summary', 'complaint_created', 'complaint_list',
           'stats', 'recommendations'].indexOf(type) === -1) {
        return null;
      }
      var card = document.createElement('div');
      card.className = 'sw-card';

      if (type === 'complaint_summary') {
        var title = document.createElement('div');
        title.className = 'sw-card-title';
        title.textContent = 'Complaint summary';
        card.appendChild(title);
        (meta.fields || []).forEach(function (f) {
          cardRow(card, f.label, f.value);
        });
        var hint = document.createElement('div');
        hint.className = 'sw-card-item';
        hint.textContent = 'Reply YES to confirm registration.';
        card.appendChild(hint);
        return card;
      }

      if (type === 'complaint_created') {
        var t2 = document.createElement('div');
        t2.className = 'sw-card-title';
        t2.textContent = 'Complaint registered';
        card.appendChild(t2);
        cardRow(card, 'Tracking ID', meta.tracking_id);
        cardRow(card, 'Status', 'Submitted');
        var href = safeHref(meta.href);
        if (href) cardItem(card, 'View complaint \u2192', href);
        return card;
      }

      if (type === 'complaint_list') {
        var items = meta.items || [];
        if (!items.length) return null;
        var t3 = document.createElement('div');
        t3.className = 'sw-card-title';
        t3.textContent = 'Complaints';
        card.appendChild(t3);
        items.slice(0, 10).forEach(function (item) {
          var label = (item.tracking_id || '') +
            (item.status ? ' \u00b7 ' + item.status : '') +
            (item.category ? ' \u00b7 ' + item.category : '') +
            (item.area ? ' \u00b7 ' + item.area : '');
          cardItem(card, label.trim(), safeHref(item.href));
        });
        return card;
      }

      if (type === 'stats') {
        var stats = meta.items || [];
        if (!stats.length) return null;
        var t4 = document.createElement('div');
        t4.className = 'sw-card-title';
        t4.textContent = 'From the live database';
        card.appendChild(t4);
        stats.slice(0, 14).forEach(function (s) {
          cardRow(card, s.label, s.value);
        });
        return card;
      }

      if (type === 'recommendations') {
        var recs = meta.items || [];
        if (!recs.length) return null;
        var t5 = document.createElement('div');
        t5.className = 'sw-card-title';
        t5.textContent = 'Recommendations';
        card.appendChild(t5);
        recs.slice(0, 8).forEach(function (r) {
          var text = (r.severity ? '[' + String(r.severity).toUpperCase() + '] ' : '') +
            (r.title || '');
          if (r.action) text += ' \u2192 ' + r.action;
          cardItem(card, text, null);
        });
        return card;
      }
      return null;
    }

    function sourceChips(meta) {
      if (!meta || meta.type !== 'knowledge' || !meta.sources ||
          !meta.sources.length) return null;
      var wrap = document.createElement('div');
      wrap.className = 'sw-chip-row';
      meta.sources.forEach(function (name) {
        var chip = document.createElement('span');
        chip.className = 'sw-chip';
        chip.textContent = String(name).replace(/_/g, ' ');
        wrap.appendChild(chip);
      });
      return wrap;
    }

    /* ---------------- Message rendering ---------------- */
    function appendMessage(sender, text, meta, createdAt) {
      clearWelcome();
      var bubble = document.createElement('div');
      bubble.className = 'sw-msg ' + (sender === 'user' ? 'sw-msg-user' : 'sw-msg-bot');
      if (meta && meta.type === 'error') bubble.classList.add('sw-msg-error');

      var body = document.createElement('span');
      body.textContent = text == null ? '' : String(text);
      bubble.appendChild(body);

      var card = sender === 'assistant' ? buildCard(meta) : null;
      if (card) bubble.appendChild(card);
      var chips = sender === 'assistant' ? sourceChips(meta) : null;
      if (chips) bubble.appendChild(chips);

      var stamp = document.createElement('span');
      stamp.className = 'sw-msg-meta';
      stamp.textContent = timeLabel(createdAt);
      bubble.appendChild(stamp);

      el.messages.appendChild(bubble);
      scrollBottom();
      return bubble;
    }

    function ensureWelcome() {
      if (el.messages.querySelector('.sw-chat-welcome')) return;
      if (el.messages.querySelector('.sw-msg')) return;
      var box = document.createElement('div');
      box.className = 'sw-chat-welcome';
      var avatar = document.createElement('div');
      avatar.className = 'sw-welcome-avatar';
      avatar.textContent = 'AI';
      var h = document.createElement('h3');
      h.textContent = "Hello! I'm SmartWaste AI.";
      var p = document.createElement('p');
      p.textContent = 'How can I help you make your community cleaner today?';
      box.appendChild(avatar);
      box.appendChild(h);
      box.appendChild(p);
      el.messages.appendChild(box);
    }

    function clearWelcome() {
      var w = el.messages.querySelector('.sw-chat-welcome');
      if (w) w.remove();
    }

    function setSuggestions(list) {
      state.suggestions = list || [];
      renderSuggestions();
    }

    function renderSuggestions() {
      clearNode(el.suggestions);
      if (!state.suggestions.length) return;
      if (el.messages.querySelector('.sw-msg')) return; // only on welcome screen
      state.suggestions.forEach(function (text) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sw-suggest';
        btn.textContent = text;
        btn.addEventListener('click', function () { send(text); });
        el.suggestions.appendChild(btn);
      });
    }

    function showTyping() {
      hideTyping();
      var t = document.createElement('div');
      t.className = 'sw-typing';
      t.setAttribute('aria-label', 'Assistant is typing');
      for (var i = 0; i < 3; i++) t.appendChild(document.createElement('span'));
      el.messages.appendChild(t);
      state.typing = t;
      scrollBottom();
    }

    function hideTyping() {
      if (state.typing && state.typing.parentNode) state.typing.remove();
      state.typing = null;
    }

    function showNotice(text, href, linkLabel) {
      var existing = el.messages.querySelector('.sw-chat-notice');
      if (existing) existing.remove();
      var box = document.createElement('div');
      box.className = 'sw-chat-notice';
      var span = document.createElement('span');
      span.textContent = text;
      box.appendChild(span);
      if (href) {
        var a = document.createElement('a');
        a.href = href;
        a.textContent = linkLabel || 'Sign in';
        box.appendChild(a);
      }
      el.messages.appendChild(box);
      scrollBottom();
    }

    /* ---------------- Conversation loading ---------------- */
    function resetView(keepWelcome) {
      clearNode(el.messages);
      clearNode(el.suggestions);
      state.conversationId = null;
      try { localStorage.removeItem(LS_CONV); } catch (e) { /* ignore */ }
      if (keepWelcome !== false) {
        ensureWelcome();
        renderSuggestions();
      }
    }

    function loadConversation(id) {
      api(API + '/conversations/' + id).then(function (data) {
        state.conversationId = data.conversation.id;
        try { localStorage.setItem(LS_CONV, String(id)); } catch (e) { /* ignore */ }
        if (data.conversation.language) {
          state.language = data.conversation.language;
          if (el.lang) el.lang.value = state.language;
        }
        clearNode(el.messages);
        clearNode(el.suggestions);
        if (!data.messages.length) {
          ensureWelcome();
          renderSuggestions();
        } else {
          data.messages.forEach(function (m) {
            appendMessage(m.sender, m.message, m.meta, m.created_at);
          });
        }
        el.status.textContent = data.conversation.title || 'Conversation';
      }).catch(function () { /* conversation vanished - start fresh */ });
    }

    function refreshHistory() {
      api(API + '/conversations').then(function (data) {
        clearNode(el.historyList);
        var list = data.conversations || [];
        if (!list.length) {
          var empty = document.createElement('li');
          var span = document.createElement('span');
          span.className = 'sw-chat-history-open';
          span.style.cursor = 'default';
          span.textContent = 'No conversations yet';
          empty.appendChild(span);
          el.historyList.appendChild(empty);
          return;
        }
        list.forEach(function (conv) {
          var li = document.createElement('li');
          if (conv.id === state.conversationId) li.className = 'is-active';
          var open = document.createElement('button');
          open.type = 'button';
          open.className = 'sw-chat-history-open';
          open.textContent = conv.title || 'Conversation';
          open.title = conv.title || '';
          open.addEventListener('click', function () {
            el.history.hidden = true;
            loadConversation(conv.id);
          });
          var del = document.createElement('button');
          del.type = 'button';
          del.className = 'sw-chat-history-del';
          del.textContent = '\u00d7';
          del.title = 'Delete conversation';
          del.setAttribute('aria-label', 'Delete conversation');
          del.addEventListener('click', function (ev) {
            ev.stopPropagation();
            api(API + '/conversations/' + conv.id, { method: 'DELETE' })
              .then(function () {
                if (conv.id === state.conversationId) resetView(true);
                refreshHistory();
              })
              .catch(function () { /* ignore */ });
          });
          li.appendChild(open);
          li.appendChild(del);
          el.historyList.appendChild(li);
        });
      }).catch(function () { /* history unavailable - non-fatal */ });
    }

    /* ---------------- Bootstrap ---------------- */
    function bootstrap() {
      if (state.booted) return;
      state.booted = true;
      api(API + '/status').then(function (data) {
        state.aiConfigured = !!data.ai_configured;
        if (data.suggestions && data.suggestions.length) {
          setSuggestions(data.suggestions);
        }
        if (state.aiConfigured) {
          el.status.textContent = 'Online \u00b7 grounded in SmartWaste knowledge';
        } else {
          el.status.textContent = 'Online \u00b7 AI model not configured';
        }
        return api(API + '/conversations');
      }).then(function (data) {
        var list = data.conversations || [];
        if (list.length) loadConversation(list[0].id);
        else { ensureWelcome(); renderSuggestions(); }
      }).catch(function (err) {
        if (err && err.status === 401) {
          state.guest = true;
          el.status.textContent = 'Sign in required';
          showNotice('Please sign in to chat with SmartWaste AI.',
                     root.dataset.loginHref, 'Sign in');
          ensureWelcome();
        } else if (err && err.status === 503) {
          state.disabled = true;
          el.status.textContent = 'Assistant disabled';
          showNotice('AI chat is currently disabled on this deployment.');
          ensureWelcome();
        } else {
          ensureWelcome();
          renderSuggestions();
        }
      });
    }

    /* ---------------- Sending ---------------- */
    function send(text) {
      text = (text || '').trim();
      if (!text || state.busy) return;
      if (state.disabled) return;
      if (state.guest) {
        showNotice('Please sign in to chat with SmartWaste AI.',
                   root.dataset.loginHref, 'Sign in');
        return;
      }
      if (text.length > 2000) text = text.slice(0, 2000);

      state.busy = true;
      el.send.disabled = true;
      appendMessage('user', text, null, new Date().toISOString());
      if (el.input) el.input.value = '';
      autoGrow();
      clearNode(el.suggestions);
      showTyping();

      api(API + '/message', {
        method: 'POST',
        body: JSON.stringify({
          message: text,
          conversation_id: state.conversationId,
          language: state.language,
        }),
      }).then(function (data) {
        state.conversationId = data.conversation_id;
        if (data.language) {
          state.language = data.language;
          if (el.lang) el.lang.value = data.language;
        }
        try { localStorage.setItem(LS_CONV, String(data.conversation_id)); } catch (e) { /* ignore */ }
        hideTyping();
        appendMessage('assistant', data.message.message, data.message.meta,
                      new Date().toISOString());
        if (data.message.meta && data.message.meta.type === 'suggestions') {
          var list = state.suggestions;
          if (data.message.meta.role === 'admin') {
            try {
              list = JSON.parse(root.dataset.suggestions).admin;
            } catch (e) { /* keep current */ }
          }
          setSuggestions(list);
        } else {
          renderSuggestions();
        }
        refreshHistoryQuiet();
      }).catch(function (err) {
        hideTyping();
        if (err && err.status === 401) {
          state.guest = true;
          showNotice('Please sign in to chat with SmartWaste AI.',
                     root.dataset.loginHref, 'Sign in');
        } else if (err && err.status === 429) {
          appendMessage('assistant', err.message, { type: 'error' },
                        new Date().toISOString());
        } else if (err && err.code === 'disabled') {
          state.disabled = true;
          showNotice('AI chat is currently disabled on this deployment.');
        } else {
          appendMessage('assistant',
                        (err && err.message) || 'Something went wrong. Please try again.',
                        { type: 'error' }, new Date().toISOString());
        }
      }).then(function () {
        state.busy = false;
        el.send.disabled = false;
        if (el.input) el.input.focus();
      });
    }

    var historyTimer = null;
    function refreshHistoryQuiet() {
      if (!state.open || el.history.hidden) return;
      clearTimeout(historyTimer);
      historyTimer = setTimeout(refreshHistory, 400);
    }

    /* ---------------- Open / close ---------------- */
    function openChat() {
      if (state.open) return;
      state.open = true;
      el.panel.hidden = false;
      // Force reflow so the transition runs from the hidden state.
      void el.panel.offsetWidth;
      el.panel.classList.add('is-open');
      el.fab.classList.add('is-open');
      el.fab.setAttribute('aria-expanded', 'true');
      el.fab.classList.remove('has-unread');
      bootstrap();
      setTimeout(function () { if (el.input) el.input.focus(); }, 60);
    }

    function closeChat() {
      if (!state.open) return;
      state.open = false;
      el.panel.classList.remove('is-open');
      el.fab.classList.remove('is-open');
      el.fab.setAttribute('aria-expanded', 'false');
      el.history.hidden = true;
      setTimeout(function () {
        if (!state.open) el.panel.hidden = true;
      }, 220);
    }

    function toggleChat() {
      if (state.open) closeChat(); else openChat();
    }

    /* ---------------- Composer ---------------- */
    function autoGrow() {
      if (!el.input) return;
      el.input.style.height = 'auto';
      el.input.style.height = Math.min(el.input.scrollHeight, 110) + 'px';
    }

    /* ---------------- Events ---------------- */
    el.fab.addEventListener('click', toggleChat);
    el.close.addEventListener('click', closeChat);
    el.send.addEventListener('click', function () { send(el.input.value); });

    el.input.addEventListener('input', autoGrow);
    el.input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        send(el.input.value);
      }
    });

    el.lang.addEventListener('change', function () {
      state.language = el.lang.value;
      try { localStorage.setItem(LS_LANG, state.language); } catch (e) { /* ignore */ }
    });

    el.historyBtn.addEventListener('click', function () {
      var show = el.history.hidden;
      el.history.hidden = !show;
      if (show) refreshHistory();
    });

    el.newBtn.addEventListener('click', function () {
      resetView(true);
      el.history.hidden = true;
      if (el.input) el.input.focus();
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && state.open) closeChat();
    });

    document.addEventListener('click', function (ev) {
      if (!state.open) return;
      if (ev.target.closest && ev.target.closest('#sw-chat')) return;
      if (ev.target.closest && ev.target.closest('.sw-chat-fab')) return;
      closeChat();
    });

    // First paint: welcome screen so the panel is never empty.
    ensureWelcome();
    renderSuggestions();
  }
})();
