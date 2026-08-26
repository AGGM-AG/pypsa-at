(function () {
  let rendering = false;

  function isDarkMode() {
    return document.body.getAttribute("data-md-color-scheme") === "slate";
  }

  function getThemeConfiguration() {
  const flowchart = {
    curve: "basis",
    nodeSpacing: 45,
    rankSpacing: 55,
    padding: 20
  };

  if (isDarkMode()) {
    return {
      theme: "base",
      flowchart,
      themeVariables: {
        fontFamily: "Inter, -apple-system, Segoe UI, sans-serif",
        fontSize: "15px",
        background: "#0f172a",
        lineColor: "#94a3b8",
        primaryTextColor: "#e2e8f0",
        edgeLabelBackground: "#1e293b",
        primaryColor: "#334155",
        primaryBorderColor: "#64748b"
      }
    };
  }

  return {
    theme: "base",
    flowchart,
    themeVariables: {
      fontFamily: "Inter, -apple-system, Segoe UI, sans-serif",
      fontSize: "15px",
      background: "#ffffff",
      lineColor: "#cbd5e1",
      primaryTextColor: "#1e293b",
      edgeLabelBackground: "#ffffff",
      primaryColor: "#f8fafc",
      primaryBorderColor: "#cbd5e1"
    }
  };
}


  function renderMermaid() {
    if (
      typeof mermaid === "undefined" ||
      rendering
    ) {
      return;
    }

    const diagrams = document.querySelectorAll(".mermaid");

    if (!diagrams.length) {
      return;
    }

    rendering = true;

    diagrams.forEach(function (diagram) {
      // Preserve the original Mermaid source before Mermaid replaces it
      // with an SVG.
      if (!diagram.dataset.mermaidSource) {
        diagram.dataset.mermaidSource = diagram.textContent.trim();
      }

      diagram.removeAttribute("data-processed");
      diagram.innerHTML = diagram.dataset.mermaidSource;
    });

    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      ...getThemeConfiguration()
    });

    mermaid
      .run({
        nodes: diagrams
      })
      .finally(function () {
        rendering = false;
      });
  }

  function observeColorSchemeChanges() {
    const observer = new MutationObserver(function () {
      renderMermaid();
    });

    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"]
    });
  }

  function start() {
    renderMermaid();
    observeColorSchemeChanges();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  // Required when using MkDocs Material instant navigation.
  if (typeof document$ !== "undefined") {
    document$.subscribe(function () {
      setTimeout(renderMermaid, 0);
    });
  }
})();
