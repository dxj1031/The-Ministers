"""The Ministers 后端入口。

    uvicorn app.back.main:app --reload --port 8000

/            → 监控台
/front/      → 前端原型（同源，省掉 CORS 麻烦）
/api/...     → REST
"""
import json
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import store, access
from .evaluation import scorers
from .services import court, library

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "app" / "front"
# 监控台放仓库根目录：同一个文件，本地跑是实时的，GitHub Pages 上读 snapshot.json 静态快照
CONSOLE = ROOT / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("RENDER"):
        if len(access.key()) < 16:
            raise RuntimeError("Set MINISTERS_ACCESS_KEY to at least 16 characters before publishing.")
        from .core import llm
        from urllib.parse import urlparse
        model_host = urlparse(llm.BASE_URL)
        if not llm.API_KEY or model_host.scheme != "https" or model_host.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("Set a cloud model HTTPS URL and API key in Render environment settings.")
    store.init_db()
    yield


app = FastAPI(title="The Ministers", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"] if not os.environ.get("RENDER") else [], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def protect_court(request: Request, call_next):
    if (request.url.path.startswith("/api/") and request.method != "OPTIONS"
            and request.url.path not in {"/api/health", "/api/access"}
            and not access.allowed(request)):
        return JSONResponse({"detail": "请输入朝堂访问口令"}, status_code=401)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class AccessReq(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/access")
def unlock_court(req: AccessReq, request: Request):
    if access.login_limited(request):
        raise HTTPException(429, "尝试过多，请五分钟后重试")
    if not access.key() or not hmac.compare_digest(req.password.encode(), access.key().encode()):
        raise HTTPException(401, "口令不正确")
    response = JSONResponse({"ok": True})
    response.set_cookie(access.COOKIE, access.issue(), max_age=access.MAX_AGE,
                        httponly=True, secure=bool(os.environ.get("RENDER")) or request.url.scheme == "https",
                        samesite="strict", path="/")
    return response


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def stats():
    # 档案指标和评估用的是同一个 score_user_read —— 同一个判据算两遍，迟早算出两个答案。
    # 监控台这边喂全部朝会，所以 churn 在这里才有数：固定议题集每个 case 只递一份奏章。
    rows = store.user_read_rows()
    out = store.stats()
    out["archive"] = dict(scorers.score_user_read(rows), rows=len(rows))
    return out


@app.get("/api/sessions")
def sessions(limit: int = 50):
    return store.list_sessions(limit)


@app.get("/api/sessions/{session_id}")
def session(session_id: str):
    s = store.get_session(session_id)
    if s is None:
        raise HTTPException(404, "no such session")
    s["traces"] = store.list_traces(session_id)
    s["retrievals"] = store.list_retrievals(session_id)
    return s


@app.get("/api/traces")
def traces(session_id: str | None = None, limit: int = 200):
    return store.list_traces(session_id, limit)


class OpenReq(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=1000)
    lang: str = "zh"
    # 递奏章时就有的倾向。辩论开始前采，之后不再问 —— 事后问拿到的是合理化。
    lean_open: float = Field(default=0.0, ge=-1.0, le=1.0)


class LibraryReq(BaseModel):
    title: str = Field(default="User document", max_length=200)
    text: str = Field(min_length=6, max_length=200000)


@app.post("/api/library")
def import_library(req: LibraryReq):
    added = library.add_facts(library.split_sentences(req.text), source="user:" + req.title)
    return {"added": added, "title": req.title}


class DecreeReq(BaseModel):
    kind: str
    lean_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    text: str = Field(default="", max_length=200)
    target: str | None = None


class FactorReq(BaseModel):
    text: str = Field(default="", max_length=160)
    kind: str = "risk"
    factor_id: str = ""
    active: bool = True


class VerdictReq(BaseModel):
    choice: str


class NoteReq(BaseModel):
    """御笔批注：皇帝把某位大臣的一句话收起来。"""
    minister: str
    text: str = Field(default="", max_length=200)


class MindReq(BaseModel):
    """用户亲手改的心事。四项都给，留空表示这一项不是用户定的。"""
    anxiety: str = Field(default="", max_length=60)
    impulse: str = Field(default="", max_length=60)
    stake: str = Field(default="", max_length=60)
    deadline: str = Field(default="", max_length=60)


def _court(fn, *a):
    try:
        return fn(*a)
    except KeyError:
        raise HTTPException(404, "no such session")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/court")
def open_court(req: OpenReq):
    return _court(court.open_court, req.topic.strip(), req.context.strip(), req.lang, req.lean_open)


@app.get("/api/court/{session_id}")
def court_state(session_id: str):
    return _court(court.snapshot, session_id)


@app.post("/api/court/{session_id}/round")
def court_round(session_id: str):
    return _court(court.next_round, session_id)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_streaming: set[str] = set()


@app.get("/api/court/{session_id}/stream")
def court_stream(session_id: str, after: int = 0):
    """把整场辩论推给前端：每轮一次模型调用，出结果就推。

    一场朝会同时只允许一条流 —— 两个标签页各跑一遍会白花一倍的模型钱。
    """
    def gen():
        if session_id in _streaming:
            yield _sse("error", {"message": "这场朝会已经在别处直播了"})
            return
        _streaming.add(session_id)
        try:
            snap = court.snapshot(session_id)
            seen = after
            stream_until = snap["round"] + 1
            while True:
                for t in snap["turns"][seen:]:
                    yield _sse("turn", t)
                seen = len(snap["turns"])
                yield _sse("state", snap)
                if snap["status"] != "debating" or snap["round"] >= stream_until:
                    break
                snap = court.next_round(session_id)
            yield _sse("done", {"tally": snap["tally"], "status": snap["status"]})
        except KeyError:
            yield _sse("error", {"message": "no such session"})
        except Exception as e:  # 模型层已经吞掉自己的错误，走到这里说明是真的崩了
            yield _sse("error", {"message": f"{type(e).__name__}: {e}"})
        finally:
            _streaming.discard(session_id)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/court/{session_id}/decree")
def court_decree(session_id: str, req: DecreeReq):
    return _court(court.decree, session_id, req.kind, req.lean_delta, req.text, req.target)


@app.post("/api/court/{session_id}/factors")
def court_factors(session_id: str, req: FactorReq):
    return _court(court.factor, session_id, req.text, req.kind, req.factor_id, req.active)


@app.post("/api/court/{session_id}/respond")
def court_respond(session_id: str):
    return _court(court.respond, session_id)


@app.post("/api/court/{session_id}/note")
def court_note(session_id: str, req: NoteReq):
    try:
        return court.add_note(session_id, req.minister, req.text)
    except KeyError:
        raise HTTPException(404, "no such session")
    except ValueError:
        raise HTTPException(400, "no such minister")


@app.post("/api/court/{session_id}/mind")
def court_mind(session_id: str, req: MindReq):
    """用户改心事：追加一行 source=user。它排在拾荒那行后面，所以立刻生效，
    而且拾荒下次重新整理时改不动它（court.read_user 里由代码钉死）。"""
    store.add_user_read(session_id, "user", req.model_dump())
    return _court(court.snapshot, session_id)


@app.post("/api/court/{session_id}/verdict")
def court_verdict(session_id: str, req: VerdictReq):
    if req.choice not in court.VERDICT_ZH:
        raise HTTPException(422, f"choice 必须是 {list(court.VERDICT_ZH)}")
    return _court(court.verdict, session_id, req.choice)


@app.get("/api/evals")
def evals(limit: int = 10):
    return store.list_eval_runs(limit)


@app.get("/api/evals/{run_id}")
def eval_run(run_id: int):
    r = store.get_eval_run(run_id)
    if r is None:
        raise HTTPException(404, "no such eval run")
    return r


@app.get("/")
def console():
    if not CONSOLE.exists():
        return {"ok": True, "hint": "监控台还没建，见 app/back/console/index.html"}
    return FileResponse(CONSOLE)


app.mount("/front", StaticFiles(directory=FRONT, html=True), name="front")
