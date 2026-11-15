/* Shared visitor-facing mask. Session titles and ticket subjects both use this. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.nebulaMask = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function maskPhone(text) {
    return String(text || "").replace(/(?<![\d])(?:\+?86[\s-]?)?(1[3-9]\d[\s-]?\d{4}[\s-]?\d{4})(?!\d)/g, (match, mobile) => {
      const digits = String(mobile || "").replace(/\D/g, "");
      if (digits.length !== 11) return match;
      return digits.slice(0, 3) + "****" + digits.slice(-4);
    });
  }

  function sessionTitle(text) {
    const masked = maskPhone(text).trim();
    return (masked || "新对话").slice(0, 40);
  }

  function handoffSubject(text) {
    return maskPhone("跟进：" + String(text || "")).slice(0, 80);
  }

  function maskStoredSession(session) {
    const source = session && typeof session === "object" ? session : {};
    const messages = Array.isArray(source.messages)
      ? source.messages.map((message) => {
          if (!message || message.role !== "user") return message;
          return Object.assign({}, message, { text: maskPhone(message.text) });
        })
      : [];
    const firstUser = messages.find((message) => message && message.role === "user");
    const titleSource = firstUser ? firstUser.text : source.title || "";
    return Object.assign({}, source, {
      title: sessionTitle(titleSource),
      messages: messages,
    });
  }

  return {
    maskPhone: maskPhone,
    sessionTitle: sessionTitle,
    handoffSubject: handoffSubject,
    maskStoredSession: maskStoredSession,
  };
});
