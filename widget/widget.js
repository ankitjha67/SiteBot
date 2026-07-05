/*
 * SiteBot embeddable widget.
 * Usage on any website:
 *   <script src="https://cdn.yourdomain.com/widget.js"
 *           data-key="pk_xxx"
 *           data-api="https://api.yourdomain.com"></script>
 * No dependencies. Styles are isolated in a Shadow DOM.
 *
 * Server-driven features: theme, avatar, position, suggested questions,
 * feedback (thumbs), lead capture, human handoff, white-label branding.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var PUBLIC_KEY = script && script.getAttribute("data-key");
  var API_BASE = (script && script.getAttribute("data-api")) || "";
  if (!PUBLIC_KEY) {
    console.error("[SiteBot] Missing data-key on the script tag.");
    return;
  }

  // UI strings (answers already follow the visitor's language; these are the
  // chrome). Selected per site via the dashboard's widget language setting.
  var STRINGS = {
    en: { placeholder: "Type your question...", handoffPrompt: "Leave your email and a short message; a human will follow up.", handoffCta: "Request human help", leadCta: "Send", emailPh: "you@email.com", notePh: "Anything to add? (optional)", emailInvalid: "Please enter a valid email.", sendFail: "Could not send. Try again.", thanksLead: "Thanks. We will be in touch.", thanksHandoff: "Got it. A human will follow up soon.", errGeneric: "Sorry, something went wrong. Please try again.", errNetwork: "Sorry, I could not reach the server.", fbThanks: "Thanks for the feedback.", supportTag: "Support team", poweredBy: "Powered by SiteBot", bookCta: "Book a time" },
    es: { placeholder: "Escribe tu pregunta...", handoffPrompt: "Deja tu correo y un mensaje breve; una persona te responder\u00e1.", handoffCta: "Hablar con una persona", leadCta: "Enviar", emailPh: "tu@correo.com", notePh: "\u00bfAlgo que a\u00f1adir? (opcional)", emailInvalid: "Introduce un correo v\u00e1lido.", sendFail: "No se pudo enviar. Int\u00e9ntalo de nuevo.", thanksLead: "Gracias. Te contactaremos pronto.", thanksHandoff: "Recibido. Una persona te responder\u00e1 pronto.", errGeneric: "Lo sentimos, algo sali\u00f3 mal. Int\u00e9ntalo de nuevo.", errNetwork: "No se pudo conectar con el servidor.", fbThanks: "Gracias por tu opini\u00f3n.", supportTag: "Equipo de soporte", poweredBy: "Con tecnolog\u00eda de SiteBot" },
    fr: { placeholder: "Posez votre question...", handoffPrompt: "Laissez votre e-mail et un court message ; un humain vous r\u00e9pondra.", handoffCta: "Parler \u00e0 un humain", leadCta: "Envoyer", emailPh: "vous@email.com", notePh: "Autre chose \u00e0 ajouter ? (optionnel)", emailInvalid: "Veuillez saisir un e-mail valide.", sendFail: "\u00c9chec de l'envoi. R\u00e9essayez.", thanksLead: "Merci. Nous vous recontacterons.", thanksHandoff: "Bien re\u00e7u. Un humain vous r\u00e9pondra bient\u00f4t.", errGeneric: "D\u00e9sol\u00e9, une erreur s'est produite. R\u00e9essayez.", errNetwork: "Impossible de joindre le serveur.", fbThanks: "Merci pour votre retour.", supportTag: "\u00c9quipe support", poweredBy: "Propuls\u00e9 par SiteBot" },
    de: { placeholder: "Ihre Frage eingeben...", handoffPrompt: "Hinterlassen Sie Ihre E-Mail und eine kurze Nachricht; ein Mensch meldet sich.", handoffCta: "Mit einem Menschen sprechen", leadCta: "Senden", emailPh: "sie@email.de", notePh: "Noch etwas? (optional)", emailInvalid: "Bitte g\u00fcltige E-Mail eingeben.", sendFail: "Senden fehlgeschlagen. Bitte erneut versuchen.", thanksLead: "Danke. Wir melden uns.", thanksHandoff: "Angekommen. Ein Mensch meldet sich in K\u00fcrze.", errGeneric: "Entschuldigung, etwas ist schiefgelaufen.", errNetwork: "Server nicht erreichbar.", fbThanks: "Danke f\u00fcr Ihr Feedback.", supportTag: "Support-Team", poweredBy: "Bereitgestellt von SiteBot" },
    hi: { placeholder: "\u0905\u092a\u0928\u093e \u0938\u0935\u093e\u0932 \u0932\u093f\u0916\u0947\u0902...", handoffPrompt: "\u0905\u092a\u0928\u093e \u0908\u092e\u0947\u0932 \u0914\u0930 \u091b\u094b\u091f\u093e \u0938\u0902\u0926\u0947\u0936 \u091b\u094b\u0921\u093c\u0947\u0902; \u0939\u092e\u093e\u0930\u0940 \u091f\u0940\u092e \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0947\u0917\u0940\u0964", handoffCta: "\u0907\u0902\u0938\u093e\u0928 \u0938\u0947 \u092c\u093e\u0924 \u0915\u0930\u0947\u0902", leadCta: "\u092d\u0947\u091c\u0947\u0902", emailPh: "aap@email.com", notePh: "\u0915\u0941\u091b \u0914\u0930 \u091c\u094b\u0921\u093c\u0928\u093e \u0939\u0948? (\u0935\u0948\u0915\u0932\u094d\u092a\u093f\u0915)", emailInvalid: "\u0915\u0943\u092a\u092f\u093e \u092e\u093e\u0928\u094d\u092f \u0908\u092e\u0947\u0932 \u0926\u0930\u094d\u091c \u0915\u0930\u0947\u0902\u0964", sendFail: "\u092d\u0947\u091c\u093e \u0928\u0939\u0940\u0902 \u091c\u093e \u0938\u0915\u093e\u0964 \u092b\u093f\u0930 \u0938\u0947 \u0915\u094b\u0936\u093f\u0936 \u0915\u0930\u0947\u0902\u0964", thanksLead: "\u0927\u0928\u094d\u092f\u0935\u093e\u0926\u0964 \u0939\u092e \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0947\u0902\u0917\u0947\u0964", thanksHandoff: "\u092e\u093f\u0932 \u0917\u092f\u093e\u0964 \u0939\u092e\u093e\u0930\u0940 \u091f\u0940\u092e \u091c\u0932\u094d\u0926 \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0947\u0917\u0940\u0964", errGeneric: "\u0915\u094d\u0937\u092e\u093e \u0915\u0930\u0947\u0902, \u0915\u0941\u091b \u0917\u0921\u093c\u092c\u0921\u093c \u0939\u094b \u0917\u0908\u0964 \u092b\u093f\u0930 \u0938\u0947 \u0915\u094b\u0936\u093f\u0936 \u0915\u0930\u0947\u0902\u0964", errNetwork: "\u0938\u0930\u094d\u0935\u0930 \u0938\u0947 \u0938\u0902\u092a\u0930\u094d\u0915 \u0928\u0939\u0940\u0902 \u0939\u094b \u0938\u0915\u093e\u0964", fbThanks: "\u0906\u092a\u0915\u0940 \u092a\u094d\u0930\u0924\u093f\u0915\u094d\u0930\u093f\u092f\u093e \u0915\u0947 \u0932\u093f\u090f \u0927\u0928\u094d\u092f\u0935\u093e\u0926\u0964", supportTag: "\u0938\u092a\u094b\u0930\u094d\u091f \u091f\u0940\u092e", poweredBy: "SiteBot \u0926\u094d\u0935\u093e\u0930\u093e \u0938\u0902\u091a\u093e\u0932\u093f\u0924" },
    pt: { placeholder: "Digite sua pergunta...", handoffPrompt: "Deixe seu e-mail e uma mensagem curta; um humano responder\u00e1.", handoffCta: "Falar com um humano", leadCta: "Enviar", emailPh: "voce@email.com", notePh: "Algo a acrescentar? (opcional)", emailInvalid: "Insira um e-mail v\u00e1lido.", sendFail: "Falha no envio. Tente novamente.", thanksLead: "Obrigado. Entraremos em contato.", thanksHandoff: "Recebido. Um humano responder\u00e1 em breve.", errGeneric: "Desculpe, algo deu errado. Tente novamente.", errNetwork: "N\u00e3o foi poss\u00edvel contatar o servidor.", fbThanks: "Obrigado pelo feedback.", supportTag: "Equipe de suporte", poweredBy: "Desenvolvido com SiteBot" }
  };
  function t(key) {
    var pack = STRINGS[config.language] || STRINGS.en;
    return pack[key] || STRINGS.en[key] || key;
  }

  var visitorId = getVisitorId();
  var conversationId = loadConversationId(); // persists across page loads
  var lastFollowups = [];
  var assistantIndex = -1; // index of assistant messages, for feedback
  var lastAgentId = 0;     // watermark for live agent-reply polling
  var pollTimer = null;
  var config = {
    display_name: "Assistant",
    theme_color: "#4f46e5",
    welcome_message: "Hi. Ask me anything about this site.",
    position: "right",
    avatar_url: "",
    suggested_questions: [],
    lead_capture_enabled: false,
    lead_prompt: "Leave your email and we will get back to you.",
    booking_url: "",
    qualifying_questions: [],
    handoff_enabled: false,
    hide_branding: false,
    language: "en",
    avatar_style: "",
    proactive_message: "",
    proactive_delay_s: 0
  };
  var lastSources = [];
  var opened = false;
  var leadShown = false;

  // ---------- DOM scaffold ----------
  var host = document.createElement("div");
  host.style.position = "fixed";
  host.style.zIndex = "2147483647";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML = [
    "<style>" + styles() + "</style>",
    '<button id="launcher" aria-label="Open chat">' + chatIcon() + "</button>",
    '<div id="panel" role="dialog" aria-label="Chat">',
    '  <div id="header"><span id="avatar"></span><span id="title"></span>',
    '    <span id="headspace"></span>',
    '    <button id="speaker" title="Read answers aloud" aria-label="Read answers aloud">' + speakerIcon() + "</button>",
    '    <button id="handoff" title="Talk to a human" aria-label="Talk to a human">' + personIcon() + "</button>",
    '    <button id="close" aria-label="Close">\u00d7</button></div>',
    '  <div id="messages"></div>',
    '  <div id="suggest"></div>',
    '  <div id="composer">',
    '    <button id="mic" title="Speak your question" aria-label="Speak your question">' + micIcon() + "</button>",
    '    <textarea id="input" rows="1" placeholder="Type your question..."></textarea>',
    '    <button id="send" aria-label="Send">' + sendIcon() + "</button>",
    "  </div>",
    '  <div id="brand">Powered by SiteBot</div>',
    "</div>",
  ].join("");

  var launcher = root.getElementById("launcher");
  var panel = root.getElementById("panel");
  var closeBtn = root.getElementById("close");
  var handoffBtn = root.getElementById("handoff");
  var micBtn = root.getElementById("mic");
  var speakerBtn = root.getElementById("speaker");
  var messagesEl = root.getElementById("messages");
  var suggestEl = root.getElementById("suggest");
  var inputEl = root.getElementById("input");
  var sendBtn = root.getElementById("send");
  var titleEl = root.getElementById("title");
  var avatarEl = root.getElementById("avatar");
  var brandEl = root.getElementById("brand");

  launcher.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);
  handoffBtn.addEventListener("click", showHandoffForm);
  sendBtn.addEventListener("click", submit);
  micBtn.addEventListener("click", toggleMic);
  speakerBtn.addEventListener("click", toggleSpeaker);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });
  inputEl.addEventListener("input", autoGrow);

  // ---------- behaviour ----------
  // Config loads immediately (not on first open) so the proactive teaser
  // and theming are ready before any interaction.
  var configReady = loadConfig();
  configReady.then(function () { maybeShowTeaser(); });

  function openPanel() {
    removeTeaser();
    panel.classList.add("open");
    launcher.classList.add("hidden");
    inputEl.focus();
    startPolling();
    scrollDown(true); // long restored chats open at the newest message
    if (!opened) {
      opened = true;
      configReady.then(function () {
        applyConfig();
        // Config resolves asynchronously; the visitor may already have sent a
        // message. The welcome always belongs at the top of the thread.
        var welcome = document.createElement("div");
        welcome.className = "bubble assistant";
        var wt = document.createElement("div");
        wt.className = "text";
        wt.textContent = config.welcome_message;
        welcome.appendChild(wt);
        messagesEl.insertBefore(welcome, messagesEl.firstChild);
        renderSuggestions();
      });
    }
  }

  function closePanel() {
    panel.classList.remove("open");
    launcher.classList.remove("hidden");
    stopPolling();
  }

  // ---------- live agent replies ----------
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(pollAgentReplies, 6000);
    pollAgentReplies();
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }
  function pollAgentReplies() {
    if (conversationId == null) return;
    fetch(API_BASE + "/v1/conversations/" + conversationId + "/updates?key=" +
          encodeURIComponent(PUBLIC_KEY) + "&after=" + lastAgentId)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.messages) return;
        d.messages.forEach(function (m) {
          if (m.id > lastAgentId) lastAgentId = m.id;
          var b = addBubble("assistant", "");
          b.classList.add("agent");
          var tag = document.createElement("div");
          tag.className = "agenttag";
          tag.textContent = t("supportTag");
          b.insertBefore(tag, b.firstChild);
          b.querySelector(".text").textContent = m.content;
          scrollDown();
        });
      })
      .catch(function () {});
  }

  // ---------- voice: speech-to-text + text-to-speech ----------
  var LOCALES = { en: "en-US", es: "es-ES", fr: "fr-FR", de: "de-DE", hi: "hi-IN", pt: "pt-BR" };
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var recognizer = null, listening = false, ttsOn = false;

  function locale() { return LOCALES[config.language] || navigator.language || "en-US"; }

  // A transient hint in the input placeholder: visible exactly where the
  // visitor is looking, and it disappears on the next interaction.
  function micHint(text) {
    var original = t("placeholder");
    inputEl.placeholder = text;
    setTimeout(function () { inputEl.placeholder = original; }, 6000);
  }

  var MIC_ERRORS = {
    "not-allowed": "Microphone blocked - allow it in the address bar and retry.",
    "service-not-allowed": "Microphone blocked - allow it in the address bar and retry.",
    "audio-capture": "No microphone found on this device.",
    "network": "Voice input needs the browser's online speech service.",
    "language-not-supported": "This language is not supported for voice input.",
    "aborted": "" // user cancelled: not an error worth showing
  };

  function toggleMic() {
    if (!SR) { micHint("Voice input is not supported in this browser."); return; }
    if (window.isSecureContext === false) {
      micHint("Voice input needs HTTPS."); return;
    }
    if (listening) { try { recognizer.stop(); } catch (e) {} return; }
    recognizer = new SR();
    recognizer.lang = locale();
    recognizer.interimResults = true;
    recognizer.continuous = false;
    recognizer.onstart = function () {
      listening = true;
      micBtn.classList.add("live");
      micHint("Listening...");
    };
    recognizer.onend = function () { listening = false; micBtn.classList.remove("live"); };
    recognizer.onerror = function (e) {
      listening = false;
      micBtn.classList.remove("live");
      var msg = e && e.error in MIC_ERRORS
        ? MIC_ERRORS[e.error]
        : e && e.error === "no-speech"
          ? "Did not catch that - tap the mic and try again."
          : "Voice input failed - you can type instead.";
      if (msg) micHint(msg);
    };
    recognizer.onresult = function (e) {
      var text = "";
      for (var i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      inputEl.value = text;
      autoGrow();
      if (e.results[e.results.length - 1].isFinal) { try { recognizer.stop(); } catch (x) {} submit(); }
    };
    try {
      recognizer.start();
    } catch (e) {
      listening = false;
      micBtn.classList.remove("live");
      micHint("Could not start the microphone - check browser permissions.");
    }
  }

  function toggleSpeaker() {
    ttsOn = !ttsOn;
    speakerBtn.classList.toggle("live", ttsOn);
    if (!ttsOn && window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function speak(text) {
    if (!ttsOn || !window.speechSynthesis || !text) return;
    var clean = text.replace(/\[\d+\]/g, "").replace(/[*`_#>]/g, "");
    var u = new SpeechSynthesisUtterance(clean);
    u.lang = locale();
    u.onstart = function () { avatarSpeaking(true); };
    u.onend = function () { avatarSpeaking(false); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  // ---------- proactive teaser ----------
  function maybeShowTeaser() {
    if (!config.proactive_message || !config.proactive_delay_s || opened) return;
    try { if (localStorage.getItem("sitebot_teased_" + PUBLIC_KEY)) return; } catch (e) {}
    setTimeout(function () {
      if (opened || root.getElementById("teaser")) return;
      var t = document.createElement("div");
      t.id = "teaser";
      t.innerHTML = '<button id="teaserx" aria-label="Dismiss">\u00d7</button><div class="ttext"></div>';
      t.querySelector(".ttext").textContent = config.proactive_message;
      root.appendChild(t);
      t.addEventListener("click", function (e) {
        if (e.target.id === "teaserx") { rememberTeased(); removeTeaser(); }
        else { rememberTeased(); openPanel(); }
      });
    }, config.proactive_delay_s * 1000);
  }
  function removeTeaser() {
    var t = root.getElementById("teaser");
    if (t) t.remove();
  }
  function rememberTeased() {
    try { localStorage.setItem("sitebot_teased_" + PUBLIC_KEY, "1"); } catch (e) {}
  }

  function loadConfig() {
    return fetch(API_BASE + "/v1/widget/config?key=" + encodeURIComponent(PUBLIC_KEY))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (c) { if (c) config = c; })
      .catch(function () {});
  }

  function applyConfig() {
    host.style.setProperty("--accent", config.theme_color || "#4f46e5");
    root.host.style.setProperty("--accent", config.theme_color || "#4f46e5");
    titleEl.textContent = config.display_name;
    if (config.position === "left") panel.classList.add("left"), launcher.classList.add("left");
    if (config.avatar_url) {
      var img = document.createElement("img");
      // Platform-hosted avatars (e.g. /static/agents/...) are relative to the
      // API origin, not the page the widget is embedded on.
      img.src = config.avatar_url.charAt(0) === "/"
        ? API_BASE + config.avatar_url
        : config.avatar_url;
      img.alt = "";
      avatarEl.appendChild(img);
    } else if (config.avatar_style) {
      // No custom image but an animated persona was chosen: show a default face.
      avatarEl.innerHTML = botFace();
    }
    if (config.avatar_style) avatarEl.classList.add("av-" + config.avatar_style);
    handoffBtn.style.display = config.handoff_enabled ? "flex" : "none";
    brandEl.style.display = config.hide_branding ? "none" : "block";
    inputEl.placeholder = t("placeholder");
    brandEl.textContent = t("poweredBy");
  }

  function renderSuggestions() {
    suggestEl.innerHTML = "";
    (config.suggested_questions || []).slice(0, 4).forEach(function (q) {
      var b = document.createElement("button");
      b.className = "chip";
      b.textContent = q;
      b.onclick = function () {
        suggestEl.innerHTML = "";
        inputEl.value = q;
        submit();
      };
      suggestEl.appendChild(b);
    });
  }

  function renderFollowupChips(questions) {
    suggestEl.innerHTML = "";
    questions.slice(0, 3).forEach(function (q) {
      var b = document.createElement("button");
      b.className = "chip";
      b.textContent = q;
      b.onclick = function () {
        suggestEl.innerHTML = "";
        inputEl.value = q;
        submit();
      };
      suggestEl.appendChild(b);
    });
  }

  function submit() {
    var text = inputEl.value.trim();
    if (!text) return;
    suggestEl.innerHTML = "";
    inputEl.value = "";
    autoGrow();
    addBubble("user", text);
    scrollDown(true); // sending always re-pins the view to the newest message
    var target = addBubble("assistant", "");
    target.classList.add("streaming");
    avatarSpeaking(true);
    streamAnswer(text, target);
  }

  function avatarSpeaking(on) {
    if (config.avatar_style) avatarEl.classList.toggle("speaking", on);
  }

  function streamAnswer(question, target) {
    lastSources = [];
    lastFollowups = [];
    setBusy(true);
    var couldNotAnswer = false;
    fetch(API_BASE + "/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key: PUBLIC_KEY,
        message: question,
        visitor_id: visitorId,
        conversation_id: conversationId,
      }),
    })
      .then(function (resp) {
        if (!resp.ok || !resp.body) throw new Error("Bad response");
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        var acc = "";

        function pump() {
          return reader.read().then(function (res) {
            if (res.done) { finish(target, acc, couldNotAnswer); return; }
            buffer += decoder.decode(res.value, { stream: true });
            var idx;
            while ((idx = buffer.indexOf("\n\n")) >= 0) {
              var frame = buffer.slice(0, idx);
              buffer = buffer.slice(idx + 2);
              var evt = parseFrame(frame);
              if (!evt) continue;
              if (evt.event === "token") {
                acc += evt.data;
                target.querySelector(".text").innerHTML = format(acc, lastSources);
                scrollDown();
              } else if (evt.event === "sources") {
                lastSources = evt.data || [];
              } else if (evt.event === "followups") {
                lastFollowups = evt.data || [];
              } else if (evt.event === "action") {
                var note = document.createElement("div");
                note.className = "actionnote";
                note.textContent = "\u2699 " + ((evt.data && evt.data.name) || "action");
                target.insertBefore(note, target.firstChild);
              } else if (evt.event === "done") {
                conversationId = evt.data && evt.data.conversation_id;
                saveConversationId(conversationId);
                startPolling();
                // A declined answer is the high-intent moment regardless of
                // whether retrieval returned sources - hybrid retrieval almost
                // always returns some chunk, so keying only on zero sources
                // would miss most lead-capture opportunities.
                couldNotAnswer = /do not have (that )?information|contact the company directly|no tengo esa informaci/i.test(acc);
              } else if (evt.event === "error") {
                acc = t("errGeneric");
                target.querySelector(".text").textContent = acc;
              }
            }
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        target.querySelector(".text").textContent = t("errNetwork");
        finish(target, "", false);
      });
  }

  function finish(target, acc, couldNotAnswer) {
    target.classList.remove("streaming");
    if (lastSources.length) renderSources(target, lastSources);
    assistantIndex += 1;
    if (acc) renderFeedback(target, assistantIndex);
    if (lastFollowups.length) renderFollowupChips(lastFollowups);
    avatarSpeaking(false);
    if (acc) speak(acc);
    setBusy(false);
    scrollDown();
    // High-intent moment: the bot could not help. Offer to capture the lead once.
    if (couldNotAnswer && config.lead_capture_enabled && !leadShown) {
      leadShown = true;
      showLeadForm();
    }
  }

  function parseFrame(frame) {
    var lines = frame.split("\n");
    var event = "message";
    var data = "";
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (line.indexOf("event:") === 0) event = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    }
    if (!data) return null;
    try { return { event: event, data: JSON.parse(data) }; }
    catch (e) { return { event: event, data: data }; }
  }

  // ---------- lead capture and handoff ----------
  function showLeadForm() {
    var wrap = addBubble("assistant", "");
    wrap.querySelector(".text").textContent = config.lead_prompt;
    wrap.appendChild(buildContactForm(t("leadCta"), function (email, note, formEl) {
      // Answers to the site's qualifying questions travel with the lead so
      // sales sees a scored, qualified contact in their CRM, not a bare email.
      var qual = {};
      formEl.querySelectorAll(".lqual").forEach(function (input) {
        if (input.value.trim()) qual[input.getAttribute("data-q")] = input.value.trim();
      });
      post("/v1/leads", { key: PUBLIC_KEY, email: email, note: note,
        qualification: qual,
        conversation_id: conversationId, visitor_id: visitorId })
        .then(function () {
          var done = "<div class='formdone'>" + t("thanksLead") + "</div>";
          if (config.booking_url) {
            done += "<div style='margin-top:6px'><a href='" + config.booking_url +
              "' target='_blank' rel='noopener' class='bookbtn'>" + t("bookCta") + "</a></div>";
          }
          formEl.innerHTML = done;
        })
        .catch(function () { formEl.querySelector(".formerr").textContent = t("sendFail"); });
    }, config.qualifying_questions || []));
    scrollDown();
  }

  function showHandoffForm() {
    var wrap = addBubble("assistant", "");
    wrap.querySelector(".text").textContent = t("handoffPrompt");
    wrap.appendChild(buildContactForm(t("handoffCta"), function (email, note, formEl) {
      post("/v1/handoff", { key: PUBLIC_KEY, email: email, message: note,
        conversation_id: conversationId, visitor_id: visitorId })
        .then(function () { formEl.innerHTML = "<div class='formdone'>" + t("thanksHandoff") + "</div>"; })
        .catch(function () { formEl.querySelector(".formerr").textContent = "Could not send. Try again."; });
    }));
    scrollDown();
  }

  function buildContactForm(cta, onSubmit, questions) {
    var form = document.createElement("div");
    form.className = "leadform";
    var qhtml = "";
    (questions || []).slice(0, 4).forEach(function (q) {
      var safe = String(q).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
      qhtml += '<input type="text" class="lqual" data-q="' + safe + '" placeholder="' + safe + '" />';
    });
    form.innerHTML =
      '<input type="email" class="lemail" placeholder="' + t("emailPh") + '" />' +
      qhtml +
      '<textarea class="lnote" rows="2" placeholder="' + t("notePh") + '"></textarea>' +
      '<button class="lsend">' + cta + "</button>" +
      '<div class="formerr"></div>';
    form.querySelector(".lsend").onclick = function () {
      var email = form.querySelector(".lemail").value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        form.querySelector(".formerr").textContent = t("emailInvalid");
        return;
      }
      onSubmit(email, form.querySelector(".lnote").value.trim(), form);
    };
    return form;
  }

  function post(path, body) {
    return fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) { if (!r.ok) throw new Error("bad"); return r.json(); });
  }

  // ---------- rendering ----------
  function addBubble(role, text) {
    var wrap = document.createElement("div");
    wrap.className = "bubble " + role;
    var t = document.createElement("div");
    t.className = "text";
    t.textContent = text;
    wrap.appendChild(t);
    messagesEl.appendChild(wrap);
    scrollDown();
    return wrap;
  }

  function renderSources(target, sources) {
    var box = document.createElement("div");
    box.className = "sources";
    var seen = {};
    sources.forEach(function (s) {
      if (!s.url || seen[s.url]) return; // internal sources have no public URL
      seen[s.url] = true;
      var a = document.createElement("a");
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = s.title.length > 42 ? s.title.slice(0, 42) + "..." : s.title;
      box.appendChild(a);
    });
    target.appendChild(box);
  }

  function renderFeedback(target, index) {
    var box = document.createElement("div");
    box.className = "feedback";
    [1, -1].forEach(function (value) {
      var b = document.createElement("button");
      b.textContent = value === 1 ? "\ud83d\udc4d" : "\ud83d\udc4e";
      b.setAttribute("aria-label", value === 1 ? "Helpful" : "Not helpful");
      b.onclick = function () {
        if (conversationId == null) return;
        post("/v1/feedback", { key: PUBLIC_KEY, conversation_id: conversationId,
          message_index: index, value: value }).catch(function () {});
        box.innerHTML = "<span class='fbdone'>" + t("fbThanks") + "</span>";
      };
      box.appendChild(b);
    });
    target.appendChild(box);
  }

  function format(text, sources) {
    var safe = escapeHtml(text);
    // Turn [n] into links to the matching source (plain [n] for internal sources).
    safe = safe.replace(/\[(\d+)\]/g, function (m, n) {
      var src = sources[parseInt(n, 10) - 1];
      if (!src || !src.url) return m;
      return '<sup><a href="' + escapeAttr(src.url) + '" target="_blank" rel="noopener">[' + n + "]</a></sup>";
    });
    // Markdown-lite: bold and inline code (applied after HTML escaping).
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    safe = safe.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    return safe.replace(/\n\n/g, "<br><br>").replace(/\n/g, "<br>");
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

  function setBusy(b) { sendBtn.disabled = b; inputEl.disabled = b; }
  // Stick-to-bottom: follow the conversation as it grows, but never yank the
  // visitor back down while they are scrolled up reading earlier messages.
  // Sending a message (or opening the panel) always re-pins to the bottom.
  var stickToBottom = true;
  messagesEl.addEventListener("scroll", function () {
    stickToBottom =
      messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 48;
  });
  function scrollDown(force) {
    if (force) stickToBottom = true;
    if (stickToBottom) messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  function autoGrow() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  }

  function loadConversationId() {
    try {
      var v = localStorage.getItem("sitebot_conv_" + PUBLIC_KEY);
      return v ? parseInt(v, 10) : null;
    } catch (e) { return null; }
  }
  function saveConversationId(id) {
    if (id == null) return;
    try { localStorage.setItem("sitebot_conv_" + PUBLIC_KEY, String(id)); } catch (e) {}
  }

  function getVisitorId() {
    try {
      var id = localStorage.getItem("sitebot_vid");
      if (!id) {
        id = "v_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
        localStorage.setItem("sitebot_vid", id);
      }
      return id;
    } catch (e) { return "v_anon"; }
  }

  // ---------- assets ----------
  function chatIcon() {
    return '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';
  }
  function sendIcon() {
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
  }
  function personIcon() {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
  }
  function micIcon() {
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/></svg>';
  }
  function speakerIcon() {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';
  }
  function botFace() {
    return '<svg width="26" height="26" viewBox="0 0 24 24" fill="var(--accent)"><rect x="4" y="7" width="16" height="12" rx="4" fill="#fff"/><circle cx="9" cy="13" r="1.7" fill="var(--accent)"/><circle cx="15" cy="13" r="1.7" fill="var(--accent)"/><rect x="11" y="2.5" width="2" height="3" rx="1" fill="#fff"/><circle cx="12" cy="2.5" r="1.6" fill="#fff"/></svg>';
  }

  function styles() {
    return [
      ":host{--accent:#4f46e5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;}",
      "*{box-sizing:border-box;}",
      "#launcher{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:none;background:var(--accent);cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);display:flex;align-items:center;justify-content:center;transition:transform .15s ease;}",
      "#launcher.left{right:auto;left:20px;}",
      "#launcher:hover{transform:scale(1.06);}",
      "#launcher.hidden{display:none;}",
      "#panel{position:fixed;right:20px;bottom:20px;width:380px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 40px);background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;}",
      "#panel.left{right:auto;left:20px;}",
      "#panel.open{display:flex;}",
      "#header{background:var(--accent);color:#fff;padding:12px 14px;display:flex;align-items:center;gap:8px;font-weight:600;}",
      "#headspace{flex:1;}",
      "#avatar{display:inline-flex;line-height:0;transition:transform .2s ease;}",
      "#avatar img{width:26px;height:26px;border-radius:50%;display:block;object-fit:cover;}",
      "#avatar.av-pulse.speaking{animation:avpulse 1s ease-in-out infinite;}",
      "#avatar.av-bounce.speaking{animation:avbounce .6s ease-in-out infinite;}",
      "@keyframes avpulse{0%,100%{transform:scale(1);}50%{transform:scale(1.18);}}",
      "@keyframes avbounce{0%,100%{transform:translateY(0);}50%{transform:translateY(-3px);}}",
      "#handoff{background:rgba(255,255,255,.18);border:none;border-radius:8px;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;}",
      "#close{background:transparent;border:none;color:#fff;font-size:22px;line-height:1;cursor:pointer;padding:0 4px;}",
      "#messages{flex:1;overflow-y:auto;overscroll-behavior:contain;padding:16px;background:#f7f7f9;display:flex;flex-direction:column;gap:10px;}",
      "#suggest{display:flex;flex-wrap:wrap;gap:6px;padding:0 12px;background:#f7f7f9;}",
      "#suggest:not(:empty){padding-bottom:10px;}",
      ".chip{border:1px solid var(--accent);color:var(--accent);background:#fff;border-radius:14px;padding:5px 11px;font-size:12px;cursor:pointer;}",
      ".chip:hover{background:#eef0ff;}",
      ".bubble{max-width:85%;padding:10px 13px;border-radius:14px;font-size:14px;line-height:1.5;word-wrap:break-word;}",
      ".bubble .text{white-space:normal;}",
      ".bubble.user{align-self:flex-end;background:var(--accent);color:#fff;border-bottom-right-radius:4px;}",
      ".bubble.assistant{align-self:flex-start;background:#fff;color:#1f2330;border:1px solid #eaeaef;border-bottom-left-radius:4px;}",
      ".bubble.streaming .text::after{content:'';display:inline-block;width:7px;height:14px;background:var(--accent);margin-left:2px;vertical-align:-2px;animation:blink 1s steps(2) infinite;}",
      "@keyframes blink{50%{opacity:0;}}",
      ".sources{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;}",
      ".sources a{font-size:11px;color:var(--accent);background:#eef0ff;padding:3px 8px;border-radius:10px;text-decoration:none;border:1px solid #e0e3ff;}",
      ".bubble a{color:var(--accent);}",
      ".feedback{margin-top:6px;display:flex;gap:6px;}",
      ".feedback button{border:1px solid #e0e3ff;background:#fff;border-radius:8px;padding:2px 8px;cursor:pointer;font-size:13px;}",
      ".feedback button:hover{background:#eef0ff;}",
      ".fbdone{font-size:11px;color:#8a90a3;}",
      ".leadform{margin-top:8px;display:flex;flex-direction:column;gap:6px;}",
      ".leadform input,.leadform textarea{border:1px solid #dcdce3;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;}",
      ".leadform input:focus,.leadform textarea:focus{border-color:var(--accent);}",
      ".bookbtn{display:inline-block;background:var(--accent);color:#fff;border-radius:8px;padding:7px 14px;font-size:13px;text-decoration:none;font-weight:600;}",
      ".leadform button{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:7px 10px;cursor:pointer;font-size:13px;}",
      ".formerr{color:#dc2626;font-size:11px;min-height:12px;}",
      ".formdone{font-size:13px;color:#16a34a;padding:4px 0;}",
      "#composer{display:flex;align-items:flex-end;gap:8px;padding:10px;border-top:1px solid #eee;background:#fff;}",
      "#mic{width:40px;height:40px;border-radius:10px;border:1px solid #dcdce3;background:#fff;color:#5a6270;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;}",
      "#mic:hover{border-color:var(--accent);color:var(--accent);}",
      "#mic.live{background:var(--accent);color:#fff;border-color:var(--accent);animation:sbpulse 1.2s ease-in-out infinite;}",
      "@keyframes sbpulse{50%{box-shadow:0 0 0 6px rgba(0,0,0,.06);}}",
      "#speaker{background:rgba(255,255,255,.18);border:none;border-radius:8px;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:.7;}",
      "#speaker.live{opacity:1;background:rgba(255,255,255,.35);}",
      "#input{flex:1;resize:none;border:1px solid #dcdce3;border-radius:10px;padding:9px 12px;font-size:14px;font-family:inherit;outline:none;max-height:120px;}",
      "#input:focus{border-color:var(--accent);}",
      "#send{width:40px;height:40px;border-radius:10px;border:none;background:var(--accent);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;}",
      "#send:disabled{opacity:.5;cursor:default;}",
      "#brand{text-align:center;font-size:10px;color:#aab;padding:6px;background:#fff;}",
      ".bubble code{background:rgba(127,127,127,.15);border-radius:4px;padding:1px 5px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;}",
      ".bubble.agent{border-left:3px solid var(--accent);}",
      ".agenttag{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin-bottom:3px;}",
      ".actionnote{font-size:10.5px;color:#8a90a3;font-style:italic;margin-bottom:4px;}",
      "#teaser{position:fixed;right:20px;bottom:88px;max-width:260px;background:#fff;color:#1f2330;border:1px solid #eaeaef;border-radius:14px;border-bottom-right-radius:4px;box-shadow:0 8px 28px rgba(0,0,0,.18);padding:12px 30px 12px 14px;font-size:13.5px;line-height:1.45;cursor:pointer;animation:sbslide .25s ease;}",
      "@keyframes sbslide{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}",
      "#teaserx{position:absolute;top:4px;right:6px;background:none;border:none;color:#aab;font-size:16px;cursor:pointer;line-height:1;padding:2px;}",
      "@media (prefers-color-scheme: dark){",
      "#panel{background:#15181c;}",
      "#messages{background:#101317;}",
      ".bubble.assistant{background:#1c2127;color:#e4e8ed;border-color:#2a3037;}",
      "#composer{background:#15181c;border-color:#262b31;}",
      "#input{background:#1c2127;color:#e4e8ed;border-color:#333a42;}",
      "#brand{background:#15181c;color:#556;}",
      ".chip{background:#1c2127;}",
      ".sources a{background:#1d2430;border-color:#2b3547;}",
      ".feedback button{background:#1c2127;border-color:#2b3547;}",
      ".leadform input,.leadform textarea{background:#1c2127;color:#e4e8ed;border-color:#333a42;}",
      "#teaser{background:#1c2127;color:#e4e8ed;border-color:#2a3037;}",
      "#suggest{background:#101317;}",
      "}",
    ].join("");
  }
})();
