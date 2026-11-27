"""Prepare an offline update for the two verified installed AI-team entry points."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
HASHES={
  "orangepi-ai-team":"42adb768ff9204aa06f01ca752dfa798199c58978f3e4d1a60112d804bb4a58d",
  "orangepi-ai-improvement":"7ee6afbc2b4db07096a95285183fafd5a0e9071c023312243ea5789106ca63fc",
}


def replace(source,old,new):
    if source.count(old)!=1:raise ValueError("Installed source differs from the reviewed entry point.")
    return source.replace(old,new)


def stage(original,dest):
    dest.mkdir(mode=0o700,parents=True,exist_ok=True)
    for n,h in HASHES.items():
        b=(original/n).read_bytes()
        if hashlib.sha256(b).hexdigest()!=h:raise ValueError("Original source hash differs: "+n)
        s=b.decode()
        if n=="orangepi-ai-team":
            s=replace(s,'    args = parser.parse_args()','''    parser.add_argument("--review-kind",choices=("controller","ai-policy"))
    parser.add_argument("--review-proposal",type=Path)
    parser.add_argument("--review-sha256")
    parser.add_argument("--check-local-review",action="store_true",help="Read-only hardware test of all local reviewers")
    args = parser.parse_args()
    if args.check_local_review or any((args.review_kind,args.review_proposal,args.review_sha256)):
        from orangepi_model_review import review, Held
        fields=(args.review_kind,args.review_proposal,args.review_sha256)
        if args.question or args.interactive or (args.check_local_review and any(fields)) or (not args.check_local_review and not all(fields)):
            parser.error("Choose a local reviewer check or one exact proposal kind, file and digest")
        if not 120<=args.budget_seconds<=900:parser.error("Review time budget must be 120 to 900 seconds")
        try:
            answer=review(globals(),"diagnostic" if args.check_local_review else args.review_kind,
                          args.review_proposal,args.review_sha256,args.budget_seconds)
        except (Held,OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
            answer={"status":"pending","reason":str(exc) if isinstance(exc,Held) else "review_unavailable"}
        print(json.dumps(answer,sort_keys=True))
        return 0 if answer["status"] in ("ready_for_owner","diagnostic_complete") else 2''')
            s=replace(s,'    context = (\n        "APPROVED POST-FLIGHT CONTEXT', '''    from orangepi_model_review import telemetry
    context = (
        "LIVE LOCAL CONTROLLER MONITOR (missing fields are unknown, no positions or control access):\\n"
        + json.dumps(telemetry(),sort_keys=True) + "\\n\\n"
        "APPROVED POST-FLIGHT CONTEXT''')
        else:
            s=replace(s,'    candidate = validated(payload["candidate"])','''    from orangepi_model_review import eligibility,owner_approved
    verdict=eligibility("ai-policy",path,expected)
    if verdict["status"]!="ready_for_owner":
        raise RuntimeError("All required model reviews must pass: " + verdict["reason"])
    if not owner_approved("ai-policy",expected,verdict):
        raise RuntimeError("The signed-in owner must approve this exact reviewed change in Field Change Review")
    candidate = validated(payload["candidate"])''')
            s=replace(s,'    print(json.dumps({"processed": len(results), "results": results}, indent=2))','''    from orangepi_model_review import review_pending
    print(json.dumps({"processed":len(results),"results":results,"model_review":review_pending()},indent=2))''')
        compile(s,n,"exec")
        out=dest/n
        out.write_bytes(s.encode());out.chmod(0o755)
    out=dest/"orangepi_model_review.py"
    shutil.copyfile(HERE/out.name,out);out.chmod(0o644)
    print("Prepared checked model review entry points and module.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original",type=Path);parser.add_argument("destination",type=Path)
    args=parser.parse_args();stage(args.original,args.destination)
