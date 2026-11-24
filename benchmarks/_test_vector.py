import os
import sys

sys.path.insert(0, r"D:\lea\XenYon code\wsc\src")
os.environ["WSC_CSM_RECALL"] = "vector"
os.environ["WSC_CSM_EMBEDDER"] = "fastembed"
os.environ["WSC_CSM_EMBED_CACHE"] = r"E:\models\fastembed"

from wsc.csm import CSM  # noqa: E402
from wsc.csm.store import CsmStore  # noqa: E402

service = CSM(CsmStore(r"D:\lea\XenYon code\wsc\benchmarks\results\public-exam-v2.db",
                       namespace="public-exam:PUB01"))
for question in ("我昨晚梦到了什么？", "那周几点之前别催我？", "黑色布基胶带最后在哪儿找到的？"):
    hits = service.search(question, limit=3)["results"]
    print(question, "->", [(h["slot"], str(h["value"])[:30], h.get("score")) for h in hits])
