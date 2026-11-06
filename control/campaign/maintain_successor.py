from pathlib import Path
import json,importlib.util,sys
r=Path(__file__).parent
sys.path.insert(0,str(r/'source-1b5e0987/factory'))
from durable.runtime import load_config
from durable.workers import _atomic_json
s=importlib.util.spec_from_file_location('bounded_campaign',r/'campaign_controller.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
runtime=m.BoundedRuntime(load_config(r/'config.json'))
try:
 q=json.loads((r/'campaign-request.json').read_text())
 lease=runtime.pool.acquire(q['case_id'],'082eaf2c52102435929eb23a37c61d1fe29516ebf88da3ac89c6ae5d75d3b67f','aed2a6f04617601bae4eb6350916d6cf7e1b3e4398ff51a42ce5835c636fab8d')
 _atomic_json(r/'campaign-successor-upgraded.json',{'case':q['case_id'],'worker':lease.worker_id,'qualified':True,'plumbing':'082eaf2c52102435929eb23a37c61d1fe29516ebf88da3ac89c6ae5d75d3b67f','model_requests':0})
finally:runtime.close()
