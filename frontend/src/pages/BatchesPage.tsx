import { useEffect, useState } from "react";
import { api } from "../api/client";
type P = { id: number; name: string };
type B = { id: number; code: string; product_name?: string; oven_label?: string; start_min: number; ferment_end?: number; bake_end?: number; status: string };
type PConflict = { batch_id: number; code: string; phase: string; start_min: number; end_min: number };
type OvenPreview = { oven_id: number; oven_label: string; ferment_end: number; bake_end: number; available: boolean; conflicts: PConflict[] };
type Preview = { product_id: number; start_min: number; ovens: OvenPreview[] };
function fmt(m: number) { const h = Math.floor(m/60), mm = m%60; return `${String(h).padStart(2,"0")}:${String(mm).padStart(2,"0")}`; }
const phaseName = (p: string) => (p === "ferment" ? "发酵" : "烘烤");
export default function BatchesPage() {
  const [products, setProducts] = useState<P[]>([]);
  const [rows, setRows] = useState<B[]>([]);
  const [pid, setPid] = useState<number | "">("");
  const [start, setStart] = useState(11 * 60);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [checked, setChecked] = useState<number | null>(null);
  const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  const reload = () => api<B[]>("/batches").then(setRows);
  useEffect(() => {
    api<P[]>("/products").then(p => { setProducts(p); if (p[0]) setPid(p[0].id); });
    reload();
  }, []);
  // 选定产品和开工分钟后即试排：只读，不写批次
  useEffect(() => {
    setChecked(null);
    if (pid === "") { setPreview(null); return; }
    api<Preview>(`/batches/preview?product_id=${pid}&start_min=${start}`)
      .then(setPreview)
      .catch(() => setPreview(null));
  }, [pid, start]);
  async function create() {
    if (pid === "" || checked === null) return;
    setMsg(""); setErr("");
    try {
      const b = await api<B>("/batches", { method: "POST", body: JSON.stringify({ product_id: pid, oven_id: checked, start_min: start }) });
      setMsg(`已排产 ${b.code}：发酵止 ${fmt(b.ferment_end ?? start)}，烘烤止 ${fmt(b.bake_end ?? start)}`);
      setChecked(null);
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }
  return (<>
    <h2>批次</h2>
    <div className="toolbar">
      <select value={pid} onChange={e => setPid(Number(e.target.value))}>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <label>开工分钟 <input type="number" value={start} onChange={e => setStart(Number(e.target.value))} style={{ width: 90 }} /></label>
      <button onClick={create} disabled={checked === null}>创建生产批次</button>
    </div>
    {msg && <div className="ok">{msg}</div>}
    {err && <div className="err">{err}</div>}
    {preview && <>
      <h3>试排（开工 {fmt(preview.start_min)}，未落库）</h3>
      <table className="table"><thead><tr><th>勾选</th><th>炉位</th><th>发酵止</th><th>烘烤止</th><th>状态</th></tr></thead>
      <tbody>{preview.ovens.map(o => <tr key={o.oven_id}>
        <td><input type="radio" name="oven" checked={checked === o.oven_id} onChange={() => setChecked(o.oven_id)} /></td>
        <td>{o.oven_label}</td>
        <td className="mono">{fmt(o.ferment_end)}</td>
        <td className="mono">{fmt(o.bake_end)}</td>
        <td>{o.available
          ? <span className="ok">可排</span>
          : <span className="err">重叠：{o.conflicts.map(c => `${c.code} ${phaseName(c.phase)}段 ${fmt(c.start_min)}–${fmt(c.end_min)}`).join("；")}</span>}
        </td></tr>)}</tbody></table>
    </>}
    <table className="table"><thead><tr><th>批次</th><th>产品</th><th>炉位</th><th>发酵</th><th>烘烤结束</th><th>状态</th></tr></thead>
    <tbody>{rows.map(b => <tr key={b.id}><td className="mono">{b.code}</td><td>{b.product_name}</td><td>{b.oven_label}</td>
      <td className="mono">{fmt(b.start_min)}–{fmt(b.ferment_end ?? b.start_min)}</td>
      <td className="mono">{fmt(b.bake_end ?? b.start_min)}</td><td>{b.status}</td></tr>)}</tbody></table>
  </>);
}
