"""Check the paper-first switch: live only when ALPACA_PAPER is false AND allow_live is set."""
import os
import sys

sys.path.insert(0, sys.argv[1])
os.environ["ALPACA_API_KEY"] = "PKTESTDUMMYKEY000000"
os.environ["ALPACA_API_SECRET"] = "test-dummy-secret"

from insider_tracker import alpaca_client, cli  # noqa: E402

bad = 0
for value in ["true", "1", "yes", "on", "y", "paper", "ture", "", " false ", "false", "0", "no", "FALSE"]:
    for allow in (False, True):
        os.environ["ALPACA_PAPER"] = value
        c = alpaca_client.AlpacaClient(allow_live=allow)
        want_live = value.strip().lower() in ("0", "false", "no") and allow
        okay = (not c.paper) == want_live
        bad += not okay
        print(f"ALPACA_PAPER={value!r:10} --live={str(allow):5} -> {'LIVE ' if not c.paper else 'paper'}  {c.client._base_url}  {'ok' if okay else 'WRONG'}")
os.environ.pop("ALPACA_PAPER")
c = alpaca_client.AlpacaClient()
print(f"ALPACA_PAPER unset      --live=False -> {'LIVE ' if not c.paper else 'paper'}")
bad += not c.paper

import argparse  # noqa: E402
import inspect  # noqa: E402

src = inspect.getsource(cli)
print("cli passes the flag through:", "AlpacaClient(allow_live=live)" in src and "live=args.live" in src)
bad += not ("AlpacaClient(allow_live=live)" in src and "live=args.live" in src)
print("RESULT:", "all correct" if not bad else f"{bad} wrong")
sys.exit(1 if bad else 0)
