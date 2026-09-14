# -*- coding: utf-8 -*-
"""worker_server - 直播服务器（第二阶段 2b-3）

职责:
  1. POST /analyze           表单/JSON 提交 -> 起后台线程跑完整分析，
                             事件实时写 output/live/<run_id>/progress.jsonl + 快照
  2. GET  /progress/<run_id> 快照（前端 ?source=live 每 2 秒轮询的就是它）
  3. GET  /result/<run_id>   归一化终态（调试用）
  4. GET  /                  起飞页：填代码一键开直播，自动跳到 v8 页面

用法:
  python -X utf8 scripts/worker_server.py            # 默认 127.0.0.1:8766
  前端静态页另起:  python -m http.server 8765 --directory docs/mockups

注意: 单工作线程 MVP——同时只跑一个分析（重复提交返回 409）。
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))  # python scripts/worker_server.py 时 src 包可导入
os.chdir(PROJECT)                 # 保证数据目录/相对路径一致

from src.agents.orchestrator import MultiAgentOrchestrator   # noqa: E402
from src.infra.progress_emitter import EventEmitter, normalize_result   # noqa: E402

LIVE_ROOT = PROJECT / "output" / "live"
STATIC_BASE = os.environ.get("LIVE_STATIC_BASE", "http://localhost:8765")
API_HOST = os.environ.get("LIVE_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("LIVE_API_PORT", "8766"))

logger = logging.getLogger("worker_server")

app = FastAPI(title="multi-agent-stock live worker")

# v8 页面在 8765、本服务在 8766，跨端口轮询需要放行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 单飞状态（同时只允许一个分析在跑）
_current = {
    "run_id": None,
    "emitter": None,
    "thread": None,
    "result": None,
    "error": None,
}
_current_lock = threading.Lock()


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def _load_config() -> dict:
    with open(PROJECT / "config" / "model.json", encoding="utf-8") as f:
        return json.load(f)


def _resolve_stock_name(code: str) -> str:
    """用 tushare stock_basic 查股票中文名，失败回退代码本身。"""
    try:
        from src.tools.tushare_utils import get_tushare_client
        client = get_tushare_client()
        rows = client._call("stock_basic", {"ts_code": code})
        if rows and rows[0].get("name"):
            return rows[0]["name"]
    except Exception as e:
        logger.warning(f"[Worker] stock name lookup failed: {e}")
    return code


def _new_run_id(code: str) -> str:
    safe = code.replace(".", "_").replace(":", "_")
    return f"r_{safe}_{time.strftime('%Y%m%d_%H%M%S')}"


def _run_analysis_thread(code: str, name: str, run_id: str, out_dir: Path,
                         max_iterations: int, debate_rounds: int):
    """后台线程: 跑完整分析，事件经 EventEmitter 实时落盘。"""
    emitter = EventEmitter(str(run_id), str(out_dir), stock_code=code, stock_name=name)
    with _current_lock:
        _current["emitter"] = emitter
        _current["result"] = None
        _current["error"] = None

    # 每次运行单独留一份日志文件，便于事后排查
    fh = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    try:
        config = _load_config()
        orch = MultiAgentOrchestrator(
            config, persist_dir=str(out_dir / "debate_logs")
        )
        result = orch.run_analysis(
            code,
            max_iterations=max_iterations,
            debate_rounds=debate_rounds,
            on_event=emitter.emit,
            stock_name=name,
        )
        normalized = normalize_result(result, stock_name=name)
        _current["result"] = normalized
        (out_dir / "result.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        emitter.finalize("done")
        logger.info(f"[Worker] run {run_id} done")
    except Exception as e:
        logger.error(f"[Worker] run {run_id} failed: {e}")
        _current["error"] = str(e)
        try:
            emitter.emit("run_error", 6, {"message": str(e)})
        except Exception:
            pass
        emitter.finalize("error")
    finally:
        logging.getLogger().removeHandler(fh)


def _is_busy() -> bool:
    th = _current.get("thread")
    return bool(th and th.is_alive())


# ----------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "busy": _is_busy(),
        "run_id": _current.get("run_id"),
        "last_seq": _current["emitter"].last_seq if _current.get("emitter") else 0,
    }


@app.post("/analyze")
async def analyze(request: Request):
    # 兼容两种提交: HTML 表单(x-www-form-urlencoded) 和 fetch(JSON)
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        body = await request.json()
        code = str(body.get("code") or "").strip()
        name = str(body.get("name") or "").strip()
        max_iterations = int(body.get("max_iterations") or 10)
        debate_rounds = int(body.get("debate_rounds") or 2)
    else:
        form = await request.form()
        code = str(form.get("code") or "").strip()
        name = str(form.get("name") or "").strip()
        max_iterations = int(form.get("max_iterations") or 10)
        debate_rounds = int(form.get("debate_rounds") or 2)

    if not code:
        raise HTTPException(status_code=400, detail="code 不能为空")
    if _is_busy():
        raise HTTPException(status_code=409, detail="已有一个分析在跑，请等它完成")

    # 代码归一（允许 601398 / 601398.SH 两种写法）
    from src.tools.tushare_utils import normalize_code
    code = normalize_code(code)

    if not name:
        name = _resolve_stock_name(code)

    run_id = _new_run_id(code)
    out_dir = LIVE_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    th = threading.Thread(
        target=_run_analysis_thread,
        args=(code, name, run_id, out_dir, max_iterations, debate_rounds),
        daemon=True,
        name=f"run-{run_id}",
    )
    with _current_lock:
        _current["run_id"] = run_id
        _current["thread"] = th
    th.start()

    progress_url = f"{request.base_url}progress/{run_id}"
    live_url = (
        f"{STATIC_BASE}/agent-analysis-demo-v8.html"
        f"?source=live&url={quote(progress_url, safe='')}"
    )

    if "json" in ctype:
        return JSONResponse({"run_id": run_id, "progress_url": progress_url,
                             "live_url": live_url})
    return RedirectResponse(live_url, status_code=303)


@app.get("/progress/{run_id}")
def progress(run_id: str):
    if _current.get("run_id") == run_id and _current.get("emitter"):
        return _current["emitter"].snapshot()
    # 非当前运行（历史/重启后）: 读盘上快照
    snap_file = LIVE_ROOT / run_id / "progress.json"
    if snap_file.exists():
        return JSONResponse(json.loads(snap_file.read_text(encoding="utf-8")))
    raise HTTPException(status_code=404, detail=f"run not found: {run_id}")


@app.get("/result/{run_id}")
def result(run_id: str):
    if _current.get("run_id") == run_id and _current.get("result") is not None:
        return _current["result"]
    res_file = LIVE_ROOT / run_id / "result.json"
    if res_file.exists():
        return JSONResponse(json.loads(res_file.read_text(encoding="utf-8")))
    raise HTTPException(status_code=404, detail=f"result not ready: {run_id}")


@app.get("/events/{run_id}")
def events_file(run_id: str):
    """原始事件流 JSONL（v8 页面 ?replay= 带动画回放用）。"""
    f = LIVE_ROOT / run_id / "progress.jsonl"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return FileResponse(f, media_type="text/plain", filename="progress.jsonl")


@app.get("/runs")
def runs():
    """历史分析存档列表（喂狗粮期: 每次分析都是可积累的资产）。"""
    items = []
    for d in LIVE_ROOT.iterdir() if LIVE_ROOT.exists() else []:
        snap_f = d / "progress.json"
        if not snap_f.exists():
            continue
        try:
            snap = json.loads(snap_f.read_text(encoding="utf-8"))
        except Exception:
            continue
        item = {
            "run_id": snap.get("run_id", d.name),
            "stock_code": snap.get("stock_code", ""),
            "stock_name": snap.get("stock_name", ""),
            "status": snap.get("status", "unknown"),
            "started_ts": snap.get("started_ts", 0),
            "last_seq": snap.get("last_seq", 0),
        }
        res_f = d / "result.json"
        if res_f.exists():
            try:
                res = json.loads(res_f.read_text(encoding="utf-8"))
                meta = res.get("meta", {})
                combined = res.get("combined", {})
                trader = res.get("trader", {})
                item.update({
                    "combined_score": combined.get("combined_score"),
                    "combined_direction": combined.get("combined_direction"),
                    "action": trader.get("action"),
                    "risk_level": combined.get("risk_level"),
                    "duration_s": meta.get("duration_s"),
                })
            except Exception:
                pass
        items.append(item)
    items.sort(key=lambda x: x.get("started_ts") or 0, reverse=True)
    return {"runs": items}


LANDING_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>AI 团队作战直播 · 起飞页</title>
<style>
body{font-family:-apple-system,"PingFang SC","Segoe UI",sans-serif;background:#0d1117;
     color:#e6edf3;display:flex;align-items:flex-start;justify-content:center;
     padding:40px 16px;min-height:100vh;margin:0;gap:24px;flex-wrap:wrap}
.card{background:#161b22;border:1px solid #2a3550;border-radius:14px;
      padding:32px;width:380px;height:fit-content}
h1{font-size:20px;margin:0 0 6px}
h2{font-size:15px;margin:0 0 4px}
p.sub{color:#8b949e;font-size:13px;margin:0 0 22px}
label{display:block;font-size:12px;color:#8b949e;margin:12px 0 4px}
input{width:100%;box-sizing:border-box;background:#0d1117;color:#e6edf3;
      border:1px solid #2a3550;border-radius:8px;padding:10px;font-size:14px}
input:focus{outline:none;border-color:#4ECDC4}
button{width:100%;margin-top:22px;background:#4ECDC4;color:#0d1117;border:none;
       border-radius:8px;padding:12px;font-size:15px;font-weight:700;cursor:pointer}
button:hover{filter:brightness(1.1)}
.busy{color:#faad14;font-size:12px;margin-top:12px;text-align:center}
.hist{background:#161b22;border:1px solid #2a3550;border-radius:14px;
      padding:24px 28px;width:640px;max-width:96vw;height:fit-content}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th{color:#8b949e;font-weight:600;text-align:left;padding:6px 8px;
   border-bottom:1px solid #2a3550;font-size:12px}
td{padding:8px;border-bottom:1px solid rgba(255,255,255,.05)}
a{color:#4ECDC4;text-decoration:none;margin-right:10px;font-size:12px}
a:hover{text-decoration:underline}
.st-done{color:#52c41a}.st-running{color:#faad14}.st-error{color:#ff4444}
.act-buy{color:#ff6b6b;font-weight:700}.act-sell{color:#4ade80;font-weight:700}
.act-hold{color:#faad14;font-weight:700}.act-watch{color:#8b949e;font-weight:700}
.empty{color:#8b949e;font-size:13px;padding:14px 0;text-align:center}
</style></head><body>
<div class="card">
  <h1>AI 团队作战直播</h1>
  <p class="sub">提交后自动跳转到直播页，全程约 4~7 分钟</p>
  <form method="post" action="/analyze">
    <label>股票代码（如 601398 或 601398.SH）</label>
    <input name="code" required placeholder="601398">
    <label>股票名称（留空自动查询）</label>
    <input name="name" placeholder="工商银行">
    <button type="submit">开始直播分析</button>
  </form>
  <div class="busy" id="busy"></div>
</div>
<div class="hist">
  <h2>历史分析存档</h2>
  <p class="sub" style="margin:0">跑过的都留着 · 回放带动画 · 每 5 秒自动刷新</p>
  <div id="hist-body"><div class="empty">加载中…</div></div>
</div>
<script>
const ACT_CN={buy:'买入',sell:'卖出',hold:'持有',watch:'观望'};
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;')
  .replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtTime(ts){if(!ts)return'-';const d=new Date(ts);
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;}
function loadRuns(){
  fetch('/runs').then(r=>r.json()).then(d=>{
    const el=document.getElementById('hist-body');
    if(!d.runs||!d.runs.length){el.innerHTML='<div class="empty">还没有记录，提交第一只股票吧</div>';return;}
    el.innerHTML='<table><tr><th>时间</th><th>股票</th><th>评分</th><th>决策</th><th>风险</th><th>用时</th><th>状态</th><th></th></tr>'
      + d.runs.map(r=>{
        const live=`http://localhost:8765/agent-analysis-demo-v8.html?source=live&url=${encodeURIComponent(location.origin+'/progress/'+r.run_id)}`;
        const rep=`http://localhost:8765/agent-analysis-demo-v8.html?replay=${encodeURIComponent(location.origin+'/events/'+r.run_id)}`;
        const st=r.status==='done'?'<span class="st-done">完成</span>'
                :r.status==='error'?'<span class="st-error">失败</span>'
                :'<span class="st-running">进行中</span>';
        const act=r.action?`<span class="act-${r.action}">${ACT_CN[r.action]||r.action}</span>`:'-';
        return `<tr><td>${fmtTime(r.started_ts)}</td>
          <td><b>${esc(r.stock_name)}</b><br><span style="color:#8b949e;font-size:11px">${esc(r.stock_code)}</span></td>
          <td>${r.combined_score??'-'}</td><td>${act}</td><td>${esc(r.risk_level||'-')}</td>
          <td>${r.duration_s?r.duration_s+'s':'-'}</td><td>${st}</td>
          <td>${r.status==='done'?`<a href="${rep}" target="_blank">▶ 回放</a>`:''}<a href="${live}" target="_blank">终态</a></td></tr>`;
      }).join('')+'</table>';
  }).catch(()=>{});
}
loadRuns(); setInterval(loadRuns, 5000);
fetch('/health').then(r=>r.json()).then(h=>{
  if(h.busy){document.getElementById('busy').textContent=
    '当前有分析进行中(seq '+h.last_seq+')，提交会被拒绝直到完成';}
});
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def landing():
    return LANDING_HTML


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    print(f"[worker_server] API    -> http://{API_HOST}:{API_PORT}")
    print(f"[worker_server] 起飞页 -> http://{API_HOST}:{API_PORT}/")
    print(f"[worker_server] 静态页 -> {STATIC_BASE}/agent-analysis-demo-v8.html")
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="warning")
