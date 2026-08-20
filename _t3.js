function test(){
        return '<div class="dc-flash"><span class="idx">?</span><span>' +
          "<b>" + esc(it.title) + "</b> ? " + esc(it.summary || "") + "<br>" +
          '<span class="muted">?? ? ' + esc(sname) + ' ? <a href="' + esc(orig) +
          '" target="_blank" rel="noopener">?? ?</a></span></span></div>";
      }).join("");
      sectionsHtml += '<div class="dc-section"><div class="sec-h">' + esc(sec.label) + "</div>" + flashes + "</div>";
    });
}
