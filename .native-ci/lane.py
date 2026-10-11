"""Isolated exact-pin native build/test lane; no publishing or system changes."""
import hashlib,json,os,pathlib,shutil,subprocess,sys,sysconfig,venv,xml.etree.ElementTree as ET
from audit_wheel import audit,pe
name,version,source_sha,mode=sys.argv[1:]
source=pathlib.Path('source').resolve(); harness=pathlib.Path(__file__).parent.resolve()
root=pathlib.Path('native').resolve();root.mkdir(exist_ok=True)
out=root/'artifacts';out.mkdir(exist_ok=True)
for key in ['PIP_CACHE_DIR','UV_CACHE_DIR','UV_PYTHON_INSTALL_DIR','UV_PYTHON_BIN_DIR','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','NUGET_PLUGINS_CACHE_PATH','VIRTUALENV_OVERRIDE_APP_DATA']:
    os.environ[key]=str(root/key.lower())
os.environ['PYTHONNOUSERSITE']='1'
logindex=0

def run(args,cwd=root,check=True,timeout=600):
    global logindex
    logindex+=1
    args=list(map(str,args));print('RUN',args,flush=True)
    p=subprocess.run(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    (out/f'{logindex:02d}-command.log').write_text(json.dumps(args)+'\n'+p.stdout,encoding='utf-8')
    print(p.stdout,flush=True)
    if check and p.returncode:raise RuntimeError((args,p.returncode))
    return p

provenance={'package':name,'version':version,'source_sha':source_sha,'mode':mode,'wrapper_sha':os.environ['GITHUB_SHA'],'python':sys.version,'platform':sysconfig.get_platform(),'upstream_scope':'full suite' if name!='psutil' else 'selected self-read and owned-child Process tests; excludes system/services/admin/process-wide mutation and stress suites'}
(out/'provenance.json').write_text(json.dumps(provenance,indent=2))
assert sys.platform=='win32' and sysconfig.get_platform()=='win-arm64'
assert pe(pathlib.Path(sys.executable).read_bytes())==0xaa64
assert run(['git','rev-parse','HEAD'],cwd=source).stdout.strip()==source_sha
run(['git','submodule','status','--recursive'],cwd=source)
venv.create(root/'build',with_pip=True);build=root/'build/Scripts/python.exe'
run([build,'-m','pip','install','pip==25.3','setuptools==80.9.0','wheel==0.45.1'])
if mode=='build':
    if name=='httptools':run([build,'-m','pip','install','Cython==0.29.37'])
    run([build,'-m','pip','freeze'])
    run([build,'setup.py','bdist_wheel','--plat-name','win_arm64','--dist-dir',out],cwd=source)
else:
    run([build,'-m','pip','download','--only-binary=:all:','--no-deps','--dest',out,f'{name}=={version}'])
wheel=next(out.glob('*.whl'))
report=audit(wheel,name,version)
if mode=='published':
    import urllib.request
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json') as response:metadata=json.load(response)
    official=next(x for x in metadata['urls'] if x['filename']==wheel.name)
    assert report['sha256']==official['digests']['sha256']
    report['official_url']=official['url'];report['official_sha256']=official['digests']['sha256']
(out/'wheel-audit.json').write_text(json.dumps(report,indent=2))
venv.create(root/'test',with_pip=True);test=root/'test/Scripts/python.exe'
run([test,'-m','pip','install','pytest==8.3.5','pytest-timeout==2.3.1','pytest-cov==6.0.0','flaky==3.8.1','setuptools==80.9.0'])
run([test,'-m','pip','install','--no-deps',wheel])
if name=='watchdog':run([test,'-m','pip','install','PyYAML==6.0.2','eventlet==0.40.3'])
run([test,'-m','pip','freeze'])
run([test,harness/'functional.py',name,version,out/'functional.json'])
if name=='psutil':
    methods=['test_pid','test_kill','test_terminate','test_send_signal','test_wait_exited','test_wait_timeout','test_wait_timeout_nonblocking','test_cpu_percent','test_cpu_times','test_create_time','test_num_threads','test_num_handles','test_threads','test_memory_info','test_memory_full_info','test_memory_percent','test_is_running','test_exe','test_cmdline','test_name','test_status','test_username','test_cwd','test_ppid','test_parent','test_invalid_pid','test_oneshot','test_oneshot_twice']
    tests=root/'psutil_tests';shutil.copytree(source/'psutil/tests',tests,dirs_exist_ok=True)
    # Upstream tests use psutil.tests utilities, shipped in both selected distributions.
    targets=[f'{tests}/test_process.py::TestProcess::{m}' for m in methods]
    p=run([test,'-m','pytest',*targets,'-v','-ra','--timeout=30',f'--junitxml={out}/upstream.xml'],check=False)
    (out/'test-scope.json').write_text(json.dumps({'selected':targets,'excluded':'all other upstream modules and Process methods; bounded no-admin self/owned-child audit, not full psutil suite'},indent=2))
else:
    tests=root/'tests';shutil.copytree(source/'tests',tests,dirs_exist_ok=True)
    if (source/'setup.cfg').exists():shutil.copy2(source/'setup.cfg',root/'setup.cfg')
    p=run([test,'-m','pytest',tests,'-v','-ra','--timeout=45',f'--junitxml={out}/upstream.xml'],check=False,timeout=900)
if (out/'upstream.xml').exists():
    suites=ET.parse(out/'upstream.xml').getroot();cases=list(suites.iter('testcase'))
    summary={'cases':len(cases),'failures':sum(c.find('failure') is not None for c in cases),'errors':sum(c.find('error') is not None for c in cases),'skips':[{'name':c.get('name'),'reason':c.find('skipped').get('message'),'type':c.find('skipped').get('type')} for c in cases if c.find('skipped') is not None]}
    (out/'test-summary.json').write_text(json.dumps(summary,indent=2))
assert p.returncode==0, f'upstream tests failed: {p.returncode}'
