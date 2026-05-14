(function () {
  window.PesquisaAPI = {
    async postJSON(url, data) {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(data || {}),
      });

      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.erro || `HTTP ${response.status}`);
      }
      return payload;
    },

    async getJSON(url) {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.erro || `HTTP ${response.status}`);
      }
      return payload;
    },
  };
})();
