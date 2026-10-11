"""Test only: original wheel preserved; source tests copied into two profiles."""
import hashlib, json, os, pathlib, shutil, struct, subprocess, sys, sysconfig, venv, zipfile
H=pathlib.Path(__file__).resolve().parent
S=pathlib.Path('release-source').resolve(); R=pathlib.Path('profile-work').resolve(); R.mkdir()
O=R/'artifacts'; O.mkdir()
manifest=json.loads((H/'manifest.json').read_text()); arch=sys.argv[1]
for key in ['PIP_CACHE_DIR','UV_CACHE_DIR','NUGet_PACKAGES','VIRTUALENV_OVERRIDE_APP_DATA']:
    os.environ[key]=str(R/key.lower())
os.environ['PYTHONNOUSERSITE']='1'
commands=[]
def run(label,args,cwd=R,check=True,timeout=600):
    args=list(map(str,args)); print('RUN',label,args,flush=True)
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    text=p.stdout+p.stderr; (O/(label+'.log')).write_text(json.dumps(args)+'\n'+text,encoding='utf-8'); print(text,flush=True)
    commands.append({'label':label,'argv':args,'returncode':p.returncode})
    (O/'commands.json').write_text(json.dumps(commands,indent=2))
    if check: assert p.returncode==0, (label,p.returncode)
    return p
assert sysconfig.get_platform()==('win-arm64' if arch=='arm64' else 'win-amd64')
assert run('source-sha',['git','rev-parse','HEAD'],cwd=S).stdout.strip()==manifest['base']
venv.create(R/'venv',with_pip=True); py=R/'venv/Scripts/python.exe'
run('dependencies',[py,'-m','pip','install','pip==25.3','setuptools==80.9.0','wheel==0.45.1','pytest==8.3.5','pytest-timeout==2.3.1','pytest-cov==6.0.0','flaky==3.8.1','PyYAML==6.0.2','eventlet==0.40.3'])
original=next((H/'input').glob('*.whl'))
assert hashlib.sha256(original.read_bytes()).hexdigest()==manifest['original_wheel_sha256']
shutil.copy2(original,O/original.name)
wheel=original
if arch=='x64':
    # Build a distinct AMD64 artifact on the native AMD64 interpreter. Never retag ARM64.
    run('x64-build',[py,'setup.py','bdist_wheel','--dist-dir',O],cwd=S)
    wheel=next(p for p in O.glob('*.whl') if p.name!=original.name)
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(wheel) as b:
        aa={n:a.read(n) for n in a.namelist() if n.startswith('watchdog/')}
        bb={n:b.read(n) for n in b.namelist() if n.startswith('watchdog/')}
        assert aa==bb, 'x64 runtime payload differs'
        (O/'payload-comparison.json').write_text(json.dumps({'equal':True,'members':len(aa),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'x64_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'x64_filename':wheel.name},indent=2))
run('install',[py,'-m','pip','install','--no-deps',wheel])
run('freeze',[py,'-m','pip','freeze'])
shutil.copy2(H/'manifest.json',O/'manifest.json')
shutil.copytree(H/'patches',O/'patches')
for label in ['original','corrected']:
    d=R/label; d.mkdir(); shutil.copytree(S/'tests',d/'tests'); shutil.copy2(S/'setup.cfg',d/'setup.cfg')
    if label=='corrected':
        for patch in sorted((H/'patches').glob('*.patch')):
            run('apply-'+patch.stem,['git','apply','--check',patch],cwd=d)
            run('patch-'+patch.stem,['git','apply',patch],cwd=d)
# Every source test remains original in original/. RED is expected only for witnessed failures.
for name,path in [('rename','tests/test_emitter.py::test_renaming_top_level_directory'),('eventlet','tests/test_skip_repeats_queue.py::test_eventlet_monkey_patching')]:
    run('legacy-'+name,[py,'-m','pytest',path,'-v','-ra','--timeout=45',f'--junitxml={O}/legacy-{name}.xml'],cwd=R/'original',check=False)
# No changes to thread/warning fixtures, no deselect, no blanket xfail.
green=run('corrected-suite',[py,'-m','pytest','tests','-v','-ra','--timeout=45',f'--junitxml={O}/corrected.xml'],cwd=R/'corrected',check=False)
roundtrip=run('roundtrip',[py,H/'roundtrip.py',O/'roundtrip.json'],check=False)
# The exact base src/ files remain unchanged, including Linux code we did not backport.
assert run('source-diff',['git','diff','--exit-code','--','src','tests'],cwd=S).returncode==0
(O/'summary.json').write_text(json.dumps({'arch':arch,'python':sys.version,'platform':sysconfig.get_platform(),'wrapper_sha':os.environ['GITHUB_SHA'],'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'original_wheel_preserved':hashlib.sha256(original.read_bytes()).hexdigest()==manifest['original_wheel_sha256'],'corrected_suite_rc':green.returncode,'roundtrip_rc':roundtrip.returncode,'original_suite_pass':False,'commands':commands},indent=2))
assert green.returncode==roundtrip.returncode==0
