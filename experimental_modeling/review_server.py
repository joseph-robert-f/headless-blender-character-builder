"""Local-only review program. Serves one trusted store; never executes model code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import unquote, urlsplit

from .contracts import Policy, identifier, read_json
from .controller import digest, regular_tree, safe_path, store_lock, write_json, sync_directory
from .requirements import RequirementSet, canonical_hash
from .verification import make_report, validate_saved_report

MAX_BODY = 16384
STATIC = Path(__file__).with_name("review_static")
RESULT_HASH = re.compile(r"[0-9a-f]{64}\Z")


def now(): return datetime.now(timezone.utc).isoformat()


def verified_revision(store: Path, revision: str):
    identifier(revision)
    candidates=[store/group/revision for group in ("accepted","attempts") if (store/group/revision).exists() or (store/group/revision).is_symlink()]
    if len(candidates)!=1:raise ValueError("revision missing or ambiguous")
    directory=safe_path(candidates[0])
    if not directory.is_relative_to(store):raise ValueError("revision escaped project store")
    result=read_json(directory/"result.json")
    if result.get("schema_version")!=1 or result.get("revision")!=revision or result.get("status") not in ("accepted","rejected","needs_review"):
        raise ValueError("invalid revision result")
    manifest=result.get("artifacts")
    if not isinstance(manifest,dict):raise ValueError("missing artifact manifest")
    actual={str(p.relative_to(directory)):digest(p) for p in regular_tree(directory) if p!=directory/"result.json"}
    if actual!=manifest:raise ValueError("artifact integrity mismatch")
    result_hash=digest(directory/"result.json")
    pointer=store/"last_good.json"
    if result["status"]=="accepted" and (pointer.exists() or pointer.is_symlink()):
        current=read_json(pointer)
        if current.get("revision")==revision and current.get("result_hash")!=result_hash:raise ValueError("last-good result hash mismatch")
    return directory,result,result_hash


def accepted_bindings(store):
    """Follow the last-good hash chain; old unbound history is not upgraded."""
    pointer=store/"last_good.json"
    if not pointer.exists() and not pointer.is_symlink():return {}
    current=read_json(pointer);revision=identifier(current["revision"]);expected=current["result_hash"]
    bindings={}
    for _ in range(256):
        if revision in bindings:raise ValueError("cyclic accepted revision history")
        path=safe_path(store/"accepted"/revision/"result.json")
        if digest(path)!=expected:raise ValueError("accepted history result hash mismatch")
        value=read_json(path)
        if value.get("revision")!=revision or value.get("status")!="accepted":raise ValueError("invalid accepted history")
        bindings[revision]=expected
        if value.get("parent") is None or value.get("parent_result_hash") is None:return bindings
        revision=identifier(value["parent"]);expected=value["parent_result_hash"]
    raise ValueError("accepted history exceeds review limit")


class ReviewProject:
    def __init__(self, store: Path):
        self.store=safe_path(store)
        if not self.store.is_dir():raise ValueError("review requires an existing local project store")
        self.token=secrets.token_urlsafe(32)
        self._mutex=threading.Lock()
        self._reports={}
        self.metadata=self.store/"review"
        safe_path(self.metadata)
        self.metadata.mkdir(exist_ok=True, mode=0o700)
        for name in ("acceptances","requests"):
            safe_path(self.metadata/name);(self.metadata/name).mkdir(exist_ok=True, mode=0o700)

    def state(self, revision, result_hash):
        path=safe_path(self.metadata/"acceptances"/(revision+".json"))
        if path.exists() or path.is_symlink():
            state=read_json(path)
            if state.get("schema_version")!=1 or state.get("result_hash")!=result_hash:
                raise ValueError("human review state targets different artifact")
            return {"human_accepted":True,"accepted_at":state["accepted_at"],"notes":state["notes"]}
        return {"human_accepted":False,"accepted_at":None,"notes":""}

    def revision(self, revision):
        directory,result,result_hash=verified_revision(self.store,revision)
        bindings=accepted_bindings(self.store)
        if revision in bindings and bindings[revision]!=result_hash:raise ValueError("revision is not the bound accepted result")
        try:observation=read_json(directory/"inspection/observation.json") if (directory/"inspection/observation.json").is_file() else None
        except (ValueError,OSError):observation=None
        previous=None
        parent_hash=None
        if result.get("parent") is not None:
            parent_dir,parent,parent_hash=verified_revision(self.store,identifier(result["parent"]))
            if parent["status"]!="accepted":raise ValueError("parent is not an accepted machine revision")
            previous=read_json(parent_dir/"inspection/observation.json")
        report_path=directory/"verification.json"
        if report_path.is_file():
            spec=RequirementSet.parse(read_json(directory/"requirements.json"))
            lock_path=self.store/"requirements.json"
            active_spec=RequirementSet.parse(read_json(lock_path)) if lock_path.exists() or lock_path.is_symlink() else None
            if result.get("requirements_lock_hash") is not None and (active_spec is None or canonical_hash(active_spec.raw)!=result["requirements_lock_hash"]):
                raise ValueError("required project rules were removed or changed")
            if result.get("requirements_hash")!=canonical_hash(spec.raw):raise ValueError("locked requirements binding mismatch")
            if canonical_hash(read_json(directory/"requirements.json"))!=canonical_hash(spec.raw):raise ValueError("attempt rules differ from locked project rules")
            policy=Policy.parse(read_json(directory/"policy.json"))
            if digest(directory/"policy.json")!=result["policy_hash"]:raise ValueError("policy binding mismatch")
            if result.get("parent_result_hash") is not None and result["parent_result_hash"]!=parent_hash:raise ValueError("parent result hash mismatch")
            key=(revision,result_hash,canonical_hash(spec.raw),parent_hash)
            report=read_json(report_path)
            if key not in self._reports:
                expected=make_report(result,policy,observation,previous,spec)
                validate_saved_report(report,expected)
                if len(self._reports)>=128:self._reports.clear()
                self._reports[key]=report
            else:
                validate_saved_report(report,self._reports[key])
            # Historical builds remain inspectable, but newer project rules and
            # absent baseline bindings cannot silently inherit a verified badge.
            gaps=[]
            if result["status"]=="accepted" and revision not in bindings:gaps.append("Revision is not anchored by the current accepted history")
            if active_spec is not None and canonical_hash(active_spec.raw)!=canonical_hash(spec.raw):gaps.append("Project requirements were introduced after this build")
            if result.get("parent") is not None and result.get("parent_result_hash") is None:gaps.append("Historical parent result is not cryptographically bound")
            if gaps:
                report=json.loads(json.dumps(report))
                report["requirements"].append({"id":"current-evidence-gap","title":"Current verification coverage incomplete","status":"unknown","hard":True,"applicable":True,"measured":None,"expected":{"current_requirements_and_bound_parent":True},"evidence":{"stage":"aggregate","reason":"; ".join(gaps)},"coverage":"Rebuild under the current locked requirements and parent binding."})
                report["summary"]["unknown"]+=1;report["machine_verified"]=False
        else:
            report={"schema_version":1,"machine_verified":False,"summary":{"pass":0,"fail":0,"unknown":1},
                    "requirements":[{"id":"legacy-report","title":"Versioned verification report unavailable","status":"unknown","hard":True,"applicable":True,
                                     "measured":None,"expected":{"report_version":1},"evidence":{"stage":"aggregate","reason":"Legacy artifacts may have prior checks, but this review layer has no bound aggregate report"},"coverage":"Rebuild through the current trusted controller to obtain versioned evidence."}]}
        state=self.state(revision,result_hash)
        state["verification_current"]=report["machine_verified"]
        views=[]
        for view in ("front","right","top","iso"):
            rel=f"inspection/views/{view}.png"
            if rel in result["artifacts"]:views.append({"label":view.title(),"url":f"/artifacts/{revision}/view-{view}"})
        meta={"id":revision,"parent":result.get("parent"),"result_hash":result_hash,"status":result["status"],"intent":result.get("intent",""),
              "machine_verified":report["machine_verified"],"human_accepted":state["human_accepted"],"execution_mode":result.get("execution_mode","unknown"),"security_boundary":result.get("security_boundary","unknown")}
        return {"revision":meta,"report":report,"observation":observation,"parent_observation":previous,"state":state,
                "artifacts":{"views":views,"glb_url":f"/artifacts/{revision}/glb" if "inspection/model.glb" in result["artifacts"] else None}}

    def project(self):
        revisions=[]
        for group in ("accepted","attempts"):
            root=safe_path(self.store/group)
            if not root.exists():continue
            for path in sorted(root.iterdir()):
                try:
                    identifier(path.name)
                    response=self.revision(path.name)
                    meta=response["revision"]
                    meta["created_at"]=None  # Filesystem copy/extraction times are not revision times.
                    revisions.append(meta)
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}",path.name):
                        revisions.append({"id":path.name,"status":"integrity_error","machine_verified":False,"human_accepted":False,"error":str(exc)[:300]})
        latest=None
        pointer=self.store/"last_good.json"
        if pointer.exists() or pointer.is_symlink():
            value=read_json(pointer);identifier(value["revision"])
            _,_,result_hash=verified_revision(self.store,value["revision"])
            if result_hash!=value.get("result_hash"):raise ValueError("last-good pointer integrity mismatch")
            latest=value["revision"]
        by_id={revision["id"]:revision for revision in revisions}
        def depth(revision,seen=()):
            parent=revision.get("parent")
            if parent not in by_id:return 0
            if parent in seen:raise ValueError("cyclic revision history")
            if len(seen)>256:raise ValueError("revision history exceeds review limit")
            return 1+depth(by_id[parent],seen+(revision["id"],))
        # The controller creates rejected siblings before an accepted child can
        # advance the same parent. Causal order survives copying/unzipping stores.
        revisions.sort(key=lambda r:(depth(r),r.get("status")=="accepted",r["id"]))
        return {"schema_version":1,"project_name":self.store.name,"csrf_token":self.token,"revisions":revisions,"latest_revision":latest,
                "execution":"Review only: this program does not execute source code or call a language model","requests":self.requests()}

    def requests(self):
        result=[]
        directory=safe_path(self.metadata/"requests")
        for path in sorted(directory.glob("*.json")):
            value=read_json(path)
            if value.get("schema_version")!=1 or value.get("status")!="queued" or value.get("execution")!="not_started":raise ValueError("unsupported queue record")
            result.append(value)
        return sorted(result,key=lambda r:r["created_at"])[-50:]

    def accept(self, revision, payload):
        if set(payload)!={"csrf_token","expected_result_hash","notes"}:raise ValueError("unexpected acceptance fields")
        expected=payload["expected_result_hash"];notes=payload["notes"]
        if not isinstance(expected,str) or not RESULT_HASH.fullmatch(expected):raise ValueError("invalid result hash")
        if not isinstance(notes,str) or len(notes)>2000:raise ValueError("review notes must be at most 2000 characters")
        with self._mutex, store_lock(self.store):
            response=self.revision(revision)
            if response["revision"]["result_hash"]!=expected:raise Conflict("revision changed; reload before accepting")
            if not response["report"]["machine_verified"]:raise Conflict("failed or not-verified requirements cannot be human-accepted")
            state=response["state"]
            if state["human_accepted"]:return state
            record={"schema_version":1,"revision":revision,"result_hash":expected,"accepted_at":now(),"notes":notes}
            write_json(safe_path(self.metadata/"acceptances"/(revision+".json")),record)
            sync_directory(self.metadata/"acceptances")
            state=self.state(revision,expected);state["verification_current"]=True
            return state

    def request(self,payload):
        if set(payload)!={"csrf_token","revision_id","expected_result_hash","prompt"}:raise ValueError("unexpected revision request fields")
        revision=identifier(payload["revision_id"]);expected=payload["expected_result_hash"];prompt=payload["prompt"]
        if not isinstance(expected,str) or not RESULT_HASH.fullmatch(expected):raise ValueError("invalid result hash")
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=8000 or len(prompt)>8000:raise ValueError("revision request must contain 1–8000 characters")
        with self._mutex,store_lock(self.store):
            response=self.revision(revision)
            if response["revision"]["result_hash"]!=expected:raise Conflict("revision changed; reload before requesting an edit")
            identity=hashlib.sha256((revision+'\0'+expected+'\0'+prompt).encode()).hexdigest()[:24]
            path=safe_path(self.metadata/"requests"/(identity+".json"))
            if not path.exists():
                if len(list((self.metadata/"requests").glob("*.json")))>=256:raise Conflict("The local request queue is full; inspect queued requests before adding more")
                write_json(path,{"schema_version":1,"request_id":identity,"status":"queued","revision_id":revision,"result_hash":expected,"prompt":prompt,"created_at":now(),"execution":"not_started"})
                sync_directory(self.metadata/"requests")
            else:read_json(path)
            return {"request_id":identity,"status":"queued","message":"Saved for a coding agent to consume. No model execution has started."}

    def artifact(self,revision,role):
        directory,result,_=verified_revision(self.store,revision)
        roles={"glb":("inspection/model.glb","model/gltf-binary"),**{"view-"+view:(f"inspection/views/{view}.png","image/png") for view in ("front","right","top","iso")}}
        if role not in roles:raise ValueError("unknown artifact role")
        rel,mime=roles[role]
        if rel not in result["artifacts"]:raise ValueError("artifact unavailable")
        path=safe_path(directory/rel)
        if not path.is_relative_to(directory) or digest(path)!=result["artifacts"][rel]:raise ValueError("artifact integrity mismatch")
        return path,mime


class Conflict(ValueError):pass


class LocalReviewServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def __init__(self,project,port=0):
        self.project=project
        super().__init__(("127.0.0.1",port),ReviewHandler)
        self.origin=f"http://127.0.0.1:{self.server_port}"


class ReviewHandler(BaseHTTPRequestHandler):
    server_version="LocalModelReview/1"
    def setup(self):
        super().setup();self.connection.settimeout(10)
    def log_message(self,format,*args):pass  # No user prompt/CSRF values in access logs.
    def send_headers(self,status,mime,size):
        self.send_response(status);self.send_header("Content-Type",mime);self.send_header("Content-Length",str(size))
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer");self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; font-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
    def json(self,status,value):
        data=json.dumps(value,allow_nan=False).encode();self.send_headers(status,"application/json; charset=utf-8",len(data));self.wfile.write(data)
    def boundary(self,post=False):
        if self.headers.get("Host")!=self.server.origin.removeprefix("http://"):raise PermissionError("invalid local Host")
        origin=self.headers.get("Origin")
        if (post and origin!=self.server.origin) or (origin is not None and origin!=self.server.origin):raise PermissionError("cross-origin access denied")
        if self.headers.get("Sec-Fetch-Site") not in (None,"none","same-origin"):raise PermissionError("cross-site access denied")
    def route(self):
        raw=urlsplit(self.path)
        if raw.scheme or raw.netloc or raw.query or raw.fragment:raise ValueError("invalid route")
        path=unquote(raw.path)
        if '\\' in path or '\0' in path or any(p in ('.','..') for p in path.split('/')):raise ValueError("invalid route path")
        return path
    def do_GET(self):
        try:
            self.boundary();path=self.route();project=self.server.project
            if path=="/api/project":return self.json(200,project.project())
            if path=="/api/requests":return self.json(200,project.requests())
            if path.startswith("/api/revisions/"):
                revision=path.removeprefix("/api/revisions/");return self.json(200,project.revision(identifier(revision)))
            if path.startswith("/artifacts/"):
                parts=path.split('/')
                if len(parts)!=4:raise ValueError("invalid artifact route")
                file,mime=project.artifact(identifier(parts[2]),parts[3])
            else:
                static={"/":"index.html","/static/app.js":"app.js","/static/style.css":"style.css"}
                if path not in static:return self.json(404,{"error":"Not found"})
                file=STATIC/static[path];mime={".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8"}[file.suffix]
            data=file.read_bytes();self.send_headers(200,mime,len(data));self.wfile.write(data)
        except PermissionError as exc:self.json(403,{"error":str(exc)})
        except (ValueError,OSError,KeyError,TypeError) as exc:self.json(409,{"error":str(exc)[:300]})
    def do_POST(self):
        try:
            self.boundary(post=True);path=self.route()
            if self.headers.get("Content-Type")!="application/json" or self.headers.get("Transfer-Encoding") is not None:raise ValueError("JSON body required")
            length=self.headers.get("Content-Length","")
            if not length.isdigit() or not 0<int(length)<=MAX_BODY:raise ValueError("invalid bounded content length")
            payload=json.loads(self.rfile.read(int(length)),parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
            if not isinstance(payload,dict) or not isinstance(payload.get("csrf_token"),str) or not secrets.compare_digest(payload["csrf_token"],self.server.project.token):raise PermissionError("invalid CSRF token")
            if path.startswith("/api/revisions/") and path.endswith("/accept"):
                revision=identifier(path[len("/api/revisions/"):-len("/accept")]);return self.json(200,self.server.project.accept(revision,payload))
            if path=="/api/requests":return self.json(200,self.server.project.request(payload))
            return self.json(404,{"error":"Not found"})
        except PermissionError as exc:self.json(403,{"error":str(exc)})
        except Conflict as exc:self.json(409,{"error":str(exc)})
        except BlockingIOError:self.json(409,{"error":"Another build or review operation holds the project lock; retry when it finishes"})
        except (ValueError,OSError,KeyError,TypeError) as exc:self.json(400,{"error":str(exc)[:300]})


def serve(store, port=0):
    if not 0<=port<=65535:raise ValueError("port must be 0..65535")
    server=LocalReviewServer(ReviewProject(store),port)
    print(f"Local model review: {server.origin}",flush=True)
    print("Review only. Revision requests are saved, not executed. Press Ctrl-C to stop.",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--store',type=Path,required=True);parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();serve(args.store,args.port)


if __name__=='__main__':main()
