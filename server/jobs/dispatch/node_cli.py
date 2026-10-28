"""Execution-only node commands. No Manager process is started."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys


def node_descriptors(path):
    value=json.loads(Path(path).read_text())
    return value.get("registrations", [value])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("register")
    worker=sub.add_parser("worker");worker.add_argument("args",nargs=argparse.REMAINDER)
    data=sub.add_parser("serve-data");data.add_argument("--bind",default="127.0.0.1");data.add_argument("--port",type=int,default=18000)
    args, unknown=parser.parse_known_args(argv)
    if unknown and args.command != "worker":
        parser.error("unrecognized arguments: " + " ".join(unknown))
    if args.command=="worker":
        os.execv(sys.executable,[sys.executable,"-m","celery","-A","server.jobs.dispatch.node_worker_app:app","worker",*(list(argv) if argv is not None else sys.argv[1:])[1:]])
    import settings
    node_root=Path(os.environ["TR_NODE_STATE_DIR"]);node_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    settings.CACHE_DB_PATH=node_root/"metadata.sqlite"
    settings.CACHE_DIR=node_root
    from .remote import remote_repository_from_env
    remote=remote_repository_from_env()
    if remote is None:raise ValueError("TR_MANAGER_ENDPOINT is required")
    if args.command=="register":
        print(json.dumps(remote.register()));return 0
    from http.server import ThreadingHTTPServer
    from types import SimpleNamespace
    from .node_market import NodeMarketHandler
    root=Path(os.environ["TR_NODE_STATE_DIR"]);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    class Handler(NodeMarketHandler):pass
    Handler.state=SimpleNamespace(
        descriptors=lambda:node_descriptors(Path(os.environ["TR_NODE_DESCRIPTOR_FILE"])),
        provider=os.environ["TR_NODE_MARKET_PROVIDER"])
    ThreadingHTTPServer((args.bind,args.port),Handler).serve_forever()
    return 0


if __name__=="__main__":raise SystemExit(main())
