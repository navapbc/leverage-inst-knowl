// Render every [data-markdown] element from its inert <template> source into sanitized HTML.
// The raw markdown is carried inside a <template> so the browser never interprets it as HTML
// before we parse it; template.content.textContent decodes it back to the exact source. Falls
// back to showing the raw text if the CDN libs (marked/DOMPurify) didn't load.
(function () {
  document.querySelectorAll("[data-markdown]").forEach(function (el) {
    var tpl = el.querySelector("template");
    var raw = tpl ? tpl.content.textContent : el.textContent;
    if (window.marked && window.DOMPurify) {
      el.innerHTML = window.DOMPurify.sanitize(window.marked.parse(raw));
    } else {
      el.textContent = raw;
    }
  });
})();
