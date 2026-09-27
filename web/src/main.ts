/* 海缆故障定位前端：录入树网 / 传感器 / 到时区间，调用真实 API 并渲染报告。 */

interface Rational {
  exact: string;
  approx: string;
}

interface SegmentJson {
  edgeIndex: number;
  edge: { from: string; to: string; length: Rational };
  fromStart: { lo: Rational; hi: Rational };
  fromEnd: { lo: Rational; hi: Rational };
  occurrenceTime: { lo: Rational; hi: Rational };
}

interface CulpritJson {
  index: number;
  order: number;
  id: string;
  node: string;
  arrival: { lo: Rational; hi: Rational };
}

type LocateResponse =
  | { ok: true; feasible: true; segmentCount: number; segments: SegmentJson[] }
  | { ok: true; feasible: false; culprit: CulpritJson; message: string }
  | { ok: false; error: { code: string; message: string } };

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`页面缺少元素 #${id}`);
  return node as T;
}

const nodesInput = el<HTMLInputElement>("nodes");
const speedInput = el<HTMLInputElement>("speed");
const edgesBody = el<HTMLTableSectionElement>("edges-body");
const sensorsBody = el<HTMLTableSectionElement>("sensors-body");
const reportEl = el<HTMLElement>("report");
const submitBtn = el<HTMLButtonElement>("submit");

/* ---------- 动态行 ---------- */

function makeInput(cls: string, value: string, placeholder = ""): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "text";
  input.className = cls;
  input.value = value;
  input.placeholder = placeholder;
  input.spellcheck = false;
  return input;
}

function makeDeleteBtn(onDelete: () => void): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "del";
  btn.title = "删除该行";
  btn.textContent = "×";
  btn.addEventListener("click", onDelete);
  return btn;
}

function addEdgeRow(from = "", to = "", length = ""): void {
  const tr = document.createElement("tr");
  const fromInput = makeInput("e-from", from);
  const toInput = makeInput("e-to", to);
  fromInput.setAttribute("list", "node-list");
  toInput.setAttribute("list", "node-list");
  const lenInput = makeInput("e-len", length);
  tr.append(
    cell(fromInput),
    cell(toInput),
    cell(lenInput),
    cell(makeDeleteBtn(() => tr.remove())),
  );
  edgesBody.appendChild(tr);
}

function addSensorRow(id = "", node = "", lo = "", hi = ""): void {
  const tr = document.createElement("tr");
  const idInput = makeInput("s-id", id);
  const nodeInput = makeInput("s-node", node);
  nodeInput.setAttribute("list", "node-list");
  const loInput = makeInput("s-lo", lo);
  const hiInput = makeInput("s-hi", hi);
  tr.append(
    cell(idInput),
    cell(nodeInput),
    cell(loInput),
    cell(hiInput),
    cell(makeDeleteBtn(() => tr.remove())),
  );
  sensorsBody.appendChild(tr);
}

function cell(child: HTMLElement): HTMLTableCellElement {
  const td = document.createElement("td");
  td.appendChild(child);
  return td;
}

function nodeLabels(): string[] {
  return nodesInput.value
    .split(/[\s,，、;；]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function refreshNodeDatalist(): void {
  const list = el<HTMLDataListElement>("node-list");
  list.innerHTML = "";
  for (const label of nodeLabels()) {
    const opt = document.createElement("option");
    opt.value = label;
    list.appendChild(opt);
  }
}

/* ---------- 示例数据 ---------- */

function loadSample(): void {
  nodesInput.value = "N0 N1 N2 N3 N4 N5";
  speedInput.value = "1000";
  edgesBody.innerHTML = "";
  sensorsBody.innerHTML = "";
  for (const to of ["N1", "N2", "N3", "N4", "N5"]) {
    addEdgeRow("N0", to, "1000");
  }
  addSensorRow("SA", "N1", "11.3", "11.5");
  addSensorRow("SB", "N2", "11.3", "11.5");
  addSensorRow("SC", "N3", "11.3", "11.5");
  refreshNodeDatalist();
  clearReport();
}

/* ---------- 请求与渲染 ---------- */

function collectPayload(): unknown {
  const edges = Array.from(edgesBody.querySelectorAll("tr")).map((tr) => ({
    from: (tr.querySelector(".e-from") as HTMLInputElement).value.trim(),
    to: (tr.querySelector(".e-to") as HTMLInputElement).value.trim(),
    length: (tr.querySelector(".e-len") as HTMLInputElement).value.trim(),
  }));
  const sensors = Array.from(sensorsBody.querySelectorAll("tr")).map((tr) => ({
    id: (tr.querySelector(".s-id") as HTMLInputElement).value.trim(),
    node: (tr.querySelector(".s-node") as HTMLInputElement).value.trim(),
    arrival: [
      (tr.querySelector(".s-lo") as HTMLInputElement).value.trim(),
      (tr.querySelector(".s-hi") as HTMLInputElement).value.trim(),
    ],
  }));
  return {
    nodes: nodeLabels(),
    edges,
    speed: speedInput.value.trim(),
    sensors,
  };
}

function clearReport(): void {
  reportEl.innerHTML = "";
}

function showBanner(kind: "error" | "warning", title: string, detail: string): void {
  clearReport();
  const box = document.createElement("div");
  box.className = `banner ${kind}`;
  const h = document.createElement("strong");
  h.textContent = title;
  const p = document.createElement("p");
  p.textContent = detail;
  box.append(h, p);
  reportEl.appendChild(box);
}

function ratSpan(r: Rational): HTMLSpanElement {
  const span = document.createElement("span");
  span.textContent = r.approx;
  if (r.exact !== r.approx) span.title = `精确值：${r.exact}`;
  return span;
}

function rangeCell(lo: Rational, hi: Rational, unit: string): HTMLTableCellElement {
  const td = document.createElement("td");
  td.append(ratSpan(lo), document.createTextNode(" ~ "), ratSpan(hi));
  const unitSpan = document.createElement("span");
  unitSpan.className = "unit";
  unitSpan.textContent = ` ${unit}`;
  td.appendChild(unitSpan);
  return td;
}

function showSegments(data: { segmentCount: number; segments: SegmentJson[] }): void {
  clearReport();
  const summary = document.createElement("div");
  summary.className = "banner ok";
  const h = document.createElement("strong");
  h.textContent = `共 ${data.segmentCount} 段待检区段`;
  const p = document.createElement("p");
  p.textContent =
    "以下每段管段上的闭区间均可同时解释全部传感器记录，请逐段安排检修；里程与时刻均为精确求解的连续范围。";
  summary.append(h, p);
  reportEl.appendChild(summary);

  const table = document.createElement("table");
  table.className = "grid result";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const text of ["#", "管段", "里程范围（距起点）", "里程范围（距终点）", "故障发生时刻范围"]) {
    const th = document.createElement("th");
    th.textContent = text;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.segments.forEach((seg, i) => {
    const tr = document.createElement("tr");

    const idx = document.createElement("td");
    idx.textContent = String(i + 1);

    const name = document.createElement("td");
    const label = document.createElement("span");
    label.textContent = `${seg.edge.from} — ${seg.edge.to}`;
    const len = document.createElement("span");
    len.className = "unit";
    len.textContent = `（全长 ${seg.edge.length.approx} m）`;
    if (seg.edge.length.exact !== seg.edge.length.approx) {
      len.title = `精确值：${seg.edge.length.exact}`;
    }
    name.append(label, len);

    tr.append(
      idx,
      name,
      rangeCell(seg.fromStart.lo, seg.fromStart.hi, "m"),
      rangeCell(seg.fromEnd.lo, seg.fromEnd.hi, "m"),
      rangeCell(seg.occurrenceTime.lo, seg.occurrenceTime.hi, "s"),
    );
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  reportEl.appendChild(table);
}

function render(data: LocateResponse): void {
  if (!data.ok) {
    // 输入不合法：清除旧报告，显示可识别的原因
    showBanner("error", `输入有误【${data.error.code}】`, data.error.message);
    return;
  }
  if (!data.feasible) {
    const c = data.culprit;
    showBanner(
      "warning",
      "无可行位置",
      `${data.message}（首条使交集为空的记录：第 ${c.order} 条，传感器 ${c.id} @ ${c.node}，` +
        `到时区间 ${c.arrival.lo.approx} ~ ${c.arrival.hi.approx} s）`,
    );
    return;
  }
  showSegments(data);
}

async function submit(): Promise<void> {
  submitBtn.disabled = true;
  try {
    const resp = await fetch("/api/locate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
    const data = (await resp.json()) as LocateResponse;
    render(data);
  } catch (err) {
    showBanner("error", "请求失败", `无法调用定位 API：${String(err)}`);
  } finally {
    submitBtn.disabled = false;
  }
}

/* ---------- 事件绑定 ---------- */

el<HTMLButtonElement>("add-edge").addEventListener("click", () => addEdgeRow());
el<HTMLButtonElement>("add-sensor").addEventListener("click", () => addSensorRow());
el<HTMLButtonElement>("load-sample").addEventListener("click", loadSample);
el<HTMLButtonElement>("clear").addEventListener("click", clearReport);
submitBtn.addEventListener("click", () => void submit());
nodesInput.addEventListener("input", refreshNodeDatalist);

loadSample();
