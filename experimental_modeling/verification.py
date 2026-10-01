"""Aggregate report: observing a mesh is never the same as verifying a revision."""
from __future__ import annotations

from dataclasses import replace
import json
from .acceptance import check
from .requirements import RequirementSet, canonical_hash, evaluate

REPORT_VERSION = 1


def preview(value):
    # Keep human-readable scalars, but don't duplicate enormous index/ray arrays
    # into every report. The complete trusted definition remains hash-bound.
    if isinstance(value,dict):return {key:preview(item) for key,item in value.items()}
    if isinstance(value,list):
        if len(json.dumps(value))>1500:return {"items":len(value),"sha256":canonical_hash(value),"detail":"Full array is in the hash-bound policy/requirements document"}
        return [preview(item) for item in value]
    return value


def make_report(result, policy, observation, previous, spec=None):
    spec = spec or RequirementSet.parse({"schema_version":1,"requirements":[]})
    report=evaluate(spec,observation,previous,is_revision=result.get("parent") is not None)
    rows=[]
    for job,title in (("author","Author job completed"),("inspect","Independent inspection job completed"),("roundtrip","GLB roundtrip"),("reopen","Saved Blender scene reopened")):
        completed=result.get("jobs",{}).get(job,{}).get("exit_code")
        rows.append({"id":"pipeline-"+job,"title":title,"kind":"pipeline","hard":True,"applicable":True,
                     "status":"pass" if completed==0 and (job!="inspect" or observation is not None) else "unknown","measured":{"exit_code":completed},"expected":{"exit_code":0},
                     "evidence":{"stage":job,"reason":result.get("observation_error",result.get("error","")) if completed!=0 or (job=="inspect" and observation is None) else ""},"coverage":"Recorded completion of this stage only; other stages and requirements still apply."})
    if result.get("parent") is not None:
        bound=previous is not None and isinstance(result.get("parent_result_hash"),str) and len(result["parent_result_hash"])==64
        rows.append({"id":"parent-reference","title":"Accepted baseline available and hash-bound","kind":"integrity","hard":True,"applicable":True,"status":"pass" if bound else "unknown","measured":{"parent_result_hash":result.get("parent_result_hash"),"observation_available":previous is not None},"expected":{"bound_parent":True},"evidence":{"stage":"preservation_comparison"},"coverage":"A revision cannot skip preservation checks merely because its baseline observation is missing."})
    rows.append({"id":"pipeline-provenance","title":"Source, rules and previous revision integrity","kind":"integrity","hard":True,"applicable":True,
                 "status":"pass" if result.get("provenance_verified") is True else "unknown","measured":{"verified":result.get("provenance_verified",False)},
                 "expected":{"verified":True},"evidence":{"stage":"controller_integrity"},"coverage":"Controller-checked file hashes; native mode is not a hostile-code security boundary."})
    policy_row={"id":"policy-overall","title":"Declared parts, geometric policy and revision scope","kind":"policy","hard":True,"applicable":True,"status":"unknown","measured":None,"expected":{"all_declared_policy_checks_pass":True},"evidence":{"stage":"policy_geometry"},"coverage":"Includes exact semantic-part inventory, removed/new-part scope and complete preserved-part comparisons."}
    if observation is not None:
        try:
            failures=check(policy,observation,previous)
            policy_row["status"]="fail" if failures else "pass";policy_row["measured"]={"failures":failures}
        except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:policy_row["evidence"]["reason"]=str(exc)[:300]
    rows.append(policy_row)
    for index,constraint in enumerate(policy.constraints):
        row={"id":f"policy-{index+1:03d}","title":f"{constraint.part}: {constraint.kind.replace('_',' ')}","kind":constraint.kind,
             "hard":True,"applicable":True,"status":"unknown","measured":None,"expected":constraint.data,
             "evidence":{"stage":"policy_geometry","part":constraint.part},"coverage":"Version-1 geometric policy check over the inspected mesh."}
        if observation is not None:
            try:
                isolated=replace(policy,changed_parts=policy.parts,constraints=(constraint,))
                failures=check(isolated,observation,previous)
                row["status"]="fail" if failures else "pass"
                row["measured"]=failures if failures else {"check_completed":True}
            except (ValueError,KeyError,TypeError,IndexError) as exc:row["evidence"]["reason"]=str(exc)[:300]
        rows.append(row)
    if previous is not None:
        for name in policy.parts:
            if name in policy.changed_parts:continue
            statuses={key:observation is not None and name in previous["parts"] and observation["parts"].get(name,{}).get(key)==previous["parts"][name].get(key) for key in ("geometry_hash","transform_hash","material_hash")}
            rows.append({"id":"preserved-"+name,"title":name+": preserved whole part","kind":"preserved_part","hard":True,"applicable":True,
                         "status":("pass" if all(statuses.values()) else "fail") if observation is not None else "unknown","measured":statuses,"expected":{"all_components_equal":True},
                         "evidence":{"stage":"preservation_comparison","parent":result.get("parent")},"coverage":"Complete geometry, transform and material fingerprints versus the actual accepted parent."})
    rows.extend(report["requirements"])
    for row in rows:
        row["expected"]=preview(row.get("expected"));row["measured"]=preview(row.get("measured"))
    report.update({"schema_version":REPORT_VERSION,"revision":result["revision"],"parent":result.get("parent"),"build_status":result["status"],"execution_mode":result.get("execution_mode","unknown"),"security_boundary":result.get("security_boundary","unknown"),
                   "requirements":rows,"summary":{status:sum(row["status"]==status for row in rows) for status in ("pass","fail","unknown")},
                   "bindings":{"policy_hash":result.get("policy_hash"),"requirements_hash":report["requirements_hash"],"runtime_hash":result.get("runtime_hash"),"source_files":{"count":len(result.get("source_files",{})),"sha256":canonical_hash(result.get("source_files",{}))},"parent_result_hash":result.get("parent_result_hash"),"requirements_lock_hash":result.get("requirements_lock_hash")}})
    report["machine_verified"]=(result["status"]=="accepted" and all(row["status"]=="pass" for row in rows if row["hard"] and row["applicable"]))
    report["human_accepted"]=False  # Human decisions live outside immutable machine artifacts.
    return report


def validate_saved_report(report, expected):
    """Recompute rather than trusting report-authored required/applicable flags."""
    if not isinstance(report,dict) or report.get("schema_version")!=REPORT_VERSION:
        raise ValueError("unsupported verification report version")
    if canonical_hash(report)!=canonical_hash(expected):
        raise ValueError("verification report does not match trusted requirements and evidence")
