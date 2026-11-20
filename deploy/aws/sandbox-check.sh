set -eu
python3 - <<'PY'
import ast,json,subprocess,time
from pathlib import Path
root=Path('/opt/lerny/current')
tree=ast.parse((root/'apps/api/tests/test_tracing.py').read_text())
fixtures={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {'BUBBLE_JAVA','LIST_C'}}
def run(lang,source):
    proc=subprocess.run(['runuser','-u','lerny-code','--','python3',str(root/'deploy/trace-sandbox/run_isolated.py'),'python','-m','lerny.tracing.runner','--language',lang],input=source.encode(),capture_output=True,timeout=50)
    if proc.returncode:raise RuntimeError('sandbox_exit_'+str(proc.returncode))
    return json.loads(proc.stdout)
def output(env):return ''.join(e['stdout'] for e in env['events'])
checks={}
for language,name,expected in [('java','BUBBLE_JAVA','1\n'),('c','LIST_C','4\n')]:
    e=run(language,fixtures[name]); checks[language]={'status':e['status'],'events':len(e['events']),'output_ok':output(e)==expected}
    print(json.dumps(checks),flush=True)
    assert e['status']=='runtime_error' and output(e)==expected and len(e['events'])>3
e=run('c','int main(void) {\n int x = 1\n return x;\n}\n')
assert e['status']=='compile_error' and e['compile_error']['line']==3
checks['compile_error_line']=True
probe='''import os, socket
print(os.getuid()==65534)
print(not any(k in os.environ for k in ['DATABASE_URL','SUPABASE_SECRET_KEY','AWS_ACCESS_KEY_ID']))
print(not os.path.exists('/etc/lerny/worker.json'))
try:
    open('/root_write_probe','w').close()
    print(False)
except OSError:
    print(True)
try:
    socket.create_connection(('1.1.1.1',443),timeout=1).close()
    print(False)
except OSError:
    print(True)
print(open('/sys/fs/cgroup/memory.max').read().strip()=='805306368')
print(open('/sys/fs/cgroup/pids.max').read().strip()=='128')
'''
e=run('python',probe)
assert e['status']=='ok' and output(e)=='True\n'*7, {'probe_status':e['status'],'probe_output':output(e)}
checks['isolation']=True
e=run('python','import time\ntime.sleep(20)\n')
assert e['status']=='timeout'
checks['timeout']=True
remaining=subprocess.check_output(['docker','ps','-aq','--filter','label=lerny.sandbox=true'],text=True).strip()
assert not remaining
checks['container_cleanup']=True
print(json.dumps(checks))
PY
