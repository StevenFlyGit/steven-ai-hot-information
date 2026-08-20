function test(){
        return '<div class="dc-flash"><span class="idx">•</span><span>' +
          "<b>" + esc(it.title) + "</b> - " + esc(it.summary || "") + "<br>" +
          '<span class="muted">来源 · ' + esc(sname) + ' · <a href="' + esc(orig) +
          '" target="_blank" rel="noopener">原文 -></a></span></span></div>";
      }).join("");
      sectionsHtml += '<div class="dc-section"><div class="sec-h">' + esc(sec.label) + "</div>" + flashes + "</div>";
    });
}
