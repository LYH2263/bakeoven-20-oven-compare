import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
type P = { id: number; name: string };
type B = { id: number; code: string; product_name?: string; oven_label?: string; start_min: number; ferment_end?: number; bake_end?: number; status: string };
type CItem = { opponent_batch_id: number; opponent_code: string; opponent_product_name?: string | null; opponent_phase_label: string; opponent_start_min: number; opponent_end_min: number; candidate_phase_label: string; candidate_start_min: number; candidate_end_min: number };
type POven = { oven_id: number; oven_label: string; ferment_end: number; bake_end: number; available: boolean; conflicts: CItem[] };
type Preview = { product_id: number; product_name: string; start_min: number; ovens: POven[] };
type Reject409 = { detail: string; oven_id: number; oven_label: string; start_min: number; conflicts: CItem[] };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }

function ConflictLines({ cs }: { cs: CItem[] }) {
  return <ul className="preview-conflicts mono">
    {cs.map((c, i) => <li key={i}>
      对手 {c.opponent_code}（{c.opponent_product_name ?? "未知产品"}）{c.opponent_phase_label} {fmt(c.opponent_start_min)}–{fmt(c.opponent_end_min)}
      <br />本批{c.candidate_phase_label} {fmt(c.candidate_start_min)}–{fmt(c.candidate_end_min)} 与之重叠
    </li>)}
  </ul>;
}

export default function BatchesPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [rows, setRows] = useState<B[]>([]);
  const [pid, setPid] = useState<number | "">("");
  const [start, setStart] = useState(11 * 60);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pvLoading, setPvLoading] = useState(false);
  const [pvErr, setPvErr] = useState("");
  const [selected, setSelected] = useState<number | "">("");
  const [creating, setCreating] = useState(false);
  const [reject, setReject] = useState<Reject409 | null>(null);
  const [msg, setMsg] = useState("");
  const reload = () => api<B[]>("/batches").then(setRows);

  async function runPreview(productId: number | "", startMin: number) {
    if (productId === "") return;
    setPvLoading(true); setPvErr(""); setReject(null); setSelected("");
    try {
      setPreview(await api<Preview>("/batches/preview", { method: "POST", body: JSON.stringify({ product_id: productId, start_min: startMin }) }));
    } catch (e) { setPreview(null); setPvErr(e instanceof Error ? e.message : String(e)); }
    finally { setPvLoading(false); }
  }

  useEffect(() => {
    api<P[]>("/products").then(p => {
      setProducts(p);
      if (p[0]) { setPid(p[0].id); void runPreview(p[0].id, 11 * 60); }
    });
    reload();
  }, []);

  function invalidate() { setPreview(null); setSelected(""); setReject(null); setMsg(""); }

  async function create() {
    if (selected === "" || pid === "") return;
    setCreating(true); setMsg(""); setReject(null);
    try {
      const b = await api<B>("/batches", { method: "POST", body: JSON.stringify({ product_id: pid, oven_id: selected, start_min: start }) });
      setMsg(`已排产 ${b.code}`);
      await reload();
      await runPreview(pid, start);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.data && typeof e.data === "object" && "conflicts" in e.data) {
        setReject(e.data as Reject409);
        void runPreview(pid, start);
      } else {
        setPvErr(e instanceof Error ? e.message : String(e));
      }
    } finally { setCreating(false); }
  }

  return (<>
    <h2>批次</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => { setPid(Number(e.target.value)); invalidate(); }}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <label>开工分钟 <input type="number" min={0} max={1439} value={start} onChange={e => { setStart(Number(e.target.value)); invalidate(); }} style={{ width: 90 }} /> <span className="mono">{fmt(start)}</span></label>
      <button onClick={() => void runPreview(pid, start)} disabled={pvLoading || pid === ""}>{pvLoading ? "试排中…" : "试排各炉"}</button>
      <button onClick={create} disabled={selected === "" || creating}>{creating ? "创建中…" : "创建生产批次"}</button>
    </div>
    {msg && <div className="ok">{msg}</div>}
    {reject && <div className="err"><div>排产未保存：{reject.oven_label} 在提交时已被占用，请重新试排</div><ConflictLines cs={reject.conflicts} /></div>}
    {pvErr && <div className="err">{pvErr}</div>}
    {preview && <>
      <h3>试排：{preview.product_name}，{fmt(preview.start_min)} 开工（发酵止 / 烘烤止按炉列出，勾选一座可排炉后创建）</h3>
      <table className="table"><thead><tr><th>选择</th><th>炉位</th><th>发酵止</th><th>烘烤止</th><th>状态</th><th>对手批次与阶段</th></tr></thead>
      <tbody>{preview.ovens.map(o => <tr key={o.oven_id} className={o.available ? "" : "preview-row--blocked"}>
        <td><label><input type="radio" name="oven" value={o.oven_id} checked={selected === o.oven_id} disabled={!o.available} onChange={() => setSelected(o.oven_id)} /> 选这座</label></td>
        <td>{o.oven_label}</td>
        <td className="mono">{fmt(o.ferment_end)}</td>
        <td className="mono">{fmt(o.bake_end)}</td>
        <td><span className={`conflict-chip${o.available ? " conflict-chip--ok" : ""}`}>{o.available ? "可排" : "不可排"}</span></td>
        <td>{o.available ? "—" : <ConflictLines cs={o.conflicts} />}</td>
      </tr>)}</tbody></table>
    </>}
    <h3>已排批次</h3>
    <table className="table"><thead><tr><th>批次</th><th>产品</th><th>炉位</th><th>发酵</th><th>烘烤结束</th><th>状态</th></tr></thead>
    <tbody>{rows.map(b => <tr key={b.id}><td className="mono">{b.code}</td><td>{b.product_name}</td><td>{b.oven_label}</td>
      <td className="mono">{fmt(b.start_min)}–{fmt(b.ferment_end ?? b.start_min)}</td>
      <td className="mono">{fmt(b.bake_end ?? b.start_min)}</td><td>{b.status}</td></tr>)}</tbody></table>
  </>);
}
