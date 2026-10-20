(function () {
  'use strict';

  // Set by the page: the pinned jsDelivr URL for this RDKit.js release.
  var RDKIT_URL = window.SERV_RDKIT_URL;
  if (!RDKIT_URL) {
    console.error('serv: window.SERV_RDKIT_URL is not set');
    return;
  }

  // Without an explicit width or height, every drawing is rendered at this
  // bond length and then cropped to its own extent. A fixed bond length keeps
  // atom labels the same size in every drawing on a page, and cropping keeps
  // each box the size of its own molecule instead of a shared canvas.
  var BOND_LENGTH = 24;
  var CANVAS = { width: 1600, height: 1200 };
  var FIT_MARGIN = 6;

  // RDKit.js ignores unknown keys but rejects wrongly typed ones, so pass
  // through only the keys this build accepts.
  var MOLECULE_KEYS = [
    'width', 'height', 'legend', 'atoms', 'bonds', 'rotate', 'kekulize',
    'addAtomIndices', 'addBondIndices', 'atomLabels',
    'highlightAtomMultipleColors', 'fixedBondLength'
  ];
  var REACTION_KEYS = [
    'width', 'height', 'legend', 'highlightByReactant',
    'highlightColorsReactants', 'fixedBondLength'
  ];

  var PROPERTIES = [
    ['exactmw', 'Molecular weight', 2],
    ['CrippenClogP', 'cLogP', 2],
    ['tpsa', 'TPSA (\u00c5\u00b2)', 1],
    ['lipinskiHBD', 'H-bond donors', 0],
    ['lipinskiHBA', 'H-bond acceptors', 0],
    ['NumRotatableBonds', 'Rotatable bonds', 0],
    ['NumHeavyAtoms', 'Heavy atoms', 0],
    ['NumAromaticRings', 'Aromatic rings', 0],
    ['FractionCSP3', 'Fraction sp\u00b3', 3],
    ['NumAtomStereoCenters', 'Stereo centres', 0]
  ];

  // Every drawing option this renderer understands. Attribute names are
  // matched case-insensitively because HTML lowercases them.
  var OPTION_KEYS = [
    'width', 'height', 'legend', 'caption', 'fixedBondLength', 'rotate', 'kekulize',
    'addAtomIndices', 'addBondIndices', 'atoms', 'bonds', 'atomLabels',
    'highlightAtomMultipleColors', 'highlightByReactant', 'highlightColorsReactants'
  ];
  var KEY_BY_LOWER = {};
  OPTION_KEYS.forEach(function (key) { KEY_BY_LOWER[key.toLowerCase()] = key; });

  // Filled from a document-wide `chem-options` block before anything is drawn.
  var documentDefaults = {};

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.onload = function () { resolve(); };
      el.onerror = function () { reject(new Error('could not load ' + src)); };
      document.head.appendChild(el);
    });
  }

  function message(text) {
    var note = document.createElement('p');
    note.className = 'chem-error';
    note.textContent = text;
    return note;
  }

  function fail(pre, text, err) {
    var detail = err && err.message ? err.message : err;
    pre.replaceWith(message(detail ? text + ' (' + detail + ')' : text));
  }

  // A fence renders as <pre class="..."><code>...</code></pre>; textContent
  // undoes the entity escaping, so "A&gt;&gt;B" arrives as "A>>B".
  function codeText(pre) {
    var code = pre.querySelector('code');
    return (code || pre).textContent;
  }

  function blockLines(pre) {
    return codeText(pre).split('\n')
      .map(function (line) { return line.trim(); })
      .filter(Boolean);
  }

  // "CCO | ethanol" - the part after " | " becomes the caption.
  function splitLabel(line) {
    var at = line.indexOf(' | ');
    if (at < 0) return { value: line.trim(), label: '' };
    return { value: line.slice(0, at).trim(), label: line.slice(at + 3).trim() };
  }

  // A block body is either a bare value line or a JSON object.
  function blockBody(pre, valueKey) {
    var text = codeText(pre).trim();
    if (text.charAt(0) === '{') {
      var parsed = {};
      try {
        parsed = JSON.parse(text);
      } catch (err) {
        parsed = {};
      }
      return { options: parsed, label: parsed.caption || '' };
    }
    var item = splitLabel(text.split('\n')[0].trim());
    var options = {};
    options[valueKey] = item.value;
    return { options: options, label: item.label };
  }

  function pick(options, keys) {
    var out = {};
    keys.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(options, key)) out[key] = options[key];
    });
    return out;
  }

  function merge(target, source) {
    Object.keys(source || {}).forEach(function (key) { target[key] = source[key]; });
    return target;
  }

  // Attribute values arrive as strings, so give JSON a chance to turn them back
  // into numbers, booleans and arrays. Anything else stays a string.
  function coerce(text) {
    if (!text.length) return text;
    try {
      return JSON.parse(text);
    } catch (err) {
      return text;
    }
  }

  // Options written in the fence header, such as
  //
  //     ```{.smiles fixedBondLength=32}
  //
  // The renderer turns "key=value" into "data-key"; both the data- prefixed
  // and bare spellings are accepted, so hand-written HTML also works.
  function fenceOptions(pre) {
    var out = {};
    Array.prototype.forEach.call(pre.attributes, function (attr) {
      var name = attr.name.toLowerCase();
      if (name === 'class' || name === 'id') return;
      if (name.indexOf('data-') === 0) name = name.slice(5);
      var key = KEY_BY_LOWER[name];
      if (key) out[key] = coerce(attr.value);
    });
    return out;
  }

  // A `chem-options` block sets defaults for the whole document and is removed
  // from the page once read. Options are then merged in increasing specificity:
  // document defaults, fence header, JSON body.
  function readDocumentOptions() {
    document.querySelectorAll('pre.chem-options').forEach(function (pre) {
      var text = codeText(pre).trim();
      var declared = {};
      if (text.charAt(0) === '{') {
        try {
          declared = JSON.parse(text);
        } catch (err) {
          declared = {};
        }
      }
      merge(documentDefaults, fenceOptions(pre));
      merge(documentDefaults, declared);
      pre.remove();
    });
  }

  function optionsFor(pre, bodyOptions) {
    return merge(merge(merge({}, documentDefaults), fenceOptions(pre)), bodyOptions || {});
  }

  // Replace the code block with the drawings and their captions.
  function figure(pre, cells) {
    var box = document.createElement('div');
    box.className = 'chem-figure';
    var toFit = [];
    cells.forEach(function (cell) {
      var item = document.createElement('div');
      item.className = 'chem-cell';
      item.appendChild(cell.node);
      if (cell.fit && cell.node.nodeName.toLowerCase() === 'svg') {
        toFit.push(cell.node);
      }
      if (cell.label) {
        var caption = document.createElement('div');
        caption.className = 'chem-label';
        caption.textContent = cell.label;
        item.appendChild(caption);
      }
      box.appendChild(item);
    });
    pre.replaceWith(box);
    // getBBox() only reports real geometry once an element is in the document,
    // so the drawings are cropped after insertion rather than before.
    toFit.forEach(function (svg) { fitToContent(svg, FIT_MARGIN); });
  }

  // Trim an SVG to the extent of its drawing. Atom labels are vector paths in
  // RDKit's output, so this box includes them; <defs> holds the masks that
  // carve gaps around labels and must not be measured.
  function fitToContent(svg, margin) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    svg.querySelectorAll('path, line, circle, ellipse').forEach(function (el) {
      if (el.closest('defs')) return;
      if (el.classList && el.classList.contains('legend')) return;
      var box = el.getBBox();
      if (!box.width && !box.height) return;
      x0 = Math.min(x0, box.x);
      y0 = Math.min(y0, box.y);
      x1 = Math.max(x1, box.x + box.width);
      y1 = Math.max(y1, box.y + box.height);
    });
    if (!isFinite(x0) || x1 <= x0 || y1 <= y0) return;
    var width = Math.ceil(x1 - x0 + 2 * margin);
    var height = Math.ceil(y1 - y0 + 2 * margin);
    svg.setAttribute('viewBox',
      (x0 - margin) + ' ' + (y0 - margin) + ' ' + width + ' ' + height);
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
  }

  function guarded(pre, work) {
    try {
      work();
    } catch (err) {
      fail(pre, 'Could not render this block', err);
    }
  }

  // ------------------------------------------------------------------------
  // Structures and schemes, drawn with RDKit.js
  // ------------------------------------------------------------------------

  var rdkitLoaded = null;

  function loadRDKit() {
    if (!rdkitLoaded) {
      rdkitLoaded = loadScript(RDKIT_URL).then(function () {
        if (typeof window.initRDKitModule !== 'function') {
          throw new Error('RDKit.js did not expose initRDKitModule');
        }
        return window.initRDKitModule();
      });
    }
    return rdkitLoaded;
  }

  // RDKit returns the image as a string. Strip the XML declaration, then
  // import the root element into this document. Returns null on failure.
  function svgNode(markup, name) {
    var root = null;
    try {
      var text = String(markup).replace(/^<\?xml[^>]*\?>\s*/, '');
      var doc = new DOMParser().parseFromString(text, 'image/svg+xml');
      if (!doc.querySelector('parsererror') &&
          doc.documentElement &&
          doc.documentElement.nodeName.toLowerCase() === 'svg') {
        root = doc.documentElement;
      }
    } catch (err) {
      root = null;
    }
    if (!root) return null;

    // RDKit paints an opaque white background. Drop it so a drawing sits on
    // the page background like every other element on the page. Only direct
    // children are touched; the mask rectangles inside <defs> carve the gaps
    // around atom labels and must stay.
    Array.prototype.forEach.call(root.querySelectorAll(':scope > rect'), function (rect) {
      var paint = (rect.getAttribute('style') || '') + ';' + (rect.getAttribute('fill') || '');
      if (/fill\s*:\s*#(?:ffffff|fff)\s*(?:;|$)/i.test(paint)) rect.remove();
    });

    root.setAttribute('role', 'img');
    if (name) root.setAttribute('aria-label', name);
    return document.importNode(root, true);
  }

  // Draw a structure or a reaction scheme. RDKit returns null when it cannot
  // parse the input, which is how invalid SMILES are caught.
  function drawing(RDKit, value, details, isReaction) {
    var object = isReaction ? RDKit.get_rxn(value) : RDKit.get_mol(value);
    if (!object) return null;
    try {
      return object.get_svg_with_highlights(JSON.stringify(details));
    } finally {
      object.delete();
    }
  }

  // Build the RDKit drawing options for a block and report whether the result
  // should be cropped to its own content.
  function drawingDetails(options, keys) {
    var details = pick(options, keys);
    var autoFit = options.width === undefined && options.height === undefined;
    var legend = null;
    if (autoFit) {
      if (details.fixedBondLength === undefined) {
        details.fixedBondLength = BOND_LENGTH;
      }
      details.width = CANVAS.width;
      details.height = CANVAS.height;
      // RDKit pins its in-image legend to the bottom of the canvas, so a
      // cropped drawing would keep a tall empty band between the structure and
      // its title. In auto-fit mode the legend becomes the caption instead.
      legend = options.legend || null;
      delete details.legend;
    }
    return { details: details, autoFit: autoFit, legend: legend };
  }

  // Draw one structure or scheme. `kind` forces the interpretation, so a
  // molecule block never silently becomes a reaction scheme.
  function structure(RDKit, value, options, keys, label, kind) {
    var isReaction = kind ? kind === 'reaction' : value.indexOf('>') >= 0;
    var noun = isReaction ? 'reaction' : 'SMILES';
    var prepared = drawingDetails(options, keys);
    var markup = drawing(RDKit, value, prepared.details, isReaction);
    var name = label || options.legend || value;
    var node = markup ? svgNode(markup, name) : null;
    if (!node) {
      return { ok: false, message: 'Not a valid ' + noun + ': ' + value };
    }
    return {
      ok: true,
      cell: { node: node, label: label || prepared.legend, fit: prepared.autoFit }
    };
  }

  function drawSmiles(pre, RDKit) {
    var lines = blockLines(pre);
    if (!lines.length) {
      fail(pre, 'Empty smiles block');
      return;
    }
    var shared = optionsFor(pre, {});
    figure(pre, lines.map(function (line) {
      var item = splitLabel(line);
      var result = structure(RDKit, item.value, shared, MOLECULE_KEYS, item.label);
      if (result.ok) return result.cell;
      return { node: message(result.message), label: item.label };
    }));
  }

  function drawMolecule(pre, RDKit) {
    var body = blockBody(pre, 'smiles');
    var options = optionsFor(pre, body.options);
    var smiles = options.smiles;
    if (!smiles) {
      fail(pre, 'A molecule block needs a smiles value');
      return;
    }
    var result = structure(RDKit, smiles, options, MOLECULE_KEYS,
      body.label || options.caption || '', 'smiles');
    if (!result.ok) {
      fail(pre, result.message);
      return;
    }
    figure(pre, [result.cell]);
  }

  function drawReaction(pre, RDKit) {
    var body = blockBody(pre, 'reaction');
    var options = optionsFor(pre, body.options);
    var reaction = options.reaction;
    if (!reaction) {
      fail(pre, 'A reaction block needs a reaction value such as "A>>B"');
      return;
    }
    var result = structure(RDKit, reaction, options, REACTION_KEYS,
      body.label || options.caption || '', 'reaction');
    if (!result.ok) {
      fail(pre, result.message);
      return;
    }
    figure(pre, [result.cell]);
  }

  function drawProperties(pre, RDKit) {
    var molecules = [];
    var rejected = [];
    blockLines(pre).forEach(function (line) {
      var item = splitLabel(line);
      var mol = RDKit.get_mol(item.value);
      if (!mol) {
        rejected.push(item.value);
        return;
      }
      var data;
      try {
        data = JSON.parse(mol.get_descriptors());
      } finally {
        mol.delete();
      }
      molecules.push({ label: item.label || item.value, data: data });
    });
    if (!molecules.length) {
      fail(pre, 'No valid SMILES in this properties block: ' + rejected.join(', '));
      return;
    }

    var table = document.createElement('table');
    table.className = 'chem-props';
    var caption = document.createElement('caption');
    caption.textContent = 'RDKit descriptors';
    table.appendChild(caption);

    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    var corner = document.createElement('th');
    corner.setAttribute('scope', 'col');
    corner.textContent = 'Descriptor';
    headRow.appendChild(corner);
    molecules.forEach(function (entry) {
      var th = document.createElement('th');
      th.setAttribute('scope', 'col');
      th.textContent = entry.label;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    PROPERTIES.forEach(function (spec) {
      var row = document.createElement('tr');
      var th = document.createElement('th');
      th.setAttribute('scope', 'row');
      th.textContent = spec[1];
      row.appendChild(th);
      molecules.forEach(function (entry) {
        var value = entry.data[spec[0]];
        var td = document.createElement('td');
        // Round through Number so that "-0.00" is printed as "0.00".
        td.textContent = typeof value === 'number'
          ? Number(value.toFixed(spec[2])).toFixed(spec[2])
          : 'NA';
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    var wrapper = document.createElement('div');
    wrapper.className = 'chem-figure';
    var cell = document.createElement('div');
    cell.className = 'chem-cell';
    if (rejected.length) {
      cell.appendChild(message('Skipped invalid SMILES: ' + rejected.join(', ')));
    }
    cell.appendChild(table);
    wrapper.appendChild(cell);
    pre.replaceWith(wrapper);
  }

  // ------------------------------------------------------------------------
  // Driver: fetch RDKit.js only when the page uses a chemistry block.
  // ------------------------------------------------------------------------

  ready(function () {
    readDocumentOptions();

    var groups = [
      ['pre.smiles', drawSmiles],
      ['pre.molecule', drawMolecule],
      ['pre.reaction', drawReaction],
      ['pre.properties', drawProperties]
    ].map(function (entry) {
      return { blocks: document.querySelectorAll(entry[0]), render: entry[1] };
    });

    var wanted = groups.filter(function (group) { return group.blocks.length; });
    if (!wanted.length) return;

    loadRDKit().then(function (RDKit) {
      wanted.forEach(function (group) {
        group.blocks.forEach(function (pre) {
          guarded(pre, function () { group.render(pre, RDKit); });
        });
      });
    }).catch(function (err) {
      wanted.forEach(function (group) {
        group.blocks.forEach(function (pre) {
          fail(pre, 'RDKit.js is unavailable', err);
        });
      });
    });
  });
})();
