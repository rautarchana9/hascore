{% from "baseframe/components.html" import networkbar -%}

(function(){

  var head = document.getElementsByTagName('head')[0],
      css = '#hg-bar { display: none; }',
      style = document.createElement('style'),
      sl1 = document.createElement("link"),
      sl2 = document.createElement("link");

  style.type = 'text/css';

  if (style.styleSheet) {
    style.styleSheet.cssText = css;
  } else {
    style.appendChild(document.createTextNode(css));
  }
  head.appendChild(style);

  sl1.type = "text/css";
  sl1.rel = "stylesheet";
  // sl1.href = "{{ url_for('baseframe.static', filename='css/networkbar.css', _external=True) }}";
  sl1.href = "{{ request.url_root[:-1] }}{% assets 'css_all' %}{{ ASSET_URL }}{% endassets %}";
  head.appendChild(sl1);

  sl2.type = "text/css";
  sl2.rel = "stylesheet";
  sl2.href = "//fonts.googleapis.com/css?family=Open+Sans:400italic,600italic,400,600;"
  head.appendChild(sl2);
  
  var container = document.getElementById('networkbar');
  if (container === null) {
    container = document.createElement('div');
    document.body.insertBefore(container, document.body.firstChild);
  }
  container.innerHTML = {{ networkbar(login=false)|tojson|safe }};
})();