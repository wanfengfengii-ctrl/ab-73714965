/* 海缆故障定位前端：录入树网/传感器/到时区间，调用定位 API，渲染全部待检区段。 */
(function () {
  "use strict";

  var API_BASE = (window.API_BASE || "/api").replace(/\/+$/, "");

  var EXAMPLE = {
    nodes: "1, 2, 3, 4",
    edges: "1 2 4\n2 3 4\n2 4 4",
    speed: "1",
    sensors: [
      { id: "S1", node: "1", start: "4.5", end: "5.5" },
      { id: "S2", node: "2", start: "0.5", end: "1.5" },
      { id: "S3", node: "3", start: "2.5", end: "5.5" }
    ]
  };

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ---------------- 传感器行 ---------------- */

  function addSensorRow(sensor) {
    var tbody = $("sensor-rows");
    var tr = document.createElement("tr");
    var data = sensor || {};
    var fields = [
      { key: "id", placeholder: "S" + (tbody.children.length + 1) },
      { key: "node", placeholder: "节点" },
      { key: "start", placeholder: "起点" },
      { key: "end", placeholder: "终点" }
    ];
    fields.forEach(function (f) {
      var td = document.createElement("td");
      var input = document.createElement("input");
      input.type = "text";
      input.spellcheck = false;
      input.placeholder = f.placeholder;
      input.dataset.field = f.key;
      if (data[f.key] !== undefined) input.value = data[f.key];
      td.appendChild(input);
      tr.appendChild(td);
    });
    var tdDel = document.createElement("td");
    var btn = el("button", "ghost small", "删除");
    btn.type = "button";
    btn.addEventListener("click", function () {
      tr.remove();
    });
    tdDel.appendChild(btn);
    tr.appendChild(tdDel);
    tbody.appendChild(tr);
  }

  /* ---------------- 输入收集与本地预检 ---------------- */

  function ClientError(message) {
    this.message = message;
  }

  function parseNodes(text) {
    var tokens = text.split(/[\s,，]+/).filter(function (t) { return t.length > 0; });
    var nodes = tokens.map(function (t) {
      if (!/^-?\d+$/.test(t)) throw new ClientError("节点编号必须是整数: " + t);
      return parseInt(t, 10);
    });
    var seen = {};
    nodes.forEach(function (n) {
      if (seen[n]) throw new ClientError("节点编号重复: " + n);
      seen[n] = true;
    });
    if (nodes.length < 4 || nodes.length > 12) {
      throw new ClientError("节点数必须在 4~12 之间，当前 " + nodes.length + " 个");
    }
    return nodes;
  }

  function parseEdges(text) {
    var lines = text.split("\n");
    var edges = [];
    lines.forEach(function (line, idx) {
      var trimmed = line.trim();
      if (!trimmed) return;
      var parts = trimmed.split(/[\s,，]+/).filter(function (t) { return t.length > 0; });
      if (parts.length !== 3) {
        throw new ClientError("第 " + (idx + 1) + " 行边格式应为：起点 终点 长度");
      }
      if (!/^-?\d+$/.test(parts[0]) || !/^-?\d+$/.test(parts[1])) {
        throw new ClientError("第 " + (idx + 1) + " 行边的端点必须是整数节点编号");
      }
      edges.push({
        u: parseInt(parts[0], 10),
        v: parseInt(parts[1], 10),
        length: parts[2]
      });
    });
    if (edges.length === 0) throw new ClientError("请至少录入一条边");
    return edges;
  }

  function collectSensors() {
    var rows = $("sensor-rows").children;
    if (rows.length < 3 || rows.length > 6) {
      throw new ClientError("传感器数量必须在 3~6 之间，当前 " + rows.length + " 台");
    }
    var sensors = [];
    for (var i = 0; i < rows.length; i += 1) {
      var inputs = rows[i].querySelectorAll("input");
      var sensor = {};
      inputs.forEach(function (input) {
        sensor[input.dataset.field] = input.value.trim();
      });
      if (!sensor.id) sensor.id = "S" + (i + 1);
      if (!/^-?\d+$/.test(sensor.node)) {
        throw new ClientError("传感器 " + sensor.id + " 的所在节点必须是整数编号");
      }
      sensors.push({
        id: sensor.id,
        node: parseInt(sensor.node, 10),
        start: sensor.start,
        end: sensor.end
      });
    }
    return sensors;
  }

  function buildPayload() {
    var speed = $("speed").value.trim();
    if (!speed) throw new ClientError("请填写统一传播速度");
    return {
      nodes: parseNodes($("nodes").value),
      edges: parseEdges($("edges").value),
      speed: speed,
      sensors: collectSensors()
    };
  }

  /* ---------------- 渲染 ---------------- */

  function clearReport() {
    $("report").innerHTML = "";
    $("error").hidden = true;
    $("error").textContent = "";
    $("empty-hint").hidden = false;
  }

  function showError(code, message) {
    $("report").innerHTML = "";
    $("empty-hint").hidden = true;
    var box = $("error");
    box.textContent = "[" + code + "] " + message;
    box.hidden = false;
  }

  function fmtRat(rat) {
    if (rat.exact.indexOf("/") === -1) return rat.exact;
    var dec = Math.round(rat.decimal * 1e6) / 1e6;
    return rat.exact + "（" + dec + "）";
  }

  function fmtInterval(interval) {
    return "[" + fmtRat(interval.start) + ", " + fmtRat(interval.end) + "]";
  }

  function renderReport(data) {
    $("error").hidden = true;
    $("empty-hint").hidden = true;
    var report = $("report");
    report.innerHTML = "";

    var summary = el("div", "summary");
    summary.appendChild(el("p", "lead",
      "共 " + data.segment_count + " 段待检区段"));
    summary.appendChild(el("p", null,
      "可共同成立的故障发生时刻范围：" + fmtInterval(data.occurrence_time)));
    summary.appendChild(el("p", "note",
      "传播速度：" + fmtRat(data.speed) + "；以下各区段上的任意闭区间位置均能使全部到时记录成立。"));
    report.appendChild(summary);

    var table = el("table", "result-table");
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    ["管段（边）", "边上位置（距起点）", "里程范围", "故障发生时刻范围", "端点"]
      .forEach(function (h) {
        headRow.appendChild(el("th", null, h));
      });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    data.segments.forEach(function (seg) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, seg.u + " – " + seg.v + "（全长 " + fmtRat(seg.edge_length) + "）"));
      tr.appendChild(el("td", null, fmtInterval(seg.position_from_u)));
      tr.appendChild(el("td", null, fmtInterval(seg.mileage)));
      tr.appendChild(el("td", null, fmtInterval(seg.occurrence_time)));
      var marks = [];
      if (seg.includes_u) marks.push("经节点 " + seg.u);
      if (seg.includes_v) marks.push("经节点 " + seg.v);
      tr.appendChild(el("td", null, marks.join("；") || "—"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    report.appendChild(table);
  }

  /* ---------------- 提交 ---------------- */

  function submit() {
    clearReport();
    var payload;
    try {
      payload = buildPayload();
    } catch (err) {
      if (err instanceof ClientError) {
        showError("INPUT", err.message);
        return;
      }
      throw err;
    }
    var btn = $("submit");
    btn.disabled = true;
    fetch(API_BASE + "/locate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        return resp.json().then(function (body) {
          return { status: resp.status, body: body };
        });
      })
      .then(function (result) {
        var body = result.body;
        if (body && body.ok) {
          renderReport(body);
        } else if (body && body.error) {
          showError(body.error.code || "ERROR", body.error.message || "未知错误");
        } else {
          showError("BAD_RESPONSE", "服务返回了无法识别的响应（HTTP " + result.status + "）");
        }
      })
      .catch(function () {
        showError("NETWORK", "无法连接定位服务，请确认 API 已启动");
      })
      .then(function () {
        btn.disabled = false;
      });
  }

  function loadExample() {
    $("nodes").value = EXAMPLE.nodes;
    $("edges").value = EXAMPLE.edges;
    $("speed").value = EXAMPLE.speed;
    $("sensor-rows").innerHTML = "";
    EXAMPLE.sensors.forEach(addSensorRow);
    clearReport();
  }

  /* ---------------- 初始化 ---------------- */

  $("add-sensor").addEventListener("click", function () {
    addSensorRow();
  });
  $("submit").addEventListener("click", submit);
  $("load-example").addEventListener("click", loadExample);
  $("clear").addEventListener("click", clearReport);

  loadExample();
})();
